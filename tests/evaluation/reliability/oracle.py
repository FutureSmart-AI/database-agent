"""Small, explicit result contracts, not a general natural-language judge."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import math
import re


class EvaluationFailure(AssertionError):
    """A result did not satisfy its declared evaluation contract."""


class UnsupportedAnswerFormat(EvaluationFailure):
    """Requires manual review; does not establish a model factual error."""


def require(condition, message):
    if not condition:
        raise EvaluationFailure(message)


@dataclass(frozen=True)
class Column:
    name: str
    kind: str
    unit: str | None = None
    nullable: bool = False
    scale: int | None = None
    rounding: str = "exact"
    absolute_tolerance: Decimal = Decimal("0")

    def __post_init__(self):
        require(self.kind in {"text", "integer", "decimal", "boolean"}, "Unknown column kind")
        require(self.rounding in {"exact", "half_even"}, "Unknown rounding policy")
        require(self.absolute_tolerance.is_finite() and self.absolute_tolerance >= 0,
                "Tolerance must be finite and nonnegative")
        require(self.kind == "decimal" or self.absolute_tolerance == 0,
                "Tolerance is only defined for decimal columns")
        require(self.scale is None or (type(self.scale) is int and 0 <= self.scale <= 12),
                "Invalid decimal scale")


_DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")


def canonical(value, spec):
    if value is None:
        require(spec.nullable, "Unexpected NULL")
        return None
    if spec.kind == "text":
        require(type(value) is str, "Expected text")
        return value
    if spec.kind == "boolean":
        require(type(value) is bool, "Expected a boolean, not numeric truthiness")
        return value
    require(not isinstance(value, bool), "Boolean cannot stand in for a number")
    require(isinstance(value, (str, int, float, Decimal)), "Expected numeric value")
    if isinstance(value, float):
        require(math.isfinite(value), "Nonfinite numeric value")
    text = str(value)
    require(bool(_DECIMAL.fullmatch(text)), "Invalid numeric encoding")
    try:
        number = Decimal(text)
        require(number.is_finite(), "Nonfinite numeric value")
        if spec.kind == "integer":
            require(number == number.to_integral_value(), "Expected integral value")
        if spec.scale is not None:
            rounded = number.quantize(Decimal(1).scaleb(-spec.scale), rounding=ROUND_HALF_EVEN)
            require(spec.rounding != "exact" or rounded == number, "Undeclared rounding required")
            number = rounded
        return number
    except InvalidOperation as error:
        raise EvaluationFailure("Numeric value outside supported precision") from error


def normalized_rows(names, rows, columns):
    expected_names = [c.name for c in columns]
    require(len(names) == len(set(names)) and set(names) == set(expected_names),
            "Missing, extra or duplicate columns")
    require(isinstance(rows, (list, tuple)), "Expected complete row sequence")
    result = []
    for row in rows:
        if isinstance(row, dict):
            require(set(row) == set(expected_names), "Missing or extra row fields")
            values = [row[name] for name in expected_names]
        else:
            require(isinstance(row, (list, tuple)) and len(row) == len(names), "Wrong row width")
            values = [row[names.index(name)] for name in expected_names]
        result.append(tuple(canonical(v, c) for v, c in zip(values, columns)))
    return result


def compare_rows(names, rows, expected, columns, *, ordered):
    """Compare all rows. Unordered mode uses one-to-one matching, preserving duplicates.

    No relative tolerance. Absolute tolerance/rounding are per-column and opt-in.
    Matching is bipartite (not greedy), so overlapping tolerances cannot reuse a row.
    """
    require(type(ordered) is bool, "Ordering policy must be explicit")
    require(len({c.name for c in columns}) == len(columns), "Duplicate contract columns")
    actual = normalized_rows(names, rows, columns)
    reference = normalized_rows([c.name for c in columns], expected, columns)
    require(len(actual) == len(reference), "Missing, extra, duplicate or truncated rows")

    def same(a, b):
        for x, y, c in zip(a, b, columns):
            if x is None or y is None:
                if x is not y:
                    return False
            elif c.kind == "decimal":
                if abs(x - y) > c.absolute_tolerance:
                    return False
            elif x != y:
                return False
        return True

    if ordered:
        require(all(same(a, b) for a, b in zip(actual, reference)), "Ordered typed rows differ")
    else:
        assigned = {}

        def augment(index, seen):
            for j, row in enumerate(reference):
                if j not in seen and same(actual[index], row):
                    seen.add(j)
                    if j not in assigned or augment(assigned[j], seen):
                        assigned[j] = index
                        return True
            return False

        require(all(augment(i, set()) for i in range(len(actual))), "Typed row multiset differs")


_WIRE_TYPES = {
    "text": {"string", "text"}, "integer": {"integer", "number"},
    "decimal": {"integer", "number", "numeric", "decimal"}, "boolean": {"boolean"},
}


def compare_block(block, expected, columns, *, ordered):
    """Validate the product's complete columns/rows/row_count/truncated wire shape."""
    require(isinstance(block, dict), "API omitted typed data block")
    require(type(block.get("truncated")) is bool and block["truncated"] is False,
            "Missing or truncated data flag")
    rows = block.get("rows")
    require(isinstance(rows, list), "API omitted complete rows")
    require(all(isinstance(row, dict) for row in rows), "API rows must bind values by column name")
    require(type(block.get("row_count")) is int and block["row_count"] == len(rows),
            "False or missing row count")
    wire = block.get("columns")
    require(isinstance(wire, list) and all(isinstance(x, dict) for x in wire),
            "Missing typed column metadata")
    names = [x.get("name") for x in wire]
    require(all(type(x) is str for x in names), "Invalid column names")
    require(len(names) == len(set(names)), "Duplicate column metadata")
    by_name = {x["name"]: x for x in wire}
    require(set(names) == {c.name for c in columns}, "Wire schema differs")
    for c in columns:
        allowed = _WIRE_TYPES[c.kind] | ({"null"} if c.nullable and all(r.get(c.name) is None for r in rows if isinstance(r, dict)) else set())
        require(by_name[c.name].get("type") in allowed, "Wire column type differs")
        if "unit" in by_name[c.name]:
            require(by_name[c.name]["unit"] == c.unit, "Explicit wire unit differs")
    compare_rows(names, rows, expected, columns, ordered=ordered)


