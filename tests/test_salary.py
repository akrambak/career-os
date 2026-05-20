"""Salary parser fixtures. Drawn from real prod data shapes:
- RemoteOK's `_format_salary` output (en-dash ranges, "from $X")
- Remotive's free-text `salary` field
- HN freelancer briefs ("$60/hr", "€3000/wk", "€80-120/hour")
- WeWorkRemotely descriptions (we don't parse these yet; flagged below)
"""
from __future__ import annotations

import pytest

from career_os.salary import EMPTY, Compensation, parse, parse_from_numeric


def _c(min_a, max_a, currency, period):
    """Tuple shorthand for fixture readability."""
    return (min_a, max_a, currency, period)


def _actual(text: str):
    c = parse(text)
    return (c.min_amount, c.max_amount, c.currency, c.period)


# ---- empty / vague --------------------------------------------------------

@pytest.mark.parametrize("text", ["", None, "   ", "\n\t"])
def test_empty_inputs_return_empty(text):
    assert parse(text) == EMPTY


@pytest.mark.parametrize("text", [
    "Competitive",
    "DOE",
    "Depending on experience",
    "Negotiable",
    "TBD",
    "to be discussed",
    "Market rate",
    "N/A",
])
def test_vague_terms_with_no_numbers_return_all_none(text):
    c = parse(text)
    assert c.min_amount is None
    assert c.max_amount is None
    assert c.period is None
    assert c.raw == text


def test_vague_term_with_numbers_still_parses():
    # "Competitive — $80k-$120k" should yield numbers.
    c = parse("Competitive — $80k-$120k")
    assert c.min_amount == 80000
    assert c.max_amount == 120000
    assert c.currency == "USD"
    assert c.period == "year"


# ---- yearly ranges (RemoteOK shape) ---------------------------------------

def test_remoteok_range_en_dash():
    assert _actual("$80,000–$120,000") == _c(80000, 120000, "USD", "year")


def test_remoteok_range_em_dash():
    assert _actual("$80,000—$120,000") == _c(80000, 120000, "USD", "year")


def test_remoteok_range_hyphen():
    assert _actual("$80,000-$120,000") == _c(80000, 120000, "USD", "year")


def test_remoteok_from_floor():
    c = parse("from $90,000")
    # Single value: min == max == 90000
    assert c.min_amount == 90000
    assert c.max_amount == 90000
    assert c.currency == "USD"
    assert c.period == "year"


def test_yearly_with_k_shortcut():
    assert _actual("$80k - $120k") == _c(80000, 120000, "USD", "year")


def test_yearly_eur_with_k():
    assert _actual("€80k–€120k") == _c(80000, 120000, "EUR", "year")


def test_yearly_with_iso_code_overrides_symbol():
    # ISO code takes precedence over '$' (which is ambiguous CAD/AUD/USD).
    assert _actual("$80,000 USD - $120,000 USD") == _c(80000, 120000, "USD", "year")


def test_yearly_with_iso_only():
    assert _actual("100k EUR - 150k EUR") == _c(100000, 150000, "EUR", "year")


def test_yearly_with_iso_prefix():
    assert _actual("USD 100,000 - 150,000") == _c(100000, 150000, "USD", "year")


def test_yearly_with_pa():
    assert _actual("£90,000 p.a.") == _c(90000, 90000, "GBP", "year")


def test_yearly_with_per_year_spelled_out():
    assert _actual("$120,000 per year") == _c(120000, 120000, "USD", "year")


# ---- hourly ---------------------------------------------------------------

def test_hourly_euro_slash_hr():
    assert _actual("€60/hr") == _c(60, 60, "EUR", "hour")


def test_hourly_dollar_per_hour():
    assert _actual("$100/hour") == _c(100, 100, "USD", "hour")


def test_hourly_range():
    assert _actual("€60-80/hr") == _c(60, 80, "EUR", "hour")


def test_hourly_iso_code_with_unit():
    assert _actual("60-80 EUR/hour") == _c(60, 80, "EUR", "hour")


def test_hourly_per_hour_long_form():
    assert _actual("USD 150 per hour") == _c(150, 150, "USD", "hour")


def test_hourly_hourly_word():
    assert _actual("$200 hourly") == _c(200, 200, "USD", "hour")


def test_hourly_short_h_suffix():
    assert _actual("€75/h") == _c(75, 75, "EUR", "hour")


# ---- monthly --------------------------------------------------------------

def test_monthly_slash_mo():
    assert _actual("USD 6500/mo") == _c(6500, 6500, "USD", "month")


def test_monthly_per_month():
    assert _actual("€5,000 per month") == _c(5000, 5000, "EUR", "month")


def test_monthly_pm_suffix():
    assert _actual("£4,500 p.m.") == _c(4500, 4500, "GBP", "month")


