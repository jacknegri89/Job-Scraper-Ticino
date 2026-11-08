"""Decide which salary to show for a job and what it means in take-home terms.

Order of trust:
1. stated   the portal gave a salary field (job["salary_text"]) that could be read
2. extracted a clear salary written in the title or description
3. ai_estimate the AI estimate for the candidate profile
4. unavailable nothing usable

A written salary always wins over an AI estimate. A net amount is never turned into a
gross one, and an amount without a period is never interpreted.
"""

from ai_analyzer import AI_GROSS_SALARY, AI_SALARY
from fx_rates import FxRate, manual_rate
from salary_calculator import calculate_net_salary
from salary_extractor import (
    BASIS_GROSS,
    BASIS_NET,
    BASIS_UNKNOWN,
    CURRENCY_CHF,
    CURRENCY_EUR,
    PERIOD_HOUR,
    PERIOD_MONTH,
    PERIOD_YEAR,
    extract_salary,
)
from salary_italy import DEFAULT_MONTHLY_PAYMENTS, calculate_italy_net

ORIGIN_STATED = "stated"
ORIGIN_EXTRACTED = "extracted"
ORIGIN_AI = "ai_estimate"
ORIGIN_NONE = "unavailable"

ORIGIN_LABELS = {
    ORIGIN_STATED: "Stated in the listing",
    ORIGIN_EXTRACTED: "Read from the listing text",
    ORIGIN_AI: "AI estimate",
    ORIGIN_NONE: "Not available",
}

HOURS_PER_WEEK = 40
WEEKS_PER_YEAR = 52
MONTHS_PER_YEAR = 12
SWISS_DEFAULT_PAYMENTS = 12
_DESCRIPTION_CHARS_READ = 3000
_COUNTRY_CURRENCY = {"CH": CURRENCY_CHF, "IT": CURRENCY_EUR}


def resolve_salary(job: dict, fx_rate: FxRate | None = None) -> dict:
    """Return the salary to display for a job, with its origin, net estimate and assumptions."""
    rate = fx_rate or manual_rate(None)
    country = str(job.get("country") or "")
    found, origin = _find_salary(job, country)
    if found is None:
        return _unavailable(job, country)
    return _with_net(found, origin, country, rate, str(job.get("contract_type") or ""))


def _find_salary(job: dict, country: str) -> tuple[dict | None, str]:
    default_currency = _COUNTRY_CURRENCY.get(country, "")
    stated_text = str(job.get("salary_text") or "")
    stated = extract_salary(stated_text, default_currency)
    if stated is not None and not stated.get("ambiguous"):
        return stated, ORIGIN_STATED
    text = f"{job.get('title') or ''}\n{str(job.get('description') or '')[:_DESCRIPTION_CHARS_READ]}"
    extracted = extract_salary(text, "")
    if extracted is not None and not extracted.get("ambiguous"):
        return extracted, ORIGIN_EXTRACTED
    ai_salary = _ai_salary(job)
    if ai_salary is not None:
        return ai_salary, ORIGIN_AI
    return None, ORIGIN_NONE


def _ai_salary(job: dict) -> dict | None:
    estimate = job.get(AI_SALARY)
    if isinstance(estimate, dict) and estimate.get("amount"):
        return _salary_record(estimate["currency"], estimate["period"], estimate["amount"], estimate["amount"],
                              BASIS_GROSS, "")
    legacy_amount = job.get(AI_GROSS_SALARY)
    if isinstance(legacy_amount, (int, float)) and not isinstance(legacy_amount, bool) and legacy_amount > 0:
        return _salary_record(CURRENCY_CHF, PERIOD_MONTH, legacy_amount, legacy_amount, BASIS_GROSS, "")
    return None


def _salary_record(currency: str, period: str, low: float, high: float, basis: str, text: str) -> dict:
    return {
        "ambiguous": False, "currency": currency, "period": period, "min": low, "max": high,
        "bound": "exact", "basis": basis, "payments": None, "employment_percent": None, "text": text,
    }


def _unavailable(job: dict, country: str) -> dict:
    ambiguous = _find_ambiguous(job, country)
    result = {
        "origin": ORIGIN_NONE, "label": ORIGIN_LABELS[ORIGIN_NONE], "currency": "", "period": "",
        "min": None, "max": None, "basis": "", "text": "", "net": None, "sort_value": None,
        "assumptions": [], "note": "",
    }
    if ambiguous is not None:
        result["note"] = f"An amount is written but cannot be read safely ({ambiguous.get('reason', '')})."
        result["text"] = ambiguous.get("text", "")
    return result


def _find_ambiguous(job: dict, country: str) -> dict | None:
    text = f"{job.get('salary_text') or ''}\n{job.get('title') or ''}\n{str(job.get('description') or '')[:_DESCRIPTION_CHARS_READ]}"
    found = extract_salary(text, _COUNTRY_CURRENCY.get(country, ""))
    if found is not None and found.get("ambiguous"):
        return found
    return None


def _with_net(found: dict, origin: str, country: str, rate: FxRate, contract_type: str) -> dict:
    assumptions: list[str] = []
    net = _net_for_contract(found, country, rate, contract_type, assumptions)
    if net is not None and found.get("bound") == "max":
        assumptions.append("Only an upper limit is written: the net estimate is calculated on that limit.")
    if net is not None and found.get("bound") == "min":
        assumptions.append("Only a lower limit is written: the net estimate is calculated on that limit.")
    return {
        "origin": origin,
        "label": ORIGIN_LABELS[origin],
        "currency": found["currency"],
        "period": found["period"],
        "bound": found.get("bound", "exact"),
        "min": found["min"],
        "max": found["max"],
        "basis": found["basis"],
        "text": found.get("text", ""),
        "net": net,
        "sort_value": _sort_value(net),
        "assumptions": assumptions,
        "note": "",
    }


