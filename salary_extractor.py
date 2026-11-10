"""Read a salary written in a listing, without guessing what is not written.

An amount is used only when a currency (or "RAL") is next to it and a period such as
month, year or hour is stated. Anything less clear is reported as ambiguous so the
dashboard can say "not available" instead of inventing a number.
"""

import re

PERIOD_MONTH = "month"
PERIOD_YEAR = "year"
PERIOD_HOUR = "hour"

BASIS_GROSS = "gross"
BASIS_NET = "net"
BASIS_UNKNOWN = "unknown"

CURRENCY_CHF = "CHF"
CURRENCY_EUR = "EUR"

# Plausible amounts per period; anything outside is not read as a salary.
PLAUSIBLE_RANGES = {
    PERIOD_MONTH: (800, 40_000),
    PERIOD_YEAR: (10_000, 500_000),
    PERIOD_HOUR: (7, 300),
}

_AMOUNT = r"\d{1,3}(?:[.'’\xa0 ]\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?\s?[kK]?"
_CURRENCY = r"CHF|SFr\.?|Fr\.|EUR|€|euro"
_SALARY_PATTERN = re.compile(
    r"(?P<cur_before>" + _CURRENCY + r")?\s?"
    r"(?P<first>" + _AMOUNT + r")"
    r"(?:\s?(?P<cur_first>" + _CURRENCY + r"))?"
    r"(?:\s?(?:-|–|—|a|e|bis|to)\s?(?P<cur_middle>" + _CURRENCY + r")?\s?(?P<second>" + _AMOUNT + r"))?"
    r"\s?(?P<cur_after>" + _CURRENCY + r")?",
    re.IGNORECASE,
)
_RAL_PATTERN = re.compile(r"\bRAL\b", re.IGNORECASE)

_HOUR_WORDS = re.compile(r"all'ora|/\s?ora|orari[oae]|per ora|/\s?h\b|\bh\b|stunde|hour", re.IGNORECASE)
_MONTH_WORDS = re.compile(r"al mese|mensil|/\s?mese|per mese|monat|month|/\s?mo\b", re.IGNORECASE)
_YEAR_WORDS = re.compile(r"annu|all'anno|l'anno|/\s?anno|\bRAL\b|jahr|year|p\.a\.", re.IGNORECASE)
_GROSS_WORDS = re.compile(r"lord[oi]|brutto|gross|\bRAL\b", re.IGNORECASE)
_NET_WORDS = re.compile(r"nett[oi]|\bnet\b|netto", re.IGNORECASE)
_PAYMENTS_WORDS = re.compile(r"(13|14)\s?(?:mensilit|monatsl|th\b)|tredicesima|quattordicesima|13th", re.IGNORECASE)
_EMPLOYMENT_PERCENT = re.compile(
    r"(?:impiego|pensum|occupazione|tempo)[^\d%]{0,20}(\d{2,3})\s?%|(\d{2,3})\s?%\s?(?:di\s+)?(?:impiego|pensum|occupazione)",
    re.IGNORECASE,
)
_UPPER_LIMIT_WORDS = re.compile(r"(?:fino a|up to|bis zu|al massimo|massimo|max\.?)\s*$", re.IGNORECASE)
_LOWER_LIMIT_WORDS = re.compile(r"(?:a partire da|almeno|minimo|from|ab|min\.?)\s*$", re.IGNORECASE)
BOUND_EXACT = "exact"
BOUND_MAX = "max"
BOUND_MIN = "min"
_CONTEXT_AFTER = 45
_CONTEXT_BEFORE = 30
_SNIPPET_LENGTH = 90
MIN_EMPLOYMENT_PERCENT = 10
MAX_EMPLOYMENT_PERCENT = 100


def extract_salary(text: str, default_currency: str = "") -> dict | None:
    """Return the first clearly written salary in the text, an ambiguous marker, or None."""
    if not text:
        return None
    ambiguous_candidate = None
    for match in _SALARY_PATTERN.finditer(text):
        candidate = _read_candidate(text, match, default_currency)
        if candidate is None:
            continue
        if not candidate.get("ambiguous"):
            return candidate
        if ambiguous_candidate is None:
            ambiguous_candidate = candidate
    return ambiguous_candidate


