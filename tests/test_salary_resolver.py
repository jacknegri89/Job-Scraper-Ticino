"""Which salary is shown: stated before extracted before AI, never guessed, never converted wrongly."""

import pytest

from fx_rates import FxRate
from salary_resolver import resolve_salary

RATE = FxRate(eur_per_chf=1.09, source="ECB reference rate", date="2026-11-06")


def _job(country: str = "IT", **extra: object) -> dict:
    base = {"title": "Sviluppatore", "description": "", "country": country}
    base.update(extra)
    return base


def test_no_salary_anywhere_is_not_available() -> None:
    result = resolve_salary(_job())
    assert result["origin"] == "unavailable"
    assert result["net"] is None
    assert result["label"] == "Not available"


def test_stated_field_wins_over_text_and_ai() -> None:
    job = _job(salary_text="RAL 30.000", description="RAL 40.000", ai_salary={"amount": 50000, "currency": "EUR", "period": "year"})
    result = resolve_salary(job, RATE)
    assert result["origin"] == "stated"
    assert result["min"] == 30000


def test_structured_field_may_omit_the_currency_but_free_text_may_not() -> None:
    structured = resolve_salary(_job(salary_text="2.000 - 2.400 al mese lordi"), RATE)
    assert (structured["currency"], structured["period"]) == ("EUR", "month")
    free_text = resolve_salary(_job(description="Stipendio 2.000 - 2.400 al mese lordi"), RATE)
    assert free_text["origin"] == "unavailable"


def test_text_salary_wins_over_ai_estimate() -> None:
    job = _job(description="Offriamo RAL 28.000", ai_salary={"amount": 50000, "currency": "EUR", "period": "year"})
    result = resolve_salary(job, RATE)
    assert result["origin"] == "extracted"
    assert result["min"] == 28000


def test_ai_estimate_is_used_only_when_nothing_is_written() -> None:
    job = _job(ai_salary={"amount": 27000, "currency": "EUR", "period": "year"})
    result = resolve_salary(job, RATE)
    assert result["origin"] == "ai_estimate"
    assert result["net"]["kind"] == "italy"


def test_legacy_ai_estimate_is_read_as_swiss_francs_per_month() -> None:
    result = resolve_salary(_job("CH", estimated_gross_salary_chf=4000), RATE)
    assert result["origin"] == "ai_estimate"
    assert (result["currency"], result["period"]) == ("CHF", "month")


def test_italian_gross_salary_gets_an_italian_net_estimate() -> None:
    result = resolve_salary(_job(description="RAL 28.000"), RATE)
    net = result["net"]
    assert net["kind"] == "italy"
    assert net["monthly_min_eur"] == net["monthly_max_eur"] == 1671
    assert any("13 payments" in note or "tax year" in note for note in result["assumptions"])


def test_range_keeps_both_ends_and_sorts_by_the_middle() -> None:
    result = resolve_salary(_job(description="RAL 26.000 - 30.000"), RATE)
    assert (result["min"], result["max"]) == (26000, 30000)
    net = result["net"]
    assert net["monthly_min_eur"] < net["monthly_max_eur"]
    assert result["sort_value"] == pytest.approx((net["monthly_min_eur"] + net["monthly_max_eur"]) / 2)


def test_swiss_salary_uses_the_cross_border_estimate_and_reports_the_rate() -> None:
    result = resolve_salary(_job("CH", description="Salario CHF 4'500 al mese lordi"), RATE)
    net = result["net"]
    assert net["kind"] == "cross_border"
    assert net["fx"] == {"eur_per_chf": 1.09, "source": "ECB reference rate", "date": "2026-11-06"}
    assert any("1.0900" in note for note in result["assumptions"])


def test_net_amount_is_never_turned_into_gross() -> None:
    result = resolve_salary(_job(description="1.600 euro netti al mese"), RATE)
    assert result["basis"] == "net"
    assert result["net"]["kind"] == "stated_net"
    assert result["net"]["monthly_min_eur"] == 1600
    assert "tax calculation" in " ".join(result["assumptions"])


def test_net_amount_in_francs_is_only_converted_to_euro() -> None:
    result = resolve_salary(_job("CH", description="CHF 4'000 netti al mese"), RATE)
    assert result["net"]["monthly_min_eur"] == round(4000 * 1.09)


def test_unclear_basis_is_flagged_as_an_assumption() -> None:
    result = resolve_salary(_job(description="RAL 25.000", title="Dev"), RATE)
    assert result["basis"] == "gross"
    result = resolve_salary(_job(description="Compenso 2.200 euro al mese"), RATE)
    assert result["basis"] == "unknown"
    assert any("treated as gross" in note for note in result["assumptions"])


def test_hourly_pay_states_its_conversion() -> None:
    result = resolve_salary(_job("CH", description="Pensum 80%. Stipendio 28 CHF all'ora"), RATE)
    assert result["net"] is not None
    assert any("hours a week" in note and "80%" in note for note in result["assumptions"])


def test_amount_without_period_is_not_interpreted() -> None:
    result = resolve_salary(_job(description="Stipendio di 2.500 euro"), RATE)
    assert result["origin"] == "unavailable"
    assert "cannot be read safely" in result["note"]


def test_currency_that_does_not_match_the_country_gets_no_net() -> None:
    result = resolve_salary(_job("IT", description="Salario CHF 4'500 al mese lordi"), RATE)
    assert result["origin"] == "extracted"
    assert result["net"] is None
    assert any("currency does not match" in note for note in result["assumptions"])


def test_thirteenth_and_fourteenth_month_are_used_when_stated() -> None:
    thirteen = resolve_salary(_job(description="2.000 euro al mese lordi per 13 mensilita"), RATE)
    fourteen = resolve_salary(_job(description="2.000 euro al mese lordi per 14 mensilita"), RATE)
    assert fourteen["net"]["annual_min_eur"] > thirteen["net"]["annual_min_eur"]
    assert fourteen["net"]["payments"] == 14


def test_upper_limit_is_labelled_and_explained() -> None:
    result = resolve_salary(_job(salary_text="Fino a 48.000 € all'anno"), RATE)
    assert result["bound"] == "max"
    assert any("upper limit" in note for note in result["assumptions"])


def test_internship_allowance_gets_no_tax_calculation() -> None:
    result = resolve_salary(_job(salary_text="800 € al mese", contract_type="internship"), RATE)
    assert result["origin"] == "stated"
    assert result["net"] is None
    assert any("Internship allowance" in note for note in result["assumptions"])