def _net_for_contract(found: dict, country: str, rate: FxRate, contract_type: str,
                      assumptions: list[str]) -> dict | None:
    """An internship allowance is not a salary: it gets no tax calculation."""
    if contract_type == "internship":
        assumptions.append("Internship allowance: no tax calculation applied.")
        return None
    return _net_estimate(found, country, rate, assumptions)


def _net_estimate(found: dict, country: str, rate: FxRate, assumptions: list[str]) -> dict | None:
    if found["basis"] == BASIS_NET:
        return _stated_net(found, rate, assumptions)
    expected_currency = _COUNTRY_CURRENCY.get(country)
    if expected_currency is None or found["currency"] != expected_currency:
        assumptions.append("No net estimate: the currency does not match the country of the job.")
        return None
    if found["basis"] == BASIS_UNKNOWN:
        assumptions.append("The listing does not say gross or net: the amount is treated as gross.")
    annual_gross = _annual_gross(found, country, assumptions, "min"), _annual_gross(found, country, assumptions, "max")
    if country == "IT":
        return _italy_net(annual_gross, found, assumptions)
    return _swiss_net(annual_gross, rate, assumptions)


def _annual_gross(found: dict, country: str, assumptions: list[str], bound: str) -> float:
    amount = float(found[bound])
    period = found["period"]
    if period == PERIOD_YEAR:
        return amount
    if period == PERIOD_HOUR:
        return _annual_from_hourly(amount, found, assumptions)
    return amount * _payments(found, country, assumptions)


def _annual_from_hourly(hourly: float, found: dict, assumptions: list[str]) -> float:
    percent = found.get("employment_percent") or 100
    note = f"Hourly pay converted with {HOURS_PER_WEEK} hours a week, {WEEKS_PER_YEAR} weeks, {percent}% employment."
    if note not in assumptions:
        assumptions.append(note)
    return hourly * HOURS_PER_WEEK * WEEKS_PER_YEAR * percent / 100


def _payments(found: dict, country: str, assumptions: list[str]) -> int:
    stated = found.get("payments")
    if stated:
        return int(stated)
    default_payments = DEFAULT_MONTHLY_PAYMENTS
    if country == "CH":
        default_payments = SWISS_DEFAULT_PAYMENTS
    note = f"Monthly pay multiplied by {default_payments} payments a year (not stated in the listing)."
    if note not in assumptions:
        assumptions.append(note)
    return default_payments


def _italy_net(annual_gross: tuple[float, float], found: dict, assumptions: list[str]) -> dict | None:
    payments = found.get("payments") or DEFAULT_MONTHLY_PAYMENTS
    low_result = calculate_italy_net(annual_gross[0], payments)
    high_result = calculate_italy_net(annual_gross[1], payments)
    if not low_result or not high_result:
        return None
    assumptions.append(_italy_assumption(low_result))
    return {
        "kind": "italy",
        "monthly_min_eur": low_result["net_monthly_eur"],
        "monthly_max_eur": high_result["net_monthly_eur"],
        "annual_min_eur": low_result["net_annual_eur"],
        "annual_max_eur": high_result["net_annual_eur"],
        "payments": low_result["monthly_payments"],
        "details": high_result,
        "tax_year": low_result["tax_year"],
    }


def _italy_assumption(result: dict) -> str:
    left_out = ", ".join(result["not_included"])
    return f"Italian tax year {result['tax_year']}, permanent contract; not included: {left_out}."


def _swiss_net(annual_gross: tuple[float, float], rate: FxRate, assumptions: list[str]) -> dict | None:
    low_result = calculate_net_salary(annual_gross[0] / MONTHS_PER_YEAR, rate.eur_per_chf)
    high_result = calculate_net_salary(annual_gross[1] / MONTHS_PER_YEAR, rate.eur_per_chf)
    if not low_result or not high_result:
        return None
    rate_date = ""
    if rate.date:
        rate_date = f" of {rate.date}"
    assumptions.append(
        f"Cross-border worker living in Italy, simplified Swiss and Italian rules. "
        f"CHF converted at {rate.eur_per_chf:.4f} EUR ({rate.source}{rate_date})."
    )
    return {
        "kind": "cross_border",
        "monthly_min_eur": low_result["net_eur"],
        "monthly_max_eur": high_result["net_eur"],
        "monthly_min_chf": low_result["net_chf"],
        "monthly_max_chf": high_result["net_chf"],
        "details": high_result,
        "fx": {"eur_per_chf": rate.eur_per_chf, "source": rate.source, "date": rate.date},
    }


def _stated_net(found: dict, rate: FxRate, assumptions: list[str]) -> dict | None:
    """A net amount stays as written: it is only expressed per month, never converted to gross."""
    period = found["period"]
    if period == PERIOD_HOUR:
        assumptions.append("Net hourly pay: no monthly figure is calculated.")
        return None
    divisor = 1
    if period == PERIOD_YEAR:
        divisor = found.get("payments") or MONTHS_PER_YEAR
    factor = 1.0
    if found["currency"] == CURRENCY_CHF:
        factor = rate.eur_per_chf
        assumptions.append(f"Net amount converted from CHF at {rate.eur_per_chf:.4f} EUR ({rate.source}).")
    assumptions.append("Net amount as written in the listing; no tax calculation applied.")
    return {
        "kind": "stated_net",
        "monthly_min_eur": round(found["min"] / divisor * factor),
        "monthly_max_eur": round(found["max"] / divisor * factor),
    }


def _sort_value(net: dict | None) -> float | None:
    if net is None:
        return None
    return (net["monthly_min_eur"] + net["monthly_max_eur"]) / 2
