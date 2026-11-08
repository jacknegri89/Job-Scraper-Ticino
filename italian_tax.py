"""Italian income tax rules shared by the Italian and the cross-border estimates.

These are indicative parameters, not tax advice. They are kept in one place so the
tax year and every assumption is explicit and easy to update.

Sources used to set the values (secondary sources, not the Agenzia delle Entrate):
IRPEF brackets 2026 after the 2026 budget law (second bracket 33%), and the
employee deduction of art. 13 TUIR. Check the official texts before relying on them.
"""

TAX_YEAR = 2026

# Annual IRPEF brackets as (upper limit in EUR, rate). The last bracket has no limit.
IRPEF_BRACKETS = (
    (28_000.0, 0.23),
    (50_000.0, 0.33),
    (None, 0.43),
)

# Employee share of INPS contributions for a standard private-sector contract.
INPS_EMPLOYEE_RATE = 0.0919

# Employee deduction (art. 13 TUIR): thresholds and fixed amounts.
DEDUCTION_LOW_INCOME_LIMIT = 15_000.0
DEDUCTION_MIDDLE_INCOME_LIMIT = 28_000.0
DEDUCTION_HIGH_INCOME_LIMIT = 50_000.0
DEDUCTION_LOW_INCOME_AMOUNT = 1_955.0
DEDUCTION_BASE_AMOUNT = 1_910.0
DEDUCTION_MIDDLE_EXTRA_AMOUNT = 1_190.0

NOT_INCLUDED = (
    "regional and municipal surcharges",
    "the 2025-2026 payroll tax-cut bonuses",
    "family deductions",
    "collective-agreement extras",
)


def annual_irpef(taxable_income_eur: float) -> float:
    """Gross IRPEF on a taxable income, before deductions."""
    if taxable_income_eur <= 0:
        return 0.0
    total_tax = 0.0
    lower_limit = 0.0
    for upper_limit, rate in IRPEF_BRACKETS:
        if upper_limit is None:
            total_tax += (taxable_income_eur - lower_limit) * rate
            return total_tax
        if taxable_income_eur <= upper_limit:
            total_tax += (taxable_income_eur - lower_limit) * rate
            return total_tax
        total_tax += (upper_limit - lower_limit) * rate
        lower_limit = upper_limit
    return total_tax


def employee_deduction(income_eur: float) -> float:
    """Deduction for employees (art. 13 TUIR), decreasing as income grows."""
    if income_eur <= 0:
        return 0.0
    if income_eur <= DEDUCTION_LOW_INCOME_LIMIT:
        return DEDUCTION_LOW_INCOME_AMOUNT
    if income_eur <= DEDUCTION_MIDDLE_INCOME_LIMIT:
        bracket_width = DEDUCTION_MIDDLE_INCOME_LIMIT - DEDUCTION_LOW_INCOME_LIMIT
        share_left = (DEDUCTION_MIDDLE_INCOME_LIMIT - income_eur) / bracket_width
        return DEDUCTION_BASE_AMOUNT + DEDUCTION_MIDDLE_EXTRA_AMOUNT * share_left
    if income_eur <= DEDUCTION_HIGH_INCOME_LIMIT:
        bracket_width = DEDUCTION_HIGH_INCOME_LIMIT - DEDUCTION_MIDDLE_INCOME_LIMIT
        share_left = (DEDUCTION_HIGH_INCOME_LIMIT - income_eur) / bracket_width
        return DEDUCTION_BASE_AMOUNT * share_left
    return 0.0
