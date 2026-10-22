"""High-cardinality value retrieval using Qdrant NATIVE HYBRID SEARCH.

Hybrid = dense semantic embeddings (OpenAI) + sparse keyword embeddings (BM25
via fastembed), fused with Reciprocal Rank Fusion at the Qdrant server.

This replaces the previous "DB ILIKE + Qdrant dense" hybrid: sparse vectors
now cover the exact / partial-keyword job that the SQL ILIKE used to do,
without an extra DB round-trip.

Migration note: the collection schema below uses NAMED dense + sparse vectors.
The legacy collection used an unnamed dense vector. If the existing collection
still has the legacy schema, the initializer logs a clear warning — recreate it
(or use HC_QDRANT_COLLECTION_NAME to point at a fresh collection) and re-run
your indexing job to repopulate.
"""
import asyncio
import logging
import os
from contextvars import ContextVar
from typing import List, Dict, Any, Tuple, Optional

from langsmith import traceable
from agent.utils.qdrant_async_client import make_async_qdrant_client
from qdrant_client.http import models
from qdrant_client.http.models import (
    VectorParams, Distance,
    SparseVectorParams, SparseIndexParams, SparseVector,
    Filter, FieldCondition, MatchValue,
    Prefetch, FusionQuery, Fusion,
    PointStruct, NamedVector,
)
from langchain_openai import OpenAIEmbeddings
from agent.utils.model_profiles import load_profile, ModelConfigurationError
from agent.utils.embedding_config import verify_vector_size

# Carries the per-request embedding API key through async context so it never
# appears as a named parameter on @traceable functions (and thus never in LangSmith).
_embedding_api_key_var: ContextVar[Optional[str]] = ContextVar("hc_embedding_api_key", default=None)

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_URL = os.getenv("qdrant_url")
QDRANT_API_KEY = os.getenv("qdrant_api_key")

_EMBEDDING_BINDING = load_profile()["embeddings"]["high_cardinality"]
_EMBEDDING_MODEL = _EMBEDDING_BINDING["model"]
_DENSE_VECTOR_SIZE = _EMBEDDING_BINDING["dimensions"]
_SPARSE_MODEL = os.getenv("HC_SPARSE_MODEL", "Qdrant/bm25")
_COLLECTION_NAME = os.getenv("HC_QDRANT_COLLECTION_NAME", "high-cardinality-values")

# Per-batch upsert retry: a transient Qdrant disconnect should retry just the
# failed batch (upserts are idempotent — deterministic uuid5 point IDs), not
# abort the whole indexing run and roll back already-indexed columns.
_UPSERT_MAX_ATTEMPTS = int(os.getenv("HC_UPSERT_MAX_ATTEMPTS", "3"))
_UPSERT_RETRY_BASE_DELAY = float(os.getenv("HC_UPSERT_RETRY_BASE_DELAY", "1.0"))

# Minimum cosine similarity for dense matches — below this, the result is treated
# as a semantic false-positive and dropped before RRF fusion. Tune higher for
# stricter retrieval (fewer cross-domain leaks), lower for broader recall.
# Sparse BM25 is naturally self-filtering: zero keyword overlap → no result.
#
# Note: text-embedding-3-large produces noisier short-text embeddings — distant
# items can score in the 0.30–0.45 range, so a threshold of ~0.5 is needed to
# actually filter cross-category noise (books, electronics, etc. for a fitness
# query). Lower → more recall; higher → more precision.
_DENSE_SCORE_THRESHOLD = float(os.getenv("HC_DENSE_SCORE_THRESHOLD", "0.5"))

# Named vector keys — must match across initialize / store / retrieve
_DENSE_NAME = "dense"
_SPARSE_NAME = "sparse"


# ──────────────────────────────────────────────────────────────────────────────
# Sparse encoder (BM25 via fastembed) — lazy singleton
# ──────────────────────────────────────────────────────────────────────────────
_sparse_encoder = None


def _get_sparse_encoder():
    """Lazy-load BM25 sparse encoder. Requires `pip install fastembed`."""
    global _sparse_encoder
    if _sparse_encoder is None:
        try:
            from fastembed import SparseTextEmbedding
        except ImportError as e:
            raise RuntimeError(
                "HC hybrid search needs fastembed for sparse BM25 encoding. "
                "Install with: pip install fastembed"
            ) from e
        _sparse_encoder = SparseTextEmbedding(model_name=_SPARSE_MODEL)
        logger.info(f"[HC] Loaded sparse encoder: {_SPARSE_MODEL}")
    return _sparse_encoder


