"""Seniority and contract classification: signals, conflicts and the unknown case."""

import pytest

from job_classifier import classify_contract, classify_seniority


@pytest.mark.parametrize("title, expected", [
    ("Junior Python Developer", "junior"),
    ("Sviluppatore Backend Senior", "senior"),
    ("Tech Lead Cloud", "senior"),
    ("Project Manager IT", "manager"),
    ("Responsabile Sistemi Informativi", "manager"),
    ("Middle Java Engineer", "mid"),
    ("Sistemista Linux", "unknown"),
    ("Stagista sviluppatore web", "junior"),
])
def test_title_signals(title, expected) -> None:
    assert classify_seniority(title)[0] == expected


def test_lead_as_a_noun_in_unrelated_words_is_not_senior() -> None:
    assert classify_seniority("Addetto Lead Generation")[0] == "unknown"


def test_conflicting_title_words_stay_unknown() -> None:
    level, evidence = classify_seniority("Junior / Senior Developer")
    assert level == "unknown"
    assert evidence


def test_years_of_experience_decide_only_when_the_title_is_silent() -> None:
    assert classify_seniority("Sviluppatore PHP", "Richiesti almeno 6 anni di esperienza")[0] == "senior"
    assert classify_seniority("Sviluppatore PHP", "Cerchiamo 3 anni di esperienza")[0] == "mid"
    assert classify_seniority("Sviluppatore PHP", "1 anno di esperienza")[0] == "unknown"
    assert classify_seniority("Junior Developer", "5 anni di esperienza")[0] == "junior"


def test_evidence_explains_the_decision() -> None:
    assert "senior" in classify_seniority("Senior DevOps")[1].lower()
    assert classify_seniority("Sistemista")[1] == ""


@pytest.mark.parametrize("text, expected", [
    ("Contratto a tempo indeterminato", "permanent"),
    ("Contratto a tempo determinato di 12 mesi", "fixed_term"),
    ("Offerta di stage curriculare", "internship"),
    ("Apprendistato professionalizzante", "apprenticeship"),
    ("Assunzione tramite somministrazione", "temp_agency"),
    ("Collaborazione con partita IVA", "freelance"),
    ("Sviluppatore Python", "unknown"),
])
def test_contract_type_from_text(text, expected) -> None:
    assert classify_contract("Sviluppatore", text) == expected
