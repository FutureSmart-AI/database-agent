"""High cardinality utilities: batch entity extraction, Qdrant retrieval, SQL-oriented suffix."""
from __future__ import annotations
from agent.utils.model_profiles import response_text
from agent.utils.model_profiles import operation_config, build_chat_model, load_profile, ModelConfigurationError

import json
import os
import re
import asyncio
from typing import Any, Dict, List, Optional, Tuple

from agent.config.hybrid_entity_resolver_settings import HybridEntityResolverSettings

from agent.utils.openai_chat_kwargs import product_chat_openai as ChatOpenAI
from langsmith import traceable
from pydantic import BaseModel, Field

try:
    from langchain_groq import ChatGroq
except Exception:
    ChatGroq = None

try:
    from langchain_anthropic import ChatAnthropic
except Exception:
    ChatAnthropic = None

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except Exception:
    ChatGoogleGenerativeAI = None

from agent.utils.prompts import get_batch_hc_entity_prompt_template
from agent.utils.high_cardinality_qdrant_utils import get_cardinality_store, _embedding_api_key_var
from knowledge.db_utils.hc_profile_db_utils import get_hc_text_search_columns, get_hc_text_search_samples
from agent.utils.model_config_loader import load_model_config
from agent.utils.owner_credential_utils import get_llm_api_key, get_openai_compatible_base_url
from agent.utils.openai_chat_kwargs import structured_tool_chat_kwargs
from logger import logger


class HCExtractionRow(BaseModel):
    table_name: str = Field(..., description="Table name from configuration")
    column_name: str = Field(..., description="Column name from configuration")
    entities: List[str] = Field(
        default_factory=list,
        description="Phrases from the user query referring only to this column.",
    )


class BatchHCExtraction(BaseModel):
    rows: List[HCExtractionRow] = Field(
        ...,
        description="One row per high-cardinality column, same order as the system prompt list.",
    )


class BatchExpansionRow(BaseModel):
    entity: str = Field(..., description="Original entity term")
    expanded_keywords: str = Field(
        ...,
        description=(
            "Single enriched sentence for embedding. For category inputs: weave in "
            "6-10 concrete sub-types as a natural sentence. For specific inputs: "
            "return unchanged. No comma lists."
        ),
    )


class BatchExpansionResult(BaseModel):
    expansions: List[BatchExpansionRow] = Field(
        ..., description="One row per input entity, same order as the numbered list"
    )


class BatchRefinementRow(BaseModel):
    table_name: str = Field(..., description="Table name from input")
    column_name: str = Field(..., description="Column name from input")
    relevant_values: List[str] = Field(
        default_factory=list,
        description=(
            "Subset of Candidates that plausibly satisfy the user query. "
            "Include every value that could be needed; omit only values that are clearly unrelated "
            "to what the user asked. Prefer false positives over false negatives."
        ),
    )


class BatchRefinementResult(BaseModel):
    results: List[BatchRefinementRow] = Field(
        ..., description="One row per column, same order as the numbered list"
    )


def _extract_hc_payload(raw_value) -> str | None:
    if hasattr(raw_value, "_mapping") or hasattr(raw_value, "_fields"):
        try:
            raw_value = tuple(raw_value)
            logger.info(f"[HC] Converted SQLAlchemy Row → tuple: {raw_value}")
        except Exception as e:
            logger.warning(f"[HC] Could not convert Row to tuple: {e}")
            return None

    if isinstance(raw_value, (tuple, list)):
        payload = raw_value[0] if raw_value else None
    elif isinstance(raw_value, (str, dict)):
        payload = raw_value
    else:
        logger.info(f"[HC] Unexpected payload type after Row check: {type(raw_value)} — returning empty")
        return None

    return payload


def _sql_string_literal(value: str) -> str:
    """Escape single quotes for SQL string literals."""
    return (value or "").replace("'", "''")


def _expand_entity_alternatives(entities: List[str]) -> List[str]:
    """Split phrases like 'iPhone or Samsung' into separate retrieval queries."""
    expanded: List[str] = []
    for raw in entities:
        e = (raw or "").strip()
        if not e:
            continue
        parts = re.split(r"\s+/\s+|\s+or\s+", e, flags=re.IGNORECASE)
        if len(parts) > 1:
            expanded.extend(p.strip() for p in parts if p.strip())
        else:
            expanded.append(e)
    return expanded


def _format_hc_literal_predicate(table_name: str, column_name: str, canonical_values: List[str]) -> str:
    """Build `col = 'x'` or `col IN ('a','b')` with SQL-safe quoting."""
    escaped = [_sql_string_literal(v) for v in canonical_values if v and str(v).strip()]
    if not escaped:
        return ""
    if len(escaped) == 1:
        return f"{table_name}.{column_name} = '{escaped[0]}'"
    inner = ", ".join(f"'{v}'" for v in escaped)
    return f"{table_name}.{column_name} IN ({inner})"


