"""Schema support is distinct from a successfully executed aggregate, including zero."""
from pydantic import BaseModel, Field, StrictBool


class SQLQuerySchema(BaseModel):
    answerable: StrictBool = Field(..., description=(
        "Whether the available schema represents the requested entity and metric. "
        "False when it would require unrelated proxy data. A genuine count of zero is answerable."
    ))
    generated_query: str = Field(..., description=(
        "SQL for the requested metric when answerable; otherwise an empty string."
    ))
    reason: str = Field("", description="Explain the missing schema support when answerable is false.")


def apply_sql_decision(state, result):
    decision = SQLQuerySchema.model_validate(result)
    if decision.answerable:
        if not decision.generated_query.strip():
            raise ValueError("Answerable SQL generation returned no query")
        state["answerability_error"] = None
        return decision.generated_query
    state.update(
        answerability_error=decision.reason or "The available schema does not support the question.",
        sql_query="", sql_error=None, db_result=[], db_columns=None,
    )
    return ""


def failure_response(state):
    """Only explicit failures abstain; an aggregate row containing zero is valid data."""
    if state.get("access_policy_error"):
        return "I can't run this query because the table access settings could not be verified. The query was not executed."
    if state.get("access_denied_tables"):
        return "I can't answer this question because the required data source is restricted."
    if state.get("answerability_error"):
        return (
            "I can't determine this from the available tables: they don't contain data "
            "that supports the requested information. This does not establish a count of zero."
        )
    if state.get("sql_error"):
        return "I couldn't retrieve the requested data because the database query failed. No count was established."
    return None
