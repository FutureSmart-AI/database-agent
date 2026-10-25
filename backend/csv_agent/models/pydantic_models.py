from pydantic import BaseModel, Field
from typing import Optional

# CSV agent Pydantic Models

class CSVQueryRequest(BaseModel):
    query: str
    answer: Optional[bool] = False


class CSVQueryResponse(BaseModel):
    dataframe: dict
    answer: Optional[str] = None