def _normalize_batch_to_map(
    filtered_columns: List[Dict[str, Any]],
    batch: BatchHCExtraction,
) -> Dict[str, List[str]]:
    expected = {f"{c['table_name']}.{c['column_name']}": [] for c in filtered_columns}
    for row in batch.rows:
        key = f"{row.table_name.strip()}.{row.column_name.strip()}"
        if key not in expected:
            continue
        ents = [e.strip() for e in row.entities if isinstance(e, str) and e.strip()]
        expected[key] = ents
    return expected


def _build_entity_llm(provider_lower, model_name, temperature, api_key):
    return _build_llm_with_structured_output(provider_lower, model_name, temperature, api_key, BatchHCExtraction)


def _build_llm_with_structured_output(provider_lower, model_name, temperature, api_key, output_schema, max_tokens=None):
    operation = {BatchHCExtraction: "entity_extraction", BatchExpansionResult: "entity_expansion",
                 BatchRefinementResult: "entity_refinement"}[output_schema]
    conf = operation_config(f"sql_agent.{operation}")
    if max_tokens is not None:
        conf["max_tokens"] = min(conf["max_tokens"], max_tokens)
    base = build_chat_model(conf, api_key=api_key)
    method = {} if conf["provider"] in ("google", "anthropic") else {"method": "json_mode" if conf["provider"] == "deepseek" else "function_calling"}
    return base.with_structured_output(output_schema, **method)


@traceable(run_type="llm", name="hc_batch_entity_extraction")
async def batch_extract_entities_for_hc_columns(
    query: str,
    filtered_columns: List[Dict[str, Any]],
    owner_id: Optional[str],
) -> Dict[str, List[str]]:
    """One LLM call: extract entities for every high-cardinality column (Pydantic structured output)."""
    if not filtered_columns:
        return {}

    ec_cfg = operation_config("sql_agent.entity_extraction")
    provider, model_name = ec_cfg["provider"], ec_cfg["model"]
    temperature = ec_cfg.get("temperature")

    api_key = await get_llm_api_key(owner_id, model_name, provider) if owner_id else None
    prompt_tpl = get_batch_hc_entity_prompt_template(filtered_columns)
    llm = _build_entity_llm(provider, model_name, temperature, api_key)
    chain = prompt_tpl | llm

    # Log the actual system prompt to verify which version is live
    try:
        from agent.utils.prompts import build_batch_hc_entity_extraction_system_text
        _sys = build_batch_hc_entity_extraction_system_text(filtered_columns)
        logger.info("[HC] entity_extraction_system_prompt_preview=\n%s", _sys[:600])
    except Exception:
        pass

    logger.info(
        f"[HC] batch entity extraction | provider={provider} model={model_name} | n_columns={len(filtered_columns)}"
    )
    result = await chain.ainvoke({"query": query})
    if isinstance(result, BatchHCExtraction):
        batch = result
    elif isinstance(result, dict):
        batch = BatchHCExtraction(**result)
    else:
        batch = BatchHCExtraction.model_validate(result)
    return _normalize_batch_to_map(filtered_columns, batch)


def _dedup_expansion_keywords(raw: str, max_terms: int = 7) -> str:
    """Post-process comma-separated expansion output.

    1. Split, strip, drop empties.
    2. Case-insensitive dedup — keep first occurrence.
    3. Token-set subset dedup — drop term A when its tokens are a proper
       subset of term B's tokens (A is the less-specific form).
       e.g. "phone" ⊂ "mobile phone" → drop "phone".
    4. Hard slice to max_terms.
    """
    terms = [t.strip() for t in raw.split(",") if t.strip()]

    seen: set = set()
    deduped: List[str] = []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            deduped.append(t)

    tokenized = [set(re.findall(r"[a-z0-9]+", t.lower())) for t in deduped]
    keep = [True] * len(deduped)
    for i in range(len(deduped)):
        if not keep[i] or not tokenized[i]:
            continue
        for j in range(len(deduped)):
            if i == j or not keep[j] or not tokenized[j]:
                continue
            if tokenized[i] < tokenized[j]:  # proper subset → i is less specific → drop
                keep[i] = False
                break

    return ", ".join([t for t, k in zip(deduped, keep) if k][:max_terms])


