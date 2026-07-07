"""K5: structural anti-hallucination enforcement. After a turn completes,
extract every numeric claim from the assistant's TEXT and cross-check it
against every numeric value that appeared in THIS turn's tool-call
arguments/results. Unmatched material figures are flagged (not deleted) —
returned as unverifiedClaims for the UI to render inline and for logging.

This is the actual guarantee behind "never state a number you didn't get
from a tool call this turn" — the system prompt asks for that, but this
module is what makes it true regardless of whether the model follows
instructions."""

import re
from dataclasses import dataclass

_QUOTED_RE = re.compile(r'"[^"]*"|\'[^\']*\'')

_DOLLAR_RE = re.compile(r"\$\s?-?\d[\d,]*\.?\d*\s?([MmKkBb](?:illion)?)?")
_PERCENT_RE = re.compile(r"-?\d+\.?\d*\s?%")
_MULTIPLE_RE = re.compile(r"-?\d+\.?\d*\s?[xX](?![a-zA-Z])")
# "Bare" numeric claims: a metric keyword immediately followed by a plain
# decimal, e.g. "the DSCR is 1.4" — no $, %, or x suffix to key off of.
_KEYWORD_NUMBER_RE = re.compile(
    r"(?i)\b(dscr|debt service coverage(?: ratio)?|debt yield|equity multiple|"
    r"cash[- ]on[- ]cash|going[- ]in cap rate|yield on cost|loan constant)\b"
    r"[^0-9\-]{0,15}(-?\d+\.?\d*)"
)

_DOLLAR_SUFFIX_SCALE = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


@dataclass
class Claim:
    raw: str
    value: float
    kind: str  # "dollar" | "percent" | "multiple" | "bare"


def _normalize_dollar(match: re.Match) -> float:
    raw = match.group(0)
    suffix = (match.group(1) or "").strip().lower()[:1]
    numeric = re.sub(r"[^\d.\-]", "", raw)
    value = float(numeric) if numeric not in ("", "-", ".") else 0.0
    return value * _DOLLAR_SUFFIX_SCALE.get(suffix, 1)


def _normalize_percent(raw: str) -> float:
    numeric = raw.replace("%", "").strip()
    return float(numeric) / 100.0


def _normalize_multiple(raw: str) -> float:
    numeric = re.sub(r"[xX]\s*$", "", raw).strip()
    return float(numeric)


def _mask_quoted_spans(text: str) -> str:
    """Numbers inside quoted text are echoes, not claims — mask them out
    (same length, so other regex spans still line up) before extraction."""
    return _QUOTED_RE.sub(lambda m: " " * len(m.group(0)), text)


def extract_claims(text: str) -> list[Claim]:
    masked = _mask_quoted_spans(text)
    claims: list[Claim] = []
    covered: list[tuple[int, int]] = []

    for m in _DOLLAR_RE.finditer(masked):
        claims.append(Claim(raw=m.group(0).strip(), value=_normalize_dollar(m), kind="dollar"))
        covered.append(m.span())

    for m in _PERCENT_RE.finditer(masked):
        claims.append(Claim(raw=m.group(0).strip(), value=_normalize_percent(m.group(0)), kind="percent"))
        covered.append(m.span())

    for m in _MULTIPLE_RE.finditer(masked):
        claims.append(Claim(raw=m.group(0).strip(), value=_normalize_multiple(m.group(0)), kind="multiple"))
        covered.append(m.span())

    # Mask spans already claimed above before running the bare-keyword
    # pattern, so e.g. "equity multiple ... 1.55x" isn't double-counted as
    # both a "multiple" claim and a "bare" claim.
    keyword_source = list(masked)
    for start, end in covered:
        for i in range(start, end):
            keyword_source[i] = " "
    keyword_source = "".join(keyword_source)

    for m in _KEYWORD_NUMBER_RE.finditer(keyword_source):
        number = m.group(2)
        try:
            value = float(number)
        except ValueError:
            continue
        claims.append(Claim(raw=m.group(0).strip(), value=value, kind="bare"))

    return claims


def _flatten_numbers(obj) -> list[float]:
    numbers: list[float] = []
    if isinstance(obj, bool):
        return numbers
    if isinstance(obj, (int, float)):
        numbers.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            numbers.extend(_flatten_numbers(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            numbers.extend(_flatten_numbers(v))
    return numbers


def known_values_from_tool_calls(tool_call_log: list[dict]) -> set[float]:
    """Every numeric value that appeared anywhere in this turn's tool-call
    arguments or results — the only source of truth a claim may cite."""
    known: set[float] = set()
    for call in tool_call_log:
        known.update(_flatten_numbers(call.get("arguments")))
        known.update(_flatten_numbers(call.get("result")))
    return known


def _matches_any(value: float, known: set[float], *, rel_tol: float, abs_tol: float) -> bool:
    for k in known:
        if abs(value - k) <= max(abs_tol, rel_tol * max(abs(value), abs(k))):
            return True
    return False


_TOLERANCES = {
    "dollar": {"rel_tol": 0.01, "abs_tol": 1.0},
    "percent": {"rel_tol": 0.02, "abs_tol": 0.001},
    "multiple": {"rel_tol": 0.01, "abs_tol": 0.01},
    "bare": {"rel_tol": 0.01, "abs_tol": 0.01},
}


def check_provenance(text: str, tool_call_log: list[dict]) -> list[dict]:
    """Returns a list of {"raw", "value", "kind"} for every claim in `text`
    that doesn't trace back to a number seen in this turn's tool calls."""
    known = known_values_from_tool_calls(tool_call_log)
    claims = extract_claims(text)
    unverified = []
    for claim in claims:
        tol = _TOLERANCES[claim.kind]
        if not _matches_any(claim.value, known, **tol):
            unverified.append({"raw": claim.raw, "value": claim.value, "kind": claim.kind})
    return unverified
