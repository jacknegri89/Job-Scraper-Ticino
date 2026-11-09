"""A title gets the field it really belongs to: words shared with software jobs do not mislead."""

import pytest

from job_filter import CATEGORY_OTHER, CATEGORY_TECH, CATEGORY_TECHNICAL, categorize_job


@pytest.mark.parametrize("title", [
    "Developer, Apparel",
    "Product Developer Off Price Intern",
    "Techn. product developer, swimwear/nightwear",
    "Business Developer",
    "Real Estate Developer",
    "Venditore IA - AI prodotti intelligenza generativa - Vendita applicazioni",
    "Sales Account Manager, AI solutions",
    "Recruiter IT",
])
def test_fashion_sales_and_property_titles_are_not_software(title: str) -> None:
    assert categorize_job(title) == CATEGORY_OTHER


@pytest.mark.parametrize("title", [
    "SVILUPPATORE PLC E HMI MACCHINE",
    "Programmatore PLC",
    "Tecnico PLC Siemens",
])
def test_plc_work_is_technical_not_software(title: str) -> None:
    assert categorize_job(title) == CATEGORY_TECHNICAL


@pytest.mark.parametrize("title", [
    "Software Developer",
    "Java Backend Developer",
    "Developer at Barclays PLC",
    "Data Scientist",
    "AI Engineer",
    "Sistemista Linux",
    "Help Desk IT",
    "DevOps Engineer",
])
def test_real_software_titles_stay_software(title: str) -> None:
    assert categorize_job(title) == CATEGORY_TECH


# ---- customer-service "help desk" roles are not IT support unless the description says so

from job_filter import category_awaits_description  # noqa: E402

CALL_CENTRE_TEXT = (
    "Gestione delle chiamate in entrata dei clienti, informazioni sui servizi e registrazione delle richieste. "
    "Orario su turni, contratto a tempo determinato."
)
IT_SUPPORT_TEXT = (
    "Supporto informatico di primo livello agli utenti: gestione ticketing, installazione di Windows e Microsoft 365, "
    "troubleshooting su hardware e VPN."
)


def test_a_customer_service_help_desk_title_is_other_by_default() -> None:
    assert categorize_job("Operatori Customer Service / Help Desk") == CATEGORY_OTHER
    assert categorize_job("Operatori Customer Service / Help Desk", CALL_CENTRE_TEXT) == CATEGORY_OTHER


def test_a_customer_service_help_desk_title_is_it_when_the_description_clearly_says_so() -> None:
    assert categorize_job("Operatori Customer Service / Help Desk", IT_SUPPORT_TEXT) == CATEGORY_TECH


def test_one_it_word_is_not_enough_to_call_a_call_centre_role_it_support() -> None:
    text = CALL_CENTRE_TEXT + " Registrazione dei ticket su un gestionale."

    assert categorize_job("Customer Care / Help Desk", text) == CATEGORY_OTHER


def test_plain_help_desk_titles_stay_it_without_a_description() -> None:
    assert categorize_job("Help Desk IT") == CATEGORY_TECH
    assert categorize_job("Tecnico Help Desk") == CATEGORY_TECH


def test_the_category_waits_for_the_description_only_when_it_can_still_change() -> None:
    assert category_awaits_description("Operatori Customer Service / Help Desk", "") is True
    assert category_awaits_description("Operatori Customer Service / Help Desk", CALL_CENTRE_TEXT) is False
    assert category_awaits_description("Help Desk IT", "") is False
    assert category_awaits_description("Cameriere", "") is False