async def _expand_entity_for_vector_search(
    entity: str,
    table_name: str,
    column_name: str,
    column_description: str,
    api_key: Optional[str],
    provider: str = None,
    model_name: str = None,
) -> str:
    """Expand a raw entity term into richer search text for better Qdrant retrieval.
    Only the search query is enriched — stored Qdrant values remain unchanged.
    e.g. 'smartphones' → 'smartphone mobile phone cellular device, brands: iPhone, Samsung Galaxy'
    """
    from langchain_core.messages import SystemMessage, HumanMessage
    try:
        system = (
            "You generate search keywords for a vector database lookup over values stored in a database column.\n\n"
            "Output rules:\n"
            "- Comma-separated keywords only. No explanation, no quotes, no other punctuation.\n"
            "- Target 5 keywords. Hard maximum 7.\n"
            "- Each keyword must point to a DISTINCT concept. No near-duplicates or rewordings.\n"
            "- At most ONE generic synonym of the input. The rest must add new information.\n"
            "- Prefer specific/concrete terms over abstract/generic ones.\n\n"
            "Decision rule:\n"
            "- SPECIFIC input (proper noun, model number, exact name): output unchanged, optionally 1 variant.\n"
            "- CATEGORY/GENERIC input: output 4-6 specific sub-types or concrete instances.\n"
            "- If unsure, lean toward fewer keywords."
        )
        human = f"Input: {entity}"
        override = {"provider": provider, "model": model_name} if provider or model_name else None
        conf = operation_config("sql_agent.entity_expansion", override)
        conf["max_tokens"] = min(conf["max_tokens"], 80)
        llm = build_chat_model(conf, api_key=api_key)
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=human)])
        raw = response_text(resp)
        if not raw:
            return entity
        expanded = _dedup_expansion_keywords(raw)
        if not expanded:
            return entity
        logger.info("[HC] query_expansion | %s.%s | %r → %r", table_name, column_name, entity, expanded)
        return expanded
    except ModelConfigurationError:
        raise
    except Exception as e:
        logger.warning(
            "[HC] query_expansion failed | %s.%s | term=%r | err=%s — using original",
            table_name, column_name, entity, e,
        )
        return entity


async def _refine_candidates_with_llm(
    query: str,
    entities: List[str],
    table_name: str,
    column_name: str,
    candidates: List[str],
    api_key: Optional[str],
    provider: str = None,
    model_name: str = None,
) -> List[str]:
    """Step 5: LLM validates Qdrant candidates against the original user query.
    Filters out irrelevant matches (e.g. 'Apple Watch', 'Smart Home Speaker' for a smartphones query).
    Falls back to returning all candidates on any error.
    """
    from langchain_core.messages import SystemMessage, HumanMessage
    import json as _json

    if not candidates:
        return candidates

    try:
        system = (
            "You are a database filter validator.\n"
            "Given a user query and database values retrieved by vector search, "
            "return ONLY the values that are genuinely relevant to what the user is filtering for.\n\n"
            "Rules:\n"
            "- Keep values that match the category, type, brand, or specific item the user mentioned\n"
            "- Remove values that belong to a different product category or are clearly unrelated\n"
            "- When in doubt, keep the value\n"
            "- Output ONLY a JSON array, e.g.: [\"value1\", \"value2\"]\n"
            "  No explanation, no markdown fences — just the JSON array."
        )
        entities_str = ", ".join(f'"{e}"' for e in entities)
        candidates_str = "\n".join(f"- {c}" for c in candidates)
        human = (
            f"User query: {query}\n"
            f"Search term(s): {entities_str}\n"
            f"Column: {table_name}.{column_name}\n\n"
            f"Candidates from vector search:\n{candidates_str}\n\n"
            "Which candidates are relevant? Return as a JSON array."
        )

        override = {"provider": provider, "model": model_name} if provider or model_name else None
        conf = operation_config("sql_agent.entity_refinement", override)
        llm = build_chat_model(conf, api_key=api_key)
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=human)])
        content = response_text(resp)

        # Strip markdown fences if the model wraps output
        if "```" in content:
            content = re.sub(r"```(?:json)?\s*", "", content).strip("`").strip()

        kept = _json.loads(content)
        if not isinstance(kept, list):
            raise ValueError(f"Expected JSON list, got {type(kept)}")

        # Validate that returned values actually exist in candidates (case-insensitive)
        cand_lower_map = {c.lower(): c for c in candidates}
        validated: List[str] = []
        for k in kept:
            k_str = str(k).strip()
            canonical = cand_lower_map.get(k_str.lower())
            if canonical and canonical not in validated:
                validated.append(canonical)

        if not validated:
            # LLM returned empty or hallucinated values — safe fallback: keep all
            logger.warning(
                "[HC] refinement returned no valid matches | %s.%s | kept=%r | falling back to all",
                table_name, column_name, kept,
            )
            return candidates

        removed = [c for c in candidates if c not in validated]
        if removed:
            logger.info(
                "[HC] refinement | %s.%s | query=%r | removed=%r | kept=%r",
                table_name, column_name, query[:100], removed, validated,
            )
        else:
            logger.info(
                "[HC] refinement | %s.%s | all %d candidates passed validation",
                table_name, column_name, len(validated),
            )
        return validated

    except ModelConfigurationError:
        raise
    except Exception as e:
        logger.warning(
            "[HC] refinement failed | %s.%s | err=%s — keeping all %d candidates",
            table_name, column_name, e, len(candidates),
        )
        return candidates