def test_monthly_range():
    assert _actual("€5,000-7,000/month") == _c(5000, 7000, "EUR", "month")


# ---- daily ----------------------------------------------------------------

def test_daily_slash_day():
    assert _actual("€700/day") == _c(700, 700, "EUR", "day")


def test_daily_per_day():
    assert _actual("$1,200 per day") == _c(1200, 1200, "USD", "day")


# ---- ambiguous / heuristic ------------------------------------------------

def test_bare_year_amount_inferred_yearly():
    # ≥ 20000 with no period marker → year
    c = parse("80,000")
    assert c.min_amount == 80000
    assert c.period == "year"
    assert c.currency is None


def test_bare_amount_3000_inferred_monthly():
    # 1000–19999 with no period → month (typical contractor monthly)
    c = parse("3000")
    assert c.min_amount == 3000
    assert c.period == "month"


def test_bare_small_amount_period_unknown():
    # 20-500 without unit is ambiguous (could be hourly, could be tokens) →
    # abstain so the floor filter doesn't mis-reject.
    c = parse("75")
    assert c.min_amount == 75
    assert c.period is None


def test_currency_unknown_returns_none_currency():
    # No symbol, no ISO code → currency=None even if numbers parse.
    c = parse("90,000-120,000")
    assert c.min_amount == 90000
    assert c.max_amount == 120000
    assert c.currency is None
    assert c.period == "year"


def test_swap_when_max_less_than_min():
    # Defensive: sources sometimes post "$120k-$80k" by mistake.
    assert _actual("$120k - $80k") == _c(80000, 120000, "USD", "year")


# ---- parse_from_numeric (for sources that already give us numbers) -------

def test_parse_from_numeric_basic():
    c = parse_from_numeric(80000, 120000, currency="USD", period="year",
                           raw="$80,000–$120,000")
    assert c.min_amount == 80000
    assert c.max_amount == 120000
    assert c.currency == "USD"
    assert c.period == "year"
    assert c.raw == "$80,000–$120,000"


def test_parse_from_numeric_unknown_currency_becomes_none():
    c = parse_from_numeric(80000, 120000, currency="ZZZ", period="year")
    assert c.currency is None


def test_parse_from_numeric_unknown_period_becomes_none():
    c = parse_from_numeric(80000, None, currency="USD", period="lunar")
    assert c.period is None


def test_parse_from_numeric_both_none():
    c = parse_from_numeric(None, None)
    assert not c.known


# ---- to_eur_hourly --------------------------------------------------------

def test_eur_hourly_from_eur_hourly():
    c = parse("€60/hr")
    assert c.to_eur_hourly() == pytest.approx(60.0)


def test_eur_hourly_from_usd_hourly():
    c = parse("$100/hour")
    # 100 USD × 0.93 EUR/USD = 93 EUR/hr
    assert c.to_eur_hourly() == pytest.approx(93.0, abs=0.5)


def test_eur_hourly_from_eur_yearly():
    c = parse("€100k/year")
    # 100000 EUR / 1872 hours ≈ 53.4 EUR/hr
    assert c.to_eur_hourly() == pytest.approx(53.4, abs=0.5)


def test_eur_hourly_unknown_currency_abstains():
    c = parse("90,000 per year")
    assert c.currency is None
    assert c.to_eur_hourly() is None


def test_eur_hourly_unknown_period_abstains():
    c = parse("€75")  # too small to infer yearly, no period marker
    assert c.period is None
    assert c.to_eur_hourly() is None


def test_eur_hourly_below_floor_for_usd_hourly():
    # $40/hr × 0.93 = ~37.2 EUR/hr — well under €60 floor
    c = parse("$40/hr")
    eur = c.to_eur_hourly()
    assert eur is not None
    assert eur < 60


# ---- known property ------------------------------------------------------

def test_known_true_when_any_amount():
    assert parse("$80k").known is True


def test_known_false_when_empty():
    assert EMPTY.known is False


def test_known_false_for_vague():
    assert parse("Competitive").known is False


# ---- raw preserved -------------------------------------------------------

def test_raw_is_preserved_even_when_parsing_fails():
    c = parse("Salary: see website")
    assert c.raw == "Salary: see website"
    assert not c.known


def test_raw_is_stripped():
    c = parse("  $80k  ")
    assert c.raw == "$80k"


# ---- never raises --------------------------------------------------------

@pytest.mark.parametrize("garbage", [
    "$$$$", "€€", "k", "kk", "/hr/hr/hr", "----",
    "123abc456",   # mixed garbage
    "1.2.3.4",     # not a real number shape
    "USD",         # currency only
    "/hr",         # period only
])
def test_garbage_never_raises_and_returns_compensation(garbage):
    c = parse(garbage)
    assert isinstance(c, Compensation)
    # Don't assert on specific fields — just that no exception escaped.