def _read_candidate(text: str, match: re.Match, default_currency: str) -> dict | None:
    before_text = text[max(0, match.start() - _CONTEXT_BEFORE):match.start()]
    after_text = text[match.end():match.end() + _CONTEXT_AFTER]
    currency = _currency_of(match, before_text, default_currency)
    if currency == "":
        return None
    amounts = _amounts_of(match)
    if amounts is None:
        return None
    snippet = _snippet(text, match)
    period = _first_period(after_text, before_text)
    if period is None:
        return {"ambiguous": True, "reason": "no period stated", "text": snippet}
    low_amount, high_amount = amounts
    if not _is_plausible(period, low_amount, high_amount):
        return {"ambiguous": True, "reason": "amount not plausible for the period", "text": snippet}
    return {
        "ambiguous": False,
        "currency": currency,
        "period": period,
        "min": low_amount,
        "max": high_amount,
        "bound": _bound_of(before_text, low_amount, high_amount),
        "basis": _basis_of(after_text, before_text),
        "payments": _payments_of(before_text + text[match.start():match.end()] + after_text),
        "employment_percent": _employment_percent(text),
        "text": snippet,
    }


def _bound_of(before_text: str, low_amount: float, high_amount: float) -> str:
    """A single amount after 'up to' or 'from' is a limit, not the exact pay."""
    if low_amount != high_amount:
        return BOUND_EXACT
    if _UPPER_LIMIT_WORDS.search(before_text):
        return BOUND_MAX
    if _LOWER_LIMIT_WORDS.search(before_text):
        return BOUND_MIN
    return BOUND_EXACT


def _currency_of(match: re.Match, before_text: str, default_currency: str) -> str:
    for group_name in ("cur_before", "cur_first", "cur_middle", "cur_after"):
        found = match.group(group_name)
        if found:
            return _currency_code(found)
    if _RAL_PATTERN.search(before_text):
        return CURRENCY_EUR
    # Only structured salary fields pass a default currency; free text never does.
    return default_currency


def _currency_code(raw_currency: str) -> str:
    lowered = raw_currency.lower()
    if lowered in ("eur", "€", "euro"):
        return CURRENCY_EUR
    return CURRENCY_CHF


def _amounts_of(match: re.Match) -> tuple[float, float] | None:
    first_text = match.group("first")
    second_text = match.group("second")
    first_value = parse_amount(first_text)
    if first_value is None:
        return None
    if second_text is None:
        return first_value, first_value
    second_value = parse_amount(second_text)
    if second_value is None:
        return None
    if second_text.strip().lower().endswith("k") and first_value < 1000:
        first_value *= 1000
    if second_value < first_value:
        return None
    return first_value, second_value


def parse_amount(raw_amount: str) -> float | None:
    """Turn '3.500', "3'500", '3 500,50' or '45k' into a number."""
    cleaned = raw_amount.strip().lower().replace("’", "'")
    multiplier = 1000 if cleaned.endswith("k") else 1
    cleaned = cleaned.rstrip("k").strip()
    cleaned = re.sub(r"['\xa0 ]", "", cleaned)
    cleaned = _normalize_separators(cleaned)
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def _normalize_separators(number_text: str) -> str:
    last_dot = number_text.rfind(".")
    last_comma = number_text.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        if last_comma > last_dot:
            return number_text.replace(".", "").replace(",", ".")
        return number_text.replace(",", "")
    if last_dot < 0 and last_comma < 0:
        return number_text
    separator = ","
    if last_dot >= 0:
        separator = "."
    digits_after = len(number_text) - number_text.rfind(separator) - 1
    if digits_after == 3:
        return number_text.replace(separator, "")
    return number_text.replace(separator, ".")


def _first_period(after_text: str, before_text: str) -> str | None:
    for context in (after_text, before_text):
        period = _period_in(context)
        if period is not None:
            return period
    return None


def _period_in(context: str) -> str | None:
    if _HOUR_WORDS.search(context):
        return PERIOD_HOUR
    if _MONTH_WORDS.search(context):
        return PERIOD_MONTH
    if _YEAR_WORDS.search(context):
        return PERIOD_YEAR
    return None


def _basis_of(after_text: str, before_text: str) -> str:
    for context in (after_text, before_text):
        if _NET_WORDS.search(context):
            return BASIS_NET
        if _GROSS_WORDS.search(context):
            return BASIS_GROSS
    return BASIS_UNKNOWN


def _payments_of(context: str) -> int | None:
    found = _PAYMENTS_WORDS.search(context)
    if found is None:
        return None
    if found.group(1):
        return int(found.group(1))
    if "quattordicesima" in found.group(0).lower():
        return 14
    return 13


def _employment_percent(text: str) -> int | None:
    found = _EMPLOYMENT_PERCENT.search(text)
    if found is None:
        return None
    percent = int(found.group(1) or found.group(2))
    if MIN_EMPLOYMENT_PERCENT <= percent <= MAX_EMPLOYMENT_PERCENT:
        return percent
    return None


def _is_plausible(period: str, low_amount: float, high_amount: float) -> bool:
    lowest, highest = PLAUSIBLE_RANGES[period]
    return lowest <= low_amount and high_amount <= highest


def _snippet(text: str, match: re.Match) -> str:
    start = max(0, match.start() - 10)
    return " ".join(text[start:start + _SNIPPET_LENGTH].split())