@traceable(run_type="llm", name="hc_batch_expand_entities")
async def _batch_expand_entities(
    entity_pairs: List[Tuple[int, str]],
    filtered_columns: List[Dict[str, Any]],
    api_key: Optional[str],
    provider: str = None,
    model_name: str = None,
) -> List[str]:
    """Expand ALL entity terms in ONE LLM call (instead of N separate calls).
    Returns expanded texts in the same order as entity_pairs.
    Falls back to original terms on any error.
    """
    from langchain_core.messages import SystemMessage, HumanMessage

    if not entity_pairs:
        return []

    system = (
        "You enrich a user search term into a single dense sentence optimised for "
        "vector-search embedding over a product/entity database column.\n\n"
        "Output rules:\n"
        "- Output ONE sentence only per input. No bullet points, no numbered lists.\n"
        "- The sentence must weave in 6-10 concrete related terms naturally.\n"
        "- SPECIFIC input (proper noun, model number, exact name): return it UNCHANGED.\n"
        "- CATEGORY/GENERIC input: write a sentence like:\n"
        "  'fitness equipment such as dumbbells yoga mats gym gloves jump ropes "
        "resistance bands treadmills and cycling helmets'\n"
        "- Do NOT use commas to separate concepts — weave them into the sentence.\n"
        "- The output will be embedded directly; optimise for semantic proximity "
        "to individual stored values in that category.\n\n"
        "Examples:\n"
        "Input: fitness equipment\n"
        "Output: fitness equipment such as dumbbells yoga mats gym gloves jump ropes "
        "resistance bands treadmills and cycling helmets\n\n"
        "Input: smartphones\n"
        "Output: smartphones such as iPhone Samsung Galaxy Pixel Android phone and "
        "mobile devices\n\n"
        "Input: iPhone 15\n"
        "Output: iPhone 15\n\n"
        "Input: legal documents\n"
        "Output: legal documents such as contracts agreements affidavits leases "
        "wills and court orders\n\n"
        "Input: Sarah Johnson\n"
        "Output: Sarah Johnson\n\n"
        "For EACH numbered input below, return one enriched sentence in the SAME ORDER."
    )
    lines = [f"{i}. Input: {entity}" for i, (_, entity) in enumerate(entity_pairs, start=1)]
    human = "\n".join(lines)

    # Scale max_tokens with entity count so structured JSON is never truncated
    _max_tokens = max(80, len(entity_pairs) * 80)

    try:
        provider_lower = (provider or "openai").lower()
        llm = _build_llm_with_structured_output(
            provider_lower, model_name, 0.0, api_key, BatchExpansionResult,
            max_tokens=_max_tokens,
        )
        result = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=human)])

        if isinstance(result, BatchExpansionResult):
            batch = result
        elif isinstance(result, dict):
            batch = BatchExpansionResult(**result)
        else:
            batch = BatchExpansionResult.model_validate(result)

        rows = batch.expansions or []
        expanded_texts: List[str] = []
        for i, (col_idx, original_entity) in enumerate(entity_pairs):
            col_info = filtered_columns[col_idx]
            if i < len(rows):
                expanded = (rows[i].expanded_keywords or "").strip() or original_entity
            else:
                expanded = original_entity
            logger.info(
                "[HC] batch_expansion | %s.%s | %r → %r",
                col_info["table_name"], col_info["column_name"], original_entity, expanded,
            )
            expanded_texts.append(expanded)

        logger.info("[HC] batch_expand_entities | %d entities expanded in 1 LLM call", len(entity_pairs))
        return expanded_texts

    except ModelConfigurationError:
        raise
    except Exception as e:
        logger.warning("[HC] batch_expand_entities failed | err=%s — using original terms", e)
        return [entity for _, entity in entity_pairs]


