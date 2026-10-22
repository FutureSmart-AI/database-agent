"""
Cross-DB merge node — the "combine at last" step.

Combines the per-DB result sets produced by `cross_db_fanout` into a single table,
in-application, using pandas — because separate databases cannot be joined in SQL. The
combine is driven by the `join_key`(s) that `db_router` declared in the plan — the router
owns the decision (it sees the real schema via routing hints); the merge never guesses a
relationship from raw columns:

  * every selected DB declared a join_key present in its result → pair rows on it (outer
    join). Keys may be named differently per DB (agent_id ↔ id); all are renamed to one
    canonical column.
  * NO DB declared a join_key → stack the results side-by-side with a `source_database`
    column (independent-facts questions: "how many X and how many Y?").
  * a join_key was declared but is MISSING from some result → fail loud (never guess or
    silently stack a question that was meant to join).

Provenance: every non-join column is prefixed with its database's name
(`chat_staging_db__agent_count`) so identical names can't collide and the final answer can
attribute values. A side that returned ONLY the join column gets a `<db>__present` flag so
anti-join questions ("which X are missing from Y?") stay answerable — unmatched rows carry
None there, and are sorted first so they survive the answer preview.

The merged frame is written back into `db_result` / `db_columns` in the exact shape
`sql_exec` produces, so check_pandas → final_answer run unchanged. Failures are explicit
(`sql_error`) — never a silently-wrong combination.
"""
import re
from typing import Dict, Any, List, Optional, Tuple

from langsmith import traceable

from agent.state import AgentState
from logger import logger
from otel_tracing import track_time


def _safe_prefix(name: Optional[str], fallback: str) -> str:
    """A short, column-safe provenance prefix from a db name (or db_id fallback)."""
    base = (name or fallback or "db").strip()
    base = re.sub(r"[^0-9A-Za-z]+", "_", base).strip("_").lower()
    return base or "db"


def _resolve_join_keys(
    frames: List[Tuple[str, "object"]],
    plan_key_by_id: Dict[str, str],
) -> Tuple[Optional[Dict[str, str]], Optional[str], str]:
    """Decide how to combine the results from the db_router's declared join_key(s).

    Returns (keys_by_db_id, canonical_output_name, mode):
      * mode="join"  — EVERY frame declares a join_key AND it exists in that frame's result
        columns. keys_by_db_id maps db_id → its actual key column (names may differ per DB,
        e.g. agent_id ↔ id); canonical_output_name is what they are all renamed to.
      * mode="stack" — NO frame declares a join_key. The router judged these independent facts
        ("how many X and how many Y?") → put the results side by side, do not pair rows.
      * mode="error" — a join_key WAS declared but is missing from some result set (model slip,
        or the sub-query didn't return it). The caller fails loud rather than guessing or
        silently stacking a question that was meant to join.

    There is NO data-driven fallback: the db_router owns the combine decision (it has the real
    schema via routing hints), so the merge never guesses a relationship from raw columns.
    """
    declared = {db_id: (plan_key_by_id.get(db_id) or "").strip() for db_id, _ in frames}
    if not any(declared.values()):
        return None, None, "stack"

    keys: Dict[str, str] = {}
    for db_id, df in frames:
        cols = {str(c).lower(): str(c) for c in df.columns}
        want = declared[db_id].lower()
        if not (want and want in cols):
            return None, None, "error"  # declared a join but a side can't supply the key
        keys[db_id] = cols[want]
    return keys, keys[frames[0][0]], "join"