def _encode_sparse_one(text: str) -> SparseVector:
    """Encode one query → Qdrant SparseVector (BM25 indices + values)."""
    enc = _get_sparse_encoder()
    r = next(enc.embed([text]))
    return SparseVector(indices=r.indices.tolist(), values=r.values.tolist())


def _encode_sparse_batch(texts: List[str]) -> List[SparseVector]:
    """Encode a batch of values → list of Qdrant SparseVectors (used at index time)."""
    enc = _get_sparse_encoder()
    return [
        SparseVector(indices=r.indices.tolist(), values=r.values.tolist())
        for r in enc.embed(texts)
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Qdrant store with hybrid (dense + sparse + RRF) retrieval
# ──────────────────────────────────────────────────────────────────────────────
class QdrantCardinalityStore:
    def __init__(self):
        # qdrant_api_key is optional: an internal/self-hosted Qdrant runs without auth
        # (mirrors qdrant_few_shot_store_utils.py). Requiring it here made every HC-profile
        # DELETE fail with a 500 against the self-hosted instances.
        if not QDRANT_URL:
            raise ValueError("Missing required environment variable: qdrant_url")
        self._embedding_model = _EMBEDDING_MODEL
        self.collection_name = _COLLECTION_NAME
        self.client = make_async_qdrant_client(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY or None,
            timeout=int(os.getenv("HC_QDRANT_TIMEOUT", "60")),
        )

    def _make_embedding_fn(self, api_key: Optional[str] = None) -> OpenAIEmbeddings:
        """Build a dense embedder. Priority: explicit arg → context var → env var."""
        key = api_key or _embedding_api_key_var.get() or OPENAI_API_KEY
        if not key:
            raise ModelConfigurationError("Missing OPENAI_API_KEY for high-cardinality embeddings")
        return OpenAIEmbeddings(model=self._embedding_model, api_key=key)

    async def _create_hybrid_collection(self) -> None:
        """Create the collection with named dense + named sparse vectors."""
        logger.info(f"[HC] Creating hybrid collection: {self.collection_name}")
        await self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                _DENSE_NAME: VectorParams(size=_DENSE_VECTOR_SIZE, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                _SPARSE_NAME: SparseVectorParams(index=SparseIndexParams()),
            },
        )
        logger.info(f"[HC] Hybrid collection ready: {self.collection_name}")

    async def _ensure_collection(self) -> None:
        """Create only missing stores; never delete, resize or rebuild existing vectors."""
        collections = await self.client.get_collections()
        if self.collection_name not in [c.name for c in collections.collections]:
            await self._create_hybrid_collection()
            return
        info = await self.client.get_collection(self.collection_name)
        params = info.config.params
        dense = getattr(params, "vectors", None)
        sparse = getattr(params, "sparse_vectors", None) or {}
        if not isinstance(dense, dict) or _DENSE_NAME not in dense or _SPARSE_NAME not in sparse:
            raise ModelConfigurationError(
                "Existing HC collection has an incompatible vector schema. Preserve it and "
                "configure a separately provisioned compatible collection; no rebuild is performed.")
        verify_vector_size(getattr(dense[_DENSE_NAME], "size", None), _DENSE_VECTOR_SIZE, self.collection_name)

    async def initialize(self):
        await self._ensure_collection()

    async def store_values(
        self,
        values: List[str],
        metadata: Dict[str, Any],
        api_key: Optional[str] = None,
    ) -> bool:
        """Index a batch of column values — computes BOTH dense and sparse vectors.

        Self-heals: if the collection was dropped (e.g. via Qdrant dashboard) the
        store will recreate it with the hybrid schema before upserting.
        """
        try:
            # Self-heal: recreate collection if it was dropped at runtime
            await self._ensure_collection()

            import uuid
            logger.info(
                f"[HC] Indexing {len(values)} values | table={metadata['table']} column={metadata['column']}"
            )

            emb_fn = self._make_embedding_fn(api_key)
            dense_vectors = await emb_fn.aembed_documents(values)
            # BM25 encoding is CPU-bound and sync — for large batches, callers
            # can wrap this method in asyncio.to_thread. Keeping it inline here
            # keeps the storage path simple and matches typical batch sizes.
            sparse_vectors = _encode_sparse_batch(values)

            points: List[PointStruct] = []
            for value, dense_vec, sparse_vec in zip(values, dense_vectors, sparse_vectors):
                _db_id = metadata.get("db_id")
                _id_seed = (
                    f"{_db_id}_{metadata['table']}_{metadata['column']}_{value}"
                    if _db_id is not None
                    else f"{metadata['table']}_{metadata['column']}_{value}"
                )
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, _id_seed))
                payload = {
                    "value": value,
                    "table": metadata["table"],
                    "column": metadata["column"],
                }
                if metadata.get("db_id") is not None:
                    payload["db_id"] = metadata["db_id"]
                points.append(PointStruct(
                    id=point_id,
                    vector={
                        _DENSE_NAME: dense_vec,
                        _SPARSE_NAME: sparse_vec,
                    },
                    payload=payload,
                ))

            batch_size = 50
            for i in range(0, len(points), batch_size):
                batch = points[i : i + batch_size]
                for attempt in range(1, _UPSERT_MAX_ATTEMPTS + 1):
                    try:
                        await self.client.upsert(
                            collection_name=self.collection_name,
                            points=batch,
                        )
                        break
                    except Exception as e:
                        if attempt == _UPSERT_MAX_ATTEMPTS:
                            raise
                        delay = _UPSERT_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning(
                            f"[HC] Upsert batch {i // batch_size + 1} for "
                            f"{metadata['table']}.{metadata['column']} failed "
                            f"(attempt {attempt}/{_UPSERT_MAX_ATTEMPTS}): "
                            f"{type(e).__name__}: {e}. Retrying in {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
            logger.info(
                f"[HC] Upserted {len(points)} hybrid points for {metadata['table']}.{metadata['column']}"
            )
            return True
        except Exception as e:
            import traceback
            logger.error(f"[HC] Error storing hybrid values: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            raise

    async def delete_values_for_table_column(
        self, table: str, column: str, db_id: Optional[str] = None
    ) -> bool:
        """Delete all points for (table, column) — payload filter, optionally scoped to db_id."""
        try:
            must = [
                FieldCondition(key="table", match=MatchValue(value=table)),
                FieldCondition(key="column", match=MatchValue(value=column)),
            ]
            if db_id is not None:
                must.append(FieldCondition(key="db_id", match=MatchValue(value=db_id)))
            await self.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(must=must),
            )
            logger.info(f"[HC] Deleted points for {table}.{column} (db_id={db_id})")
            return True
        except Exception as e:
            logger.error(f"[HC] Error deleting points for {table}.{column}: {e}")
            raise

    async def _hybrid_query(
        self,
        query: str,
        table: str,
        column: str,
        *,
        limit: int,
        dense_limit: Optional[int] = None,
        sparse_limit: Optional[int] = None,
        dense_query: Optional[str] = None,
        db_id: Optional[str] = None,
    ):
        """Run Qdrant native hybrid: dense + sparse → RRF fusion. Returns raw points.

        ``query`` is what we send to BOTH paths by default. For better precision,
        callers should pass the *original* user term as ``dense_query`` and let
        ``query`` be the LLM-expanded version — dense benefits from a focused
        short term (tighter embedding cluster), sparse benefits from extra
        keywords for BM25 recall.
        """
        # Dense embedding — prefer the focused original term if provided,
        # else fall back to whatever was passed as `query`.
        await self._ensure_collection()
        dense_text = dense_query if dense_query else query
        emb_fn = self._make_embedding_fn()
        dense_vec = await emb_fn.aembed_query(dense_text)

        # Sparse embedding (BM25 keyword/exact-match) — gets the broader text
        # so it has more keywords to match across the indexed product names.
        sparse_vec = _encode_sparse_one(query)

        _dense_limit = dense_limit or max(limit * 4, 40)
        _sparse_limit = sparse_limit or max(limit * 4, 40)

        _must = [
            FieldCondition(key="table", match=MatchValue(value=table)),
            FieldCondition(key="column", match=MatchValue(value=column)),
        ]
        if db_id is not None:
            _must.append(FieldCondition(key="db_id", match=MatchValue(value=db_id)))
        payload_filter = Filter(must=_must)

        response = await self.client.query_points(
            collection_name=self.collection_name,
            prefetch=[
                Prefetch(
                    query=dense_vec,
                    using=_DENSE_NAME,
                    limit=_dense_limit,
                    filter=payload_filter,
                    # Drop weak semantic matches server-side BEFORE RRF fusion.
                    # Stops cross-domain noise (e.g. headphones / books pulled in
                    # for "fitness equipment") from polluting the fused result.
                    score_threshold=_DENSE_SCORE_THRESHOLD,
                ),
                Prefetch(
                    query=sparse_vec,
                    using=_SPARSE_NAME,
                    limit=_sparse_limit,
                    filter=payload_filter,
                    # Sparse BM25 is naturally self-filtering — no keyword overlap = no match.
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        return response.points or []

    @traceable(run_type="retriever", name="hc_qdrant_hybrid_search")
    async def retrieve_similar_values(
        self,
        query: str,
        table: str,
        column: str,
        limit: int = 25,
        *,
        dense_limit: Optional[int] = None,
        sparse_limit: Optional[int] = None,
        dense_query: Optional[str] = None,
        db_id: Optional[str] = None,
    ) -> List[str]:
        """Hybrid retrieval — dense + sparse + RRF. Returns a deduped list of values.

        Pass the original user term as ``dense_query`` and the LLM-expanded text
        as ``query`` for best precision/recall balance.
        """
        try:
            points = await self._hybrid_query(
                query, table, column,
                limit=limit, dense_limit=dense_limit, sparse_limit=sparse_limit,
                dense_query=dense_query, db_id=db_id,
            )
            values: List[str] = []
            scored: List[Tuple[str, float]] = []  # for diagnostic logging
            seen: set[str] = set()
            for p in points:
                v = str((p.payload or {}).get("value", "")).strip()
                k = v.lower()
                if v and k not in seen:
                    seen.add(k)
                    values.append(v)
                    scored.append((v, float(getattr(p, "score", 0.0) or 0.0)))
            # Log each candidate with its fused score so the operator can see
            # where the noise is coming in and tune HC_DENSE_SCORE_THRESHOLD.
            scored_preview = ", ".join(f"{val!r}:{score:.4f}" for val, score in scored)
            logger.info(
                "[HC] hybrid_search | %s.%s | term=%r | threshold=%.2f | n=%d | candidates=[%s]",
                table, column, query, _DENSE_SCORE_THRESHOLD, len(values), scored_preview,
            )
            return values
        except ModelConfigurationError:
            raise
        except Exception as e:
            logger.error(f"[HC] hybrid search error | {table}.{column} | err={e}")
            return []

    async def retrieve_similar_values_scored(
        self,
        query: str,
        table: str,
        column: str,
        limit: int = 25,
        *,
        search_limit: Optional[int] = None,
        db_id: Optional[str] = None,
    ) -> List[Tuple[str, float]]:
        """Backward-compat shim — same hybrid retrieval, but returns (value, RRF_score) tuples."""
        try:
            points = await self._hybrid_query(
                query, table, column,
                limit=limit,
                dense_limit=search_limit,
                sparse_limit=search_limit,
                db_id=db_id,
            )
            out: List[Tuple[str, float]] = []
            seen: set[str] = set()
            for p in points:
                v = str((p.payload or {}).get("value", "")).strip()
                k = v.lower()
                if v and k not in seen:
                    seen.add(k)
                    out.append((v, float(getattr(p, "score", 0.0) or 0.0)))
            return out
        except ModelConfigurationError:
            raise
        except Exception as e:
            logger.error(f"[HC] hybrid scored retrieval error: {e}")
            return []

    async def get_suffix_string(
        self, query: str, table: str, column: str, limit: int = 25, db_id: Optional[str] = None
    ) -> str:
        """Format hybrid-retrieved values for SQL-gen prompt suffix."""
        values = await self.retrieve_similar_values(query, table, column, limit=limit, db_id=db_id)
        if not values:
            return ""
        return f"Some example values for {column} in {table} are: {', '.join(values)}"


# Global instance
cardinality_store: Optional[QdrantCardinalityStore] = None


async def get_cardinality_store() -> QdrantCardinalityStore:
    """Get or create the cardinality store singleton."""
    global cardinality_store
    if cardinality_store is None:
        cardinality_store = QdrantCardinalityStore()
        await cardinality_store.initialize()
    return cardinality_store