@traceable(run_type="llm", name="hc_batch_refine_candidates")
async def _batch_refine_candidates(
    query: str,
    cols_to_refine: List[int],
    filtered_columns: List[Dict[str, Any]],
    extracted_by_col: Dict[int, List[str]],
    col_all_candidates: Dict[int, List[str]],
    api_key: Optional[str],
    provider: str = None,
    model_name: str = None,
) -> Dict[int, List[str]]:
    """Validate Qdrant candidates for ALL columns in ONE LLM call (instead of M separate calls).
    Returns {col_idx: filtered_candidates}. Falls back to all candidates on any error.
    """
    from langchain_core.messages import SystemMessage, HumanMessage

    if not cols_to_refine:
        return {}

    lines = []
    for i, col_idx in enumerate(cols_to_refine, start=1):
        col_info = filtered_columns[col_idx]
        entities = extracted_by_col.get(col_idx, [])
        candidates = col_all_candidates.get(col_idx, [])
        entities_str = ", ".join(f'"{e}"' for e in entities)
        cand_lines = "\n    ".join(f"- {c}" for c in candidates)
        lines.append(
            f"{i}. Column: {col_info['table_name']}.{col_info['column_name']}\n"
            f"   Search term(s): {entities_str}\n"
            f"   Candidates:\n    {cand_lines}"
        )

    system = (
        "You filter vector-search candidates before they are turned into SQL literals.\n"
        "The candidates were retrieved by hybrid semantic + keyword search, which sometimes returns "
        "items from a different category or family than the one the user asked about. Your job is to "
        "keep only the values that genuinely belong to the category, type, or entity the user is "
        "filtering for, and remove the cross-category false positives.\n\n"
        "Per column:\n"
        "1. Identify the category, type, or specific entity the user is filtering for.\n"
        "2. KEEP candidates that genuinely belong to that category — including loosely related or "
        "borderline items that still fit the same purpose or domain.\n"
        "3. REMOVE candidates that are clearly in a different category, family, or domain. These are "
        "vector-similarity false positives — they share embedding space with the query but do not "
        "belong to what the user asked for.\n"
        "4. For a SPECIFIC NAMED entity, keep only that entity and its obvious aliases or variants.\n"
        "5. When a candidate is GENUINELY AMBIGUOUS (a plausible case can be made it belongs to the "
        "asked category), keep it. 'Genuinely ambiguous' is not the same as 'semantically close'.\n\n"
        "Output rules:\n"
        "- Return one row per column in the SAME ORDER as the numbered list.\n"
        "- Each string in `relevant_values` must appear verbatim in that column's Candidates list.\n"
        "- `relevant_values` may be empty if every candidate is clearly off-topic."
    )
    human = (
        f"User query: {query}\n\n"
        f"For each of the {len(cols_to_refine)} column(s) below, return only the candidates that "
        f"genuinely belong to the category or entity the user asked about. Off-domain candidates must "
        f"be removed; on-domain candidates (even loosely related) must be kept.\n\n"
        + "\n\n".join(lines)
        + "\n\nReturn one result row per column, same order."
    )

    try:
        provider_lower = (provider or "openai").lower()
        llm = _build_llm_with_structured_output(
            provider_lower, model_name, 0.0, api_key, BatchRefinementResult
        )
        result = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=human)])

        if isinstance(result, BatchRefinementResult):
            batch = result
        elif isinstance(result, dict):
            batch = BatchRefinementResult(**result)
        else:
            batch = BatchRefinementResult.model_validate(result)

        rows = batch.results or []
        refined_by_col: Dict[int, List[str]] = {}
        for i, col_idx in enumerate(cols_to_refine):
            col_info = filtered_columns[col_idx]
            candidates = col_all_candidates.get(col_idx, [])
            if i < len(rows):
                kept = rows[i].relevant_values or []
                cand_lower_map = {c.lower(): c for c in candidates}
                validated: List[str] = []
                for k in kept:
                    canonical = cand_lower_map.get(str(k).strip().lower())
                    if canonical and canonical not in validated:
                        validated.append(canonical)
                if not validated:
                    logger.warning(
                        "[HC] batch_refinement no valid matches | %s.%s — keeping all",
                        col_info["table_name"], col_info["column_name"],
                    )
                    validated = candidates
                removed = [c for c in candidates if c not in validated]
                if removed:
                    logger.info(
                        "[HC] batch_refinement | %s.%s | removed=%r | kept=%r",
                        col_info["table_name"], col_info["column_name"], removed, validated,
                    )
                else:
                    logger.info(
                        "[HC] batch_refinement | %s.%s | all %d candidates passed",
                        col_info["table_name"], col_info["column_name"], len(validated),
                    )
                refined_by_col[col_idx] = validated
            else:
                logger.warning(
                    "[HC] batch_refinement missing row for %s.%s — keeping all",
                    col_info["table_name"], col_info["column_name"],
                )
                refined_by_col[col_idx] = candidates

        logger.info("[HC] batch_refine_candidates | %d columns refined in 1 LLM call", len(cols_to_refine))
        return refined_by_col

    except ModelConfigurationError:
        raise
    except Exception as e:
        logger.warning("[HC] batch_refine_candidates failed | err=%s — keeping all candidates", e)
        return {col_idx: col_all_candidates.get(col_idx, []) for col_idx in cols_to_refine}


