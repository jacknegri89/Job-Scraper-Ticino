"""Estimate monthly net pay for a new Italian cross-border worker in Ticino."""

CHF_EUR_RATE = 0.96
ITALIAN_TAX_FREE_CHF = 10_000


def calculate_net_salary(gross_chf: float | int | None) -> dict[str, int]:
    """Return a rough monthly net salary estimate from a gross CHF amount."""
    if gross_chf is None or gross_chf <= 0:
        return {}

    gross_value = float(gross_chf)
    social_chf = _swiss_social_contributions(gross_value)
    withholding_chf = _monthly_withholding_tax(gross_value, social_chf)
    net_before_italy_chf = gross_value - social_chf - withholding_chf
    extra_italian_tax_eur = _monthly_italian_tax(gross_value, withholding_chf)
    final_net_chf = net_before_italy_chf - (extra_italian_tax_eur / CHF_EUR_RATE)

    return _salary_result(
        gross_value,
        social_chf,
        withholding_chf,
        extra_italian_tax_eur,
        final_net_chf,
    )


def _swiss_social_contributions(gross_chf: float) -> float:
    return gross_chf * 0.0955


def _monthly_withholding_tax(gross_chf: float, social_chf: float) -> float:
    taxable_chf = gross_chf - social_chf
    return taxable_chf * _withholding_tax_rate(gross_chf * 12)


def _withholding_tax_rate(annual_gross_chf: float) -> float:
    brackets = [
        (18_000, 0.030), (21_000, 0.045), (24_000, 0.060),
        (27_000, 0.075), (30_000, 0.090), (35_000, 0.100),
        (40_000, 0.110), (45_000, 0.115), (50_000, 0.120),
        (60_000, 0.130), (80_000, 0.145), (100_000, 0.155),
    ]
    for threshold, rate in brackets:
        if annual_gross_chf <= threshold:
            return rate
    return 0.170


def _monthly_italian_tax(gross_chf: float, withholding_chf: float) -> float:
    annual_gross_chf = gross_chf * 12
    taxable_chf = max(0.0, annual_gross_chf - ITALIAN_TAX_FREE_CHF)
    taxable_eur = taxable_chf * CHF_EUR_RATE
    if taxable_eur <= 0:
        return 0.0

    gross_tax_eur = _annual_irpef(taxable_eur)
    employee_deduction_eur = _employee_deduction(annual_gross_chf)
    net_tax_eur = max(0.0, gross_tax_eur - employee_deduction_eur)
    tax_credit_eur = _withholding_tax_credit(withholding_chf, taxable_chf, annual_gross_chf)
    return max(0.0, net_tax_eur - tax_credit_eur) / 12


def _annual_irpef(taxable_eur: float) -> float:
    if taxable_eur <= 28_000:
        return taxable_eur * 0.23
    if taxable_eur <= 50_000:
        return 6_440 + (taxable_eur - 28_000) * 0.35
    return 14_140 + (taxable_eur - 50_000) * 0.43


def _employee_deduction(annual_gross_chf: float) -> float:
    income_eur = annual_gross_chf * CHF_EUR_RATE
    if income_eur <= 15_000:
        return 1_880.0
    if income_eur <= 28_000:
        return 1_910 - (income_eur - 15_000) * 720 / 13_000
    if income_eur <= 50_000:
        return 1_190 - (income_eur - 28_000) * 1_190 / 22_000
    return 0.0


def _withholding_tax_credit(
    withholding_chf: float,
    taxable_chf: float,
    annual_gross_chf: float,
) -> float:
    taxable_share = taxable_chf / annual_gross_chf if annual_gross_chf else 0
    return (withholding_chf * 12) * CHF_EUR_RATE * taxable_share


def _salary_result(
    gross_chf: float,
    social_chf: float,
    withholding_chf: float,
    extra_italian_tax_eur: float,
    final_net_chf: float,
) -> dict[str, int]:
    return {
        "gross_chf": int(gross_chf),
        "social_chf": int(round(social_chf)),
        "withholding_chf": int(round(withholding_chf)),
        "extra_italian_tax_eur": int(round(extra_italian_tax_eur)),
        "net_chf": int(round(final_net_chf)),
        "net_eur": int(round(final_net_chf * CHF_EUR_RATE)),
    }