def verify_support(result, *, supported, unavailable_subjects=("review ratings", "ratings")):
    """Validate declared support; unavailable prose uses a bounded single sentence.

    Subjects are trusted case policy, never extracted from the candidate answer.
    Ambiguous/extra prose is manual review, not a general NLU factual verdict.
    """
    require(type(supported) is bool, "Support policy must be explicit")
    require(isinstance(result, dict), "Expected response object")
    require(type(result.get("is_answered")) is bool and result["is_answered"] is supported,
            "Supported versus unavailable outcome differs")
    if not supported:
        debug = result.get("debug_info") or {}
        require(isinstance(debug, dict), "Invalid debug metadata")
        require(not debug.get("sql_query"), "Unsupported answer leaked surrogate SQL")
        block = debug.get("db_result")
        require(block is None or (isinstance(block, dict) and block.get("rows") == []
                                 and block.get("columns") == []
                                 and type(block.get("row_count")) is int and block["row_count"] == 0
                                 and block.get("truncated") is False),
                "Unsupported answer leaked rows")
        answer = result.get("response", "")
        require(bool(unavailable_subjects) and all(type(s) is str and s.strip() for s in unavailable_subjects),
                "Unavailable subjects must be explicit case policy")
        subjects = "|".join(re.escape(" ".join(s.split())) for s in unavailable_subjects)
        pattern = (r"(?:" + subjects + r") (?:is|are) (?:unavailable|not available|not supported)"
                   r"(?: in this schema)?[.!]?")
        normalized = " ".join(answer.split()) if isinstance(answer, str) else ""
        if not re.fullmatch(pattern, normalized, re.I):
            raise UnsupportedAnswerFormat("Unavailable response outside declared single-sentence format; manual review required")


def verify_sales_narrative(answer, expected):
    """Conservative English two-region USD checker for the existing demo ONLY.

    Each entity must occur once and own exactly one amount before the next entity.
    Markdown emphasis/table punctuation and bare amounts in the declared USD
    context are accepted. Ambiguous prose, negation, additional numbers/units,
    totals or unsupported formats fail closed, rather than claiming semantic NLU.
    """
    def format_required(condition, message):
        if not condition:
            raise UnsupportedAnswerFormat(message)

    format_required(isinstance(answer, str) and bool(answer.strip()), "Missing narrative")
    text = answer.replace("**", "").replace("`", "")
    format_required(not re.search(r"\b(?:not|no|wrong|incorrect|unavailable|unsupported|approximately)\b", text, re.I),
            "Ambiguous or negated narrative")
    require(not re.search(r"[%€£¥₹₽]|\b(?:EUR|GBP|cents?|orders?|percent|thousands?|millions?)\b", text, re.I),
            "Narrative unit differs from USD amount")
    entities = {row[0].lower(): Decimal(str(row[1])) for row in expected}
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in entities) + r")\b", re.I)
    matches = list(pattern.finditer(text))
    format_required(len(matches) == len(entities) and {m[0].lower() for m in matches} == set(entities),
            "Missing, repeated or unknown entity association")
    format_required(not re.search(r"\d", text[:matches[0].start()]), "Unassociated numeric claim")
    prefix = text[:matches[0].start()]
    prefix = re.sub(r"\|[\s:|\-]+\|", "", prefix)  # Markdown header separator only.
    format_required(not re.search(r"[^A-Za-z\s$|:;,.()=]", prefix), "Unsupported narrative preamble syntax")
    prefix_words = re.findall(r"[A-Za-z]+", prefix.lower())
    format_required(set(prefix_words) <= {"here", "are", "is", "a", "the", "totals", "total", "by", "region",
                                  "amount", "revenue", "usd", "dollars", "for", "each", "breakdown", "of"},
            "Unrecognized narrative preamble; manual review required")
    for i, match in enumerate(matches):
        segment = text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        numbers = list(re.finditer(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", segment))
        format_required(len(numbers) == 1, "Expected exactly one amount per region")
        value = numbers[0]
        amount = canonical(value[0].replace(",", ""), Column("amount", "decimal", unit="USD", scale=2))
        require(amount == entities[match[0].lower()], "Narrative entity/amount association differs")
        residual = segment[:value.start()] + segment[value.end():]
        words = re.findall(r"[A-Za-z]+", residual.lower())
        format_required(set(words) <= {"total", "amount", "revenue", "is", "equals", "of", "was", "were",
                              "for", "the", "in", "usd", "dollars", "dollar", "and", "while", "whereas"},
                "Unrecognized narrative assertion; manual review required")
        # A sign must be part of the parsed numeric token. -$250 and accounting
        # parentheses cannot silently become positive250 after token extraction.
        format_required(not re.search(r"[^A-Za-z\s$|:;,.=]", residual), "Unsupported narrative syntax")
