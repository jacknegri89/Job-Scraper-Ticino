"""Reading salaries written in listings: clear cases, ranges and refusals to guess."""

from salary_extractor import extract_salary, parse_amount


def test_parse_amount_handles_italian_and_swiss_formats() -> None:
    assert parse_amount("3.500") == 3500
    assert parse_amount("3'500") == 3500
    assert parse_amount("3 500,50") == 3500.5
    assert parse_amount("45k") == 45000
    assert parse_amount("1,234.56") == 1234.56


def test_ral_without_currency_is_euro_gross_per_year() -> None:
    result = extract_salary("Offriamo RAL 28.000 - 32.000 e benefit")
    assert result["currency"] == "EUR"
    assert result["period"] == "year"
    assert result["basis"] == "gross"
    assert (result["min"], result["max"]) == (28000, 32000)


def test_swiss_monthly_range_in_francs() -> None:
    result = extract_salary("Salario CHF 4'200 - 4'800 al mese lordi, 13 mensilita")
    assert result["currency"] == "CHF"
    assert result["period"] == "month"
    assert (result["min"], result["max"]) == (4200, 4800)
    assert result["basis"] == "gross"
    assert result["payments"] == 13


def test_hourly_pay_and_employment_percentage() -> None:
    result = extract_salary("Pensum 80%. Stipendio 28 CHF all'ora")
    assert result["period"] == "hour"
    assert result["min"] == 28
    assert result["employment_percent"] == 80


def test_net_amount_stays_marked_as_net() -> None:
    result = extract_salary("1.600 euro netti al mese")
    assert result["basis"] == "net"
    assert result["period"] == "month"


def test_k_suffix_range_uses_thousands_for_both_ends() -> None:
    result = extract_salary("Stipendio 35-45k euro annui")
    assert (result["min"], result["max"]) == (35000, 45000)
    assert result["period"] == "year"


def test_amount_without_period_is_ambiguous_and_not_interpreted() -> None:
    result = extract_salary("Stipendio di 2.500 euro")
    assert result["ambiguous"] is True
    assert "min" not in result


def test_implausible_amount_for_the_period_is_ambiguous() -> None:
    result = extract_salary("Compenso 90.000 euro al mese")
    assert result["ambiguous"] is True


def test_text_without_currency_returns_nothing() -> None:
    assert extract_salary("Cerchiamo 3 anni di esperienza e 2.000 candidati") is None
    assert extract_salary("") is None