@traceable(run_type="chain", name="node_cross_db_merge")
@track_time("Node: Cross-DB Merge")
async def node_cross_db_merge(state: AgentState) -> AgentState:
    """Combine the per-DB result sets (join on a detected common column, or stack)."""
    request_id = state.get("request_id")
    results: List[Dict[str, Any]] = state.get("cross_db_results") or []
    by_id = {d.get("db_id"): d for d in (state.get("selected_dbs") or [])}
    logger.info("[WF] step.start=cross_db_merge | request_id=%s | n_results=%d", request_id, len(results))

    # A required side denied a source read. Do not merge other sides into an
    # apparently complete answer or invoke another model to reinterpret failure.
    if any(r.get("access_policy_error") or r.get("access_denied_tables") for r in results):
        from agent.utils.table_access import deny_table_access
        return deny_table_access(state,
            policy_error=any(r.get("access_policy_error") for r in results),
            tables=sorted({t for r in results for t in (r.get("access_denied_tables") or [])}))

    unsupported = [r.get("answerability_error") for r in results if r.get("answerability_error")]
    if results and len(unsupported) == len(results):
        state.update(answerability_error=unsupported[0], sql_query="", sql_error=None,
                     db_result=[], db_columns=None)
        return state
    # Mixed required-source results retain the existing combine/error contract;
    # one unsupported source does not establish absence across every database.
    state["answerability_error"] = None

    # Combined SQL string for debug/observability regardless of outcome.
    state["sql_query"] = "\n\n".join(
        f"-- {r.get('db_id')}\n{r.get('sql_query') or '(no SQL generated)'}" for r in results
    )

    try:
        import pandas as pd
    except Exception as e:  # noqa: BLE001
        logger.error("[cross_db_merge] pandas unavailable: %s", e)
        state["sql_error"] = "Cross-database combining is unavailable (pandas not installed)."
        state["db_result"] = []
        state["db_columns"] = None
        return state

    # Surface any per-sub-query errors up front.
    for r in results:
        if r.get("error"):
            logger.warning("[cross_db_merge] db_id=%s sub-query errored: %s",
                           r.get("db_id"), str(r.get("error"))[:200])

    # Raw DataFrame per non-empty result (original column names for detection).
    frames: List[Tuple[str, "pd.DataFrame"]] = []
    for r in results:
        rows = r.get("rows") or []
        cols = [str(c) for c in (r.get("columns") or [])]
        if rows and cols:
            frames.append((r.get("db_id"), pd.DataFrame([list(row) for row in rows], columns=cols)))

    if len(frames) < 2:
        logger.warning("[WF] step.end=cross_db_merge | request_id=%s | insufficient data (frames=%d)",
                       request_id, len(frames))
        state["sql_error"] = (
            "Could not combine data across databases: not all databases returned usable results."
        )
        state["db_result"] = []
        state["db_columns"] = None
        return state

    # Combine per the db_router's declared join_key(s): join when all declared + present,
    # stack when none declared, fail loud when declared but missing (no guessing).
    plan_subs = (state.get("cross_db_plan") or {}).get("sub_questions") or []
    plan_key_by_id = {s.get("db_id"): (s.get("join_key") or "").strip() for s in plan_subs}
    keys_by_id, join_col, combine_mode = _resolve_join_keys(frames, plan_key_by_id)
    if combine_mode == "error":
        logger.warning(
            "[cross_db_merge] declared join_key missing from a result set | request_id=%s | declared=%s",
            request_id, plan_key_by_id,
        )
        state["sql_error"] = (
            "Could not combine data across databases: the column meant to link them was not "
            "returned by every database. Please rephrase the question."
        )
        state["db_result"] = []
        state["db_columns"] = None
        return state
    state["cross_db_combine"] = {
        "mode": combine_mode, "on": join_col, "key_source": ("router" if join_col else None),
    }

    try:
        if join_col:
            # ── JOIN mode: pair rows on the resolved key column (always outer — matched
            # rows are visible, unmatched rows are marked, so compare/missing/overlap
            # questions are all answerable from the same result). Each frame's own key column
            # (which may be named differently per DB) is renamed to the canonical `join_col`.
            prepared = []
            for db_id, df in frames:
                key = keys_by_id[db_id]
                prefix = _safe_prefix((by_id.get(db_id) or {}).get("db_name"), db_id)
                renamed = {c: (join_col if c == key else f"{prefix}__{c}") for c in df.columns}
                df = df.rename(columns=renamed)
                # A side that returned ONLY the key gets a presence flag — that flag IS the
                # answer to "which rows exist / are missing in this database".
                if list(df.columns) == [join_col]:
                    df = df.drop_duplicates(subset=[join_col])
                    df[f"{prefix}__present"] = True
                prepared.append(df)
            merged = prepared[0]
            for df in prepared[1:]:
                merged = merged.merge(df, on=join_col, how="outer")
            # Unmatched rows first so they survive the final-answer preview of large results.
            present_cols = [c for c in merged.columns if str(c).endswith("__present")]
            value_cols = [c for c in merged.columns if c != join_col]
            sort_cols = present_cols or value_cols
            if sort_cols:
                try:
                    merged = merged.sort_values(by=sort_cols[:2], na_position="first")
                except Exception:  # noqa: BLE001 — ordering is best-effort
                    pass
        else:
            # ── STACK mode: nothing to pair (independent facts) — put the results
            # side-by-side with a source_database column saying where each row came from.
            stacked = []
            for db_id, df in frames:
                df = df.copy()
                df.insert(0, "source_database", (by_id.get(db_id) or {}).get("db_name") or db_id)
                stacked.append(df)
            merged = pd.concat(stacked, ignore_index=True, sort=False)
    except Exception as e:  # noqa: BLE001
        logger.error("[cross_db_merge] combine failed: %s", e)
        state["sql_error"] = f"Cross-database combining failed: {e}"
        state["db_result"] = []
        state["db_columns"] = None
        return state

    # NaN (unmatched cells) is not valid JSON — convert to None before extracting rows.
    merged = merged.astype(object).where(merged.notna(), None)
    columns = [str(c) for c in merged.columns]
    rows = [tuple(rec) for rec in merged.itertuples(index=False, name=None)]

    state["db_columns"] = columns
    state["db_result"] = rows
    state["sql_error"] = None
    # Union of the real tables used, so final_answer's allowed-tables guard doesn't wrongly
    # refuse a valid cross-DB answer.
    tables_union: List[str] = []
    for r in results:
        for t in (r.get("selected_tables") or []):
            if t and t not in tables_union:
                tables_union.append(t)
    state["selected_tables"] = tables_union or [
        d.get("db_name") or d.get("db_id") for d in (state.get("selected_dbs") or [])
    ]

    logger.info(
        "[WF] step.end=cross_db_merge | request_id=%s | mode=%s | on=%s | key_source=%s | rows=%d | cols=%d",
        request_id, state["cross_db_combine"]["mode"], join_col,
        state["cross_db_combine"]["key_source"], len(rows), len(columns),
    )
    return state
