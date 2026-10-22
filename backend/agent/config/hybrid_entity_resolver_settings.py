"""Environment-driven settings for hybrid entity resolution (lexical + vector)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class HybridEntityResolverSettings:
    enabled: bool
    # Kept for backward compatibility with env; resolver uses lexical→vector merge, not L/V weights.
    lexical_weight: float
    vector_weight: float
    top_n: int
    pg_candidate_limit: int
    qdrant_search_limit: int

    @staticmethod
    def load() -> HybridEntityResolverSettings:
        enabled = _bool_env("USE_HYBRID_ENTITY_RESOLVER", True)
        lw = _float_env("HYBRID_ENTITY_WEIGHT_LEXICAL", 0.50)
        vw = _float_env("HYBRID_ENTITY_WEIGHT_VECTOR", 0.50)
        total = lw + vw
        if total <= 0:
            lw, vw = 0.50, 0.50
            total = 1.0
        if abs(total - 1.0) > 1e-6:
            inv = 1.0 / total
            lw, vw = lw * inv, vw * inv
        return HybridEntityResolverSettings(
            enabled=enabled,
            lexical_weight=lw,
            vector_weight=vw,
            top_n=max(1, _int_env("HYBRID_ENTITY_TOP_N", 25)),
            pg_candidate_limit=max(5, _int_env("HYBRID_PG_CANDIDATE_LIMIT", 100)),
            qdrant_search_limit=max(10, _int_env("HYBRID_QDRANT_SEARCH_LIMIT", 100)),
        )