@traceable(run_type="retriever", name="hc_entity_retriever")
async def entity_retriever(
    query: str,
    table: str,
    column: str,
    *,
    runtime_db: Optional[Dict[str, Any]] = None,
    owner_id: Optional[str] = None,
    settings: Optional[HybridEntityResolverSettings] = None,
    original_term: Optional[str] = None,
    db_id: Optional[str] = None,
) -> List[str]:
    """Retrieve high-cardinality column-value candidates via Qdrant native hybrid
    search (dense semantic + sparse BM25 + RRF fusion).

    Precision/recall split:
      - ``query`` is the LLM-expanded text → fed to sparse BM25 (extra keywords
        improve recall over indexed values).
      - ``original_term`` is the user's short focused phrase → fed to the dense
        embedding (a tight, undiluted vector improves semantic precision).
      Sending the expanded text to dense diffuses the embedding across many
      concepts and pulls in cross-category matches.

    The ``runtime_db`` parameter is kept on the signature for backward
    compatibility with existing callers but is no longer consumed.
    """
    cfg = settings or HybridEntityResolverSettings.load()
    try:
        store = await get_cardinality_store()
        values = await store.retrieve_similar_values(
            query, table, column,
            limit=cfg.top_n,
            dense_query=original_term,
            db_id=db_id,
        )
        logger.info(
            "[HC] entity_retriever mode=QDRANT_HYBRID | %s.%s | sparse_q=%r | dense_q=%r | n=%d | top=%s",
            table, column, query, original_term, len(values), values[:5],
        )
        return values
    except ModelConfigurationError:
        raise
    except Exception as e:
        logger.error(
            "[HC] entity_retriever error | %s.%s | term=%r | err=%s",
            table, column, query, e,
        )
        return []


async def _build_low_cardinality_block(
    agent_id: str, selected_tables: List[str], query: str = "", db_id: Optional[str] = None
) -> str:
    """
    Fetch LOW_CARDINALITY_CATEGORICAL columns from hc_column_profiles and format
    them as a prompt block so the LLM uses exact valid values in WHERE clauses.

    When `query` is provided, only columns whose name is referenced in the query
    (substring match) or whose values appear in the query are included. This avoids
    bloating the prompt with irrelevant categorical columns.
    """
    try:
        from knowledge.db_utils.hc_profile_db_utils import get_low_cardinality_columns
        low_card = await get_low_cardinality_columns(agent_id, db_id=db_id)
        if not low_card:
            return ""
        query_lower = query.lower() if query else ""
        lines = []
        for table_name, cols in low_card.items():
            if selected_tables and table_name not in selected_tables:
                continue
            for col_name, values in cols.items():
                if not values:
                    continue
                if query_lower:
                    # Include column if its name (or any word of it) appears in the query,
                    # OR if any of its values appears verbatim in the query.
                    col_words = [w for w in re.split(r"[_\s]+", col_name.lower()) if len(w) > 2]
                    col_referenced = any(w in query_lower for w in col_words)
                    any_value_in_query = any(
                        str(v).lower() in query_lower for v in values if v is not None
                    )
                    if not col_referenced and not any_value_in_query:
                        continue
                quoted = ", ".join(f"'{v}'" for v in values if v is not None)
                lines.append(f"- {table_name}.{col_name}: {quoted}")
        if not lines:
            return ""
        return (
            "=== CATEGORICAL COLUMN VALID VALUES ===\n"
            "When filtering by these columns, use ONLY the exact values listed (case-sensitive):\n"
            + "\n".join(lines)
        )
    except Exception as e:
        logger.warning(f"[HC] _build_low_cardinality_block failed (non-blocking): {e}")
        return ""


