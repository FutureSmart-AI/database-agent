from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class HCProfilingConfigRequest(BaseModel):
    low_cardinality_threshold: Optional[int] = 20
    high_null_threshold: Optional[float] = 95.0
    min_avg_text_len_for_hc: Optional[float] = 2.0
    sample_limit: Optional[int] = 5


class TriggerHCProfileRequest(BaseModel):
    config: Optional[HCProfilingConfigRequest] = None
    tables: Optional[List[str]] = None  # None = profile all tables
    auto_register_hc: bool = True       # auto-index HC_TEXT_SEARCH columns into Qdrant
