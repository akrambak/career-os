"""Parse free-text compensation strings into structured (min, max, currency, period).

Used by the scraper layer at fetch-time and by `filters.py` (Tier 1 Upgrade 1)
to enforce the freelance hourly floor without burning Claude tokens.

Design notes:
- Regex-based, no dependencies. Multi-pass for clarity (currency, period,
  numbers) instead of one mega-regex.
- Static FX table — refreshed quarterly by hand (no live API). Used only for
  the floor comparison; we never store EUR-converted values.
- Ambiguous inputs return all-None Compensation — the floor filter abstains
  rather than mis-rejecting.
- `raw` is always preserved so the dashboard can still show the original text
  when parsing fails to extract structure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---- types -----------------------------------------------------------------

@dataclass(frozen=True)
class Compensation:
    min_amount: float | None
    max_amount: float | None
    currency: str | None         # ISO 4217 if recognized, else None
    period: str | None           # "year" | "month" | "day" | "hour" | None
    raw: str

    @property
    def known(self) -> bool:
        return self.min_amount is not None or self.max_amount is not None

    def to_eur_hourly(self) -> float | None:
        """Convert the lower bound to an EUR-equivalent hourly rate.

        Returns None when:
          - amount is unknown
          - currency is unknown (we don't guess)
          - period is unknown (the rule abstains rather than mis-rejecting)
        """
        if self.min_amount is None or self.currency is None or self.period is None:
            return None
        rate = _FX_TO_EUR.get(self.currency)
        if rate is None:
            return None
        eur_amount = self.min_amount * rate
        hours = _HOURS_PER_PERIOD.get(self.period)
        if hours is None:
            return None
        return eur_amount / hours


EMPTY = Compensation(
    min_amount=None, max_amount=None, currency=None, period=None, raw="",
)


# ---- constants -------------------------------------------------------------

# Static FX rates (quote = EUR per 1 unit of the foreign currency).
# Refresh quarterly — accuracy isn't load-bearing because the floor filter
# only kicks in well above/below the threshold.
_FX_TO_EUR: dict[str, float] = {
    "EUR": 1.00,
    "USD": 0.93,
    "GBP": 1.18,
    "CHF": 1.03,
    "CAD": 0.68,
    "AUD": 0.61,
    "JPY": 0.0062,
    "SEK": 0.087,
    "NOK": 0.086,
    "DKK": 0.134,
    "PLN": 0.23,
}

# Approximate working hours for a fully-utilized contractor — used only for
# the EUR-hourly floor conversion. Year = 52 wk × 5 d × 8 h × 90% utilization.
_HOURS_PER_PERIOD: dict[str, float] = {
    "hour": 1.0,
    "day": 8.0,
    "month": 160.0,
    "year": 1872.0,
}

_SYMBOL_TO_CURRENCY: dict[str, str] = {
    "$": "USD",     # NOTE: '$' is ambiguous (CAD/AUD/USD) — we pick the most common
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₣": "CHF",
}

_VAGUE_TERMS = (
    "competitive", "doe", "depending on experience", "negotiable",
    "tbd", "to be discussed", "market rate", "market-rate", "open",
    "based on experience", "n/a", "n.a.", "unspecified",
)


# ---- regex -----------------------------------------------------------------

# A "number" can be:
#   - plain digits: 80, 90000
#   - with comma or space thousand separators: 80,000  100 000
#   - with European dot thousands: 80.000
#   - decimal: 1.5, 2.5
#   - with k/K suffix: 80k, 150K
# Two unnamed groups: (digit body, optional kK suffix). The digit body
# matches either a separator-grouped form (80,000 / 80 000 / 80.000) OR a
# plain run of digits with optional decimal (6500 / 1.5).
_NUMBER = re.compile(
    r"(\d{1,3}(?:[,.\s]\d{3})+|\d+(?:\.\d+)?)\s*([kK])?",
)

# Range-separator pattern, matched against the substring BETWEEN two numbers.
# Hyphen, en-dash, em-dash, the word "to", a forward slash (for "60/80"-style).
_RANGE_SEP_RE = re.compile(r"^\s*(?:-|–|—|to|/)\s*$", re.IGNORECASE)

# ISO currency codes we recognize. We list only the realistic set for tech
# remote markets; an unknown 3-letter token returns currency=None which causes
# floor filtering to abstain.
_ISO_CODES = (
    "USD", "EUR", "GBP", "CHF", "CAD", "AUD", "JPY",
    "SEK", "NOK", "DKK", "PLN",
)
_CURRENCY_CODE = r"\b(" + "|".join(_ISO_CODES) + r")\b"
_CURRENCY_SYMBOL = r"[$€£¥₣]"

# Period markers. Order matters — match the longer ones first so "/hour" wins
# over "/h" by anchoring at word boundaries.
_PERIOD_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?:/|\s+per\s+|\s)\s*hourly\b", re.IGNORECASE), "hour"),
    (re.compile(r"(?:/|\s+per\s+|\s)\s*hour\b", re.IGNORECASE), "hour"),
    (re.compile(r"(?:/|\s+per\s+)\s*hr\b", re.IGNORECASE), "hour"),
    (re.compile(r"/\s*h\b", re.IGNORECASE), "hour"),
    (re.compile(r"(?:/|\s+per\s+|\s)\s*daily\b", re.IGNORECASE), "day"),
    (re.compile(r"(?:/|\s+per\s+|\s)\s*day\b", re.IGNORECASE), "day"),
    (re.compile(r"/\s*d\b", re.IGNORECASE), "day"),
    (re.compile(r"(?:/|\s+per\s+|\s)\s*monthly\b", re.IGNORECASE), "month"),
    (re.compile(r"(?:/|\s+per\s+|\s)\s*month\b", re.IGNORECASE), "month"),
    (re.compile(r"/\s*mo\b", re.IGNORECASE), "month"),
    (re.compile(r"(?:/|\s+per\s+|\s)\s*annual(?:ly)?\b", re.IGNORECASE), "year"),
    (re.compile(r"(?:/|\s+per\s+|\s)\s*year\b", re.IGNORECASE), "year"),
    (re.compile(r"(?:/|\s+per\s+|\s)\s*yearly\b", re.IGNORECASE), "year"),
    (re.compile(r"/\s*yr\b", re.IGNORECASE), "year"),
    (re.compile(r"\bp\.?a\.?\b", re.IGNORECASE), "year"),
    (re.compile(r"\bp\.?m\.?\b", re.IGNORECASE), "month"),
]


# ---- public API ------------------------------------------------------------

def parse(text: str | None) -> Compensation:
    """Parse a free-text compensation string. Never raises."""
    if not text or not text.strip():
        return EMPTY
    raw = text.strip()
    lower = raw.lower()
    # Vague terms with no numbers: short-circuit. (If a vague term appears next
    # to a real range like "Competitive — $80k–$120k", we still try to parse
    # the numbers.)
    if any(term in lower for term in _VAGUE_TERMS) and not re.search(r"\d", raw):
        return Compensation(None, None, None, None, raw=raw)

    currency = _detect_currency(raw)
    period = _detect_period(raw)
    min_amt, max_amt = _detect_amounts(raw)

    # Period heuristics when nothing matched explicitly.
    if period is None and min_amt is not None:
        period = _guess_period(min_amt, raw)

    return Compensation(
        min_amount=min_amt,
        max_amount=max_amt,
        currency=currency,
        period=period,
        raw=raw,
    )


def parse_from_numeric(
    min_amount: float | None, max_amount: float | None,
    currency: str = "USD", period: str = "year",
    raw: str | None = None,
) -> Compensation:
    """Convenience: build a Compensation when the source already has numeric
    fields (e.g., RemoteOK's `salary_min`/`salary_max`). Skips the regex pass.
    """
    if min_amount is None and max_amount is None:
        return Compensation(
            None, None, None, None,
            raw=(raw or "").strip(),
        )
    return Compensation(
        min_amount=float(min_amount) if min_amount is not None else None,
        max_amount=float(max_amount) if max_amount is not None else None,
        currency=currency if currency in _ISO_CODES else None,
        period=period if period in _HOURS_PER_PERIOD else None,
        raw=(raw or "").strip(),
    )


# ---- internals -------------------------------------------------------------

def _detect_currency(text: str) -> str | None:
    """ISO code wins over symbol if both present (more specific)."""
    m = re.search(_CURRENCY_CODE, text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m = re.search(_CURRENCY_SYMBOL, text)
    if m:
        return _SYMBOL_TO_CURRENCY.get(m.group(0))
    return None


def _detect_period(text: str) -> str | None:
    for pat, period in _PERIOD_PATTERNS:
        if pat.search(text):
            return period
    return None


def _detect_amounts(text: str) -> tuple[float | None, float | None]:
    """Find one or two numbers in the text and return (min, max).

    Returns (None, None) when no plausible amount is found. A single number
    becomes (n, n) — callers can detect "single" by min == max if they care.
    """
    matches = list(_NUMBER.finditer(text))
    if not matches:
        return None, None

    # Single value — easy.
    if len(matches) == 1:
        n = _parse_one(matches[0].group(1), matches[0].group(2))
        if n is None:
            return None, None
        return n, n

    # Two or more numbers — check whether the FIRST two form a range. The gap
    # between them must be (at most) a range separator like ' - ', ' – ', ' to ',
    # possibly preceded by a currency symbol/code.
    first, second = matches[0], matches[1]
    gap = text[first.end():second.start()]
    # Strip a currency symbol or ISO code from the gap (e.g., "$80k - $120k"
    # has "$" between the numbers in addition to the separator).
    gap_no_currency = re.sub(_CURRENCY_SYMBOL, "", gap)
    gap_no_currency = re.sub(_CURRENCY_CODE, "", gap_no_currency, flags=re.IGNORECASE)

    if _RANGE_SEP_RE.match(gap_no_currency):
        a = _parse_one(first.group(1), first.group(2))
        b = _parse_one(second.group(1), second.group(2))
        if a is not None and b is not None:
            lo, hi = (a, b) if a <= b else (b, a)
            return lo, hi
        # One number parsed, the other didn't — degrade gracefully.
        return (a if a is not None else b), (b if b is not None else a)

    # Not a range — return the first number only.
    n = _parse_one(first.group(1), first.group(2))
    if n is None:
        return None, None
    return n, n


def _parse_one(num: str, k_suffix: str | None) -> float | None:
    """Turn "80,000" / "80k" / "1.5" into a float. Returns None on garbage."""
    # Strip thousand separators (comma or space). A decimal point with exactly
    # one trailing group of 1-2 digits is preserved as fractional; everything
    # else is normalized to integer with separators dropped.
    cleaned = num.replace(",", "").replace(" ", "")
    # If the cleaned number has a single dot and the trailing part looks like
    # a thousands-separator (3 digits, no decimal use elsewhere), drop the dot.
    if cleaned.count(".") == 1:
        before, after = cleaned.split(".")
        if len(after) == 3 and after.isdigit() and not k_suffix:
            cleaned = before + after
    try:
        n = float(cleaned)
    except ValueError:
        return None
    if k_suffix:
        n *= 1000.0
    return n


def _guess_period(min_amount: float, raw: str) -> str | None:
    """Period heuristic when nothing explicit was found.

    Rules:
      - amount >= 20_000 → "year" (clearly an annual salary)
      - amount in 1_000..19_999 → "month" (typical monthly take-home band)
      - amount in 20..500 → ambiguous (could be hourly OR token misread); abstain
      - amount < 20 → too small to be meaningful; abstain
    The 'rate' / 'hourly' raw-text hint isn't checked here because explicit
    period detection already runs first — if we reached this function and
    none of the period regexes matched, the source didn't say.
    """
    if min_amount >= 20_000:
        return "year"
    if min_amount >= 1_000:
        return "month"
    return None