@traceable(run_type="chain", name="hc_get_suffix_string")
async def get_suffix_string(
    user_id,
    agent_id,
    db_details,
    query,
    selected_tables,
    owner_id: Optional[str] = None,
    db_id: Optional[str] = None,
):
    """
    Build suffix for SQL generation: human-readable hints + SQL_FILTER_LITERALS for exact predicates.
    Flow: load HC config → filter by selected tables → one batched LLM entity extraction → Qdrant per entity → suffix text.
    """
    # Resolve to the agent's primary DB when no explicit db_id is provided so
    # all downstream profile reads and Qdrant retrievals stay db-scoped.
    if db_id is None:
        try:
            from agent.db_utils.database_db_utils import get_primary_db_id
            db_id = await get_primary_db_id(agent_id)
        except Exception:
            logger.warning("[HC] Could not resolve primary db_id for agent_id=%s", agent_id)

    logger.info(f"[HC] get_suffix_string | agent_id={agent_id} | db_id={db_id} | query={query} | tables={selected_tables}")
    logger.info(
        "[WF] step=sql_gen.hc_suffix.resolve.start | agent_id=%s | owner_id=%s",
        agent_id,
        owner_id,
    )

    # Fetch LOW_CARDINALITY_CATEGORICAL block independently — always appended regardless of HC path
    low_card_block = await _build_low_cardinality_block(agent_id, selected_tables, query, db_id=db_id)

    hc_data = await get_hc_text_search_columns(agent_id, db_id=db_id)
    logger.info(f"[HC] get_hc_text_search_columns result: {hc_data}")

    if not hc_data:
        logger.info("[HC] No HC text search columns found in DB — returning low_card_block only")
        return low_card_block

    # Fetch sample values to give the entity-extraction LLM column context.
    # e.g. "column notes — example values: 'Order shipped via UPS', 'Refund requested'"
    # makes it obvious that "statuswise" is not a filter value for notes.
    hc_samples = await get_hc_text_search_samples(agent_id, db_id=db_id)

    high_cardinality_columns: List[Dict[str, Any]] = []
    for table_name, columns in hc_data.items():
        for col in columns:
            samples = (hc_samples.get(table_name) or {}).get(col) or []
            if samples:
                sample_str = ", ".join(f'"{v}"' for v in samples[:5] if v is not None)
                desc = f"example values: {sample_str}"
            else:
                desc = ""
            high_cardinality_columns.append({
                "table_name": table_name,
                "column_name": col,
                "column_description": desc,
            })

    filtered_columns = [
        col for col in high_cardinality_columns
        if col["table_name"] in selected_tables
    ]
    if not filtered_columns:
        logger.info("[HC] No matching HC columns for selected tables — returning empty")
        return low_card_block

    entity_map = await batch_extract_entities_for_hc_columns(query, filtered_columns, owner_id)
    logger.info(f"[HC] batch entity_map: {entity_map}")

    # Drop entities that are just the table name itself — the user wants all rows, not a filtered subset.
    # e.g. query "show me list of products" → entity "products" for products.name → should be ignored.
    for col_info in filtered_columns:
        key = f"{col_info['table_name']}.{col_info['column_name']}"
        if key not in entity_map:
            continue
        table_lower = col_info["table_name"].lower()
        table_variants = {table_lower, table_lower.rstrip("s"), table_lower + "s"}
        before = entity_map[key]
        entity_map[key] = [e for e in before if e.strip().lower() not in table_variants]
        if len(entity_map[key]) < len(before):
            logger.info(
                "[HC] Dropped table-name-only entities for %s: %r → %r",
                key, before, entity_map[key],
            )

    runtime_db: Dict[str, Any] = {}
    if isinstance(db_details, dict):
        runtime_db = db_details.get("db_details") or {}

    _hybrid_cfg = HybridEntityResolverSettings.load()
    logger.info(
        "[HC] suffix_string resolution context | USE_HYBRID_ENTITY_RESOLVER effective=%s | "
        "runtime_db_engine=%s | will_use_hybrid_when_retrieving=%s",
        _hybrid_cfg.enabled,
        runtime_db.get("db_engine") if runtime_db else None,
        _hybrid_cfg.enabled
        and bool(runtime_db)
        and (runtime_db.get("db_engine") or "").lower() in ("postgresql", "mysql"),
    )

    # Resolve embedding API key once and store in context var so it never appears
    # as a named parameter on @traceable functions (and is invisible in LangSmith).
    embedding_key: Optional[str] = None
    if owner_id:
        try:
            embedding_model = load_profile()["embeddings"]["high_cardinality"]["model"]
            embedding_key = await get_llm_api_key(owner_id, embedding_model, "openai")
        except ModelConfigurationError:
            raise
        except Exception:
            logger.warning("[HC] Could not resolve embedding api key for owner_id=%s, using env fallback", owner_id)
    _ctx_token = _embedding_api_key_var.set(embedding_key)  # set before any retrieval

    narrative_parts: List[str] = []
    literal_lines: List[str] = []
    max_in = max(2, int(os.getenv("HC_MAX_IN_LITERALS", "25")))
    top_k_per_entity = max(1, int(os.getenv("HC_TOP_K_PER_ENTITY", "3")))

    # Collect all (col_idx, entity) pairs across columns
    entity_pairs: List[Tuple[int, str]] = []
    extracted_by_col: Dict[int, List[str]] = {}

    for col_idx, col_info in enumerate(filtered_columns):
        key = f"{col_info['table_name']}.{col_info['column_name']}"
        extracted = _expand_entity_alternatives(entity_map.get(key, []))
        extracted_by_col[col_idx] = extracted
        for entity in extracted:
            entity_pairs.append((col_idx, entity))

    if not entity_pairs:
        logger.info("[HC] No entities extracted for any HC column — returning empty")
        return low_card_block

    # Step 3 — independently configured batch expansion.
    _ec = operation_config("sql_agent.entity_expansion")
    _expand_provider, _expand_model = _ec["provider"], _ec["model"]
    _expand_key = await get_llm_api_key(owner_id, _expand_model, _expand_provider) if owner_id else None

    logger.info("[HC] Running batch query expansion for %d entities in 1 LLM call", len(entity_pairs))
    expanded_texts: List[str] = await _batch_expand_entities(
        entity_pairs, filtered_columns, _expand_key, _expand_provider, _expand_model
    )

    # Build parallel retrieval tasks using expanded search text
    # original_entity → DB ILIKE seed; search_text (enriched sentence) → Qdrant embedding
    retrieval_tasks = []
    task_mapping: List[Tuple[int, str]] = []
    for (col_idx, original_entity), search_text in zip(entity_pairs, expanded_texts):
        col_info = filtered_columns[col_idx]
        retrieval_tasks.append(entity_retriever(
            search_text,
            col_info["table_name"],
            col_info["column_name"],
            runtime_db=runtime_db,
            owner_id=owner_id,
            settings=_hybrid_cfg,
            original_term=original_entity,
            db_id=db_id,
        ))
        task_mapping.append((col_idx, original_entity))

    # Run all retrievals in parallel (embedding key flows via context var)
    logger.info(f"[HC] Running {len(retrieval_tasks)} retrievals in parallel")
    retrieval_results = await asyncio.gather(*retrieval_tasks)
    _embedding_api_key_var.reset(_ctx_token)  # clear after retrievals

    # Merge per-entity results back into per-column candidate lists (deduped)
    col_all_candidates: Dict[int, List[str]] = {i: [] for i in range(len(filtered_columns))}
    col_seen: Dict[int, set] = {i: set() for i in range(len(filtered_columns))}
    for values, (col_idx, _orig) in zip(retrieval_results, task_mapping):
        for v in values:
            vv = str(v).strip()
            if vv and vv.lower() not in col_seen[col_idx]:
                col_seen[col_idx].add(vv.lower())
                col_all_candidates[col_idx].append(vv)

    cols_to_refine = [
        col_idx for col_idx in range(len(filtered_columns))
        if col_all_candidates[col_idx] and extracted_by_col.get(col_idx)
    ]
    logger.info("[HC] Running batch refinement for %d columns in 1 LLM call (Step 5)", len(cols_to_refine))
    _refine = operation_config("sql_agent.entity_refinement")
    _refine_key = await get_llm_api_key(owner_id, _refine["model"], _refine["provider"]) if owner_id else None
    refined_by_col: Dict[int, List[str]] = await _batch_refine_candidates(
        query,
        cols_to_refine,
        filtered_columns,
        extracted_by_col,
        col_all_candidates,
        _refine_key,
        _refine["provider"],
        _refine["model"],
    )

    # Build narrative and literals from LLM-validated candidates
    for col_idx, col_info in enumerate(filtered_columns):
        table_name = col_info["table_name"]
        column_name = col_info["column_name"]

        if not extracted_by_col.get(col_idx):
            continue

        canonicals = refined_by_col.get(col_idx, [])[:max_in]
        if not canonicals:
            continue

        narrative_parts.append(
            f"Some example values for {column_name} in {table_name} are: {', '.join(canonicals[:15])}"
        )
        pred = _format_hc_literal_predicate(table_name, column_name, canonicals)
        if pred:
            literal_lines.append(pred)

    if not narrative_parts:
        logger.info("[HC] No suffix content after retrieval — returning empty")
        return low_card_block

    narrative = " ".join(narrative_parts)
    literals_block = (
        "SQL_FILTER_LITERALS (use = or IN below exactly; do not replace with ILIKE/LIKE on user paraphrase):\n"
        + "\n".join(literal_lines)
    )
    final = f"{narrative}\n\n{literals_block}"
    if low_card_block:
        final = final + "\n\n" + low_card_block
    logger.info(f"[HC] Final suffix_string length={len(final)}")
    logger.info(
        "[WF] step=sql_gen.hc_suffix.resolve.end | agent_id=%s | literal_count=%d",
        agent_id,
        len(literal_lines),
    )
    return final
