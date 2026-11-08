"""Tests for the filtering pipeline: area, preferences, duplicates and categories."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import geo
from geo import AreaPolicy
from job_filter import categorize_job, is_safe_job_url, normalize_url, sort_date
from job_model import normalize_job, source_country
from job_pipeline import process_jobs
from preferences import SearchPreferences


def _job(**extra: object) -> dict:
    base = {
        "title": "Sviluppatore Python",
        "company": "ACME SA",
        "city": "Chiasso",
        "date": "2026-06-10",
        "url": "https://example.ch/job/1",
        "source": "jobs.ch",
    }
    base.update(extra)
    return base


def _seveso() -> tuple[float, float]:
    place = geo.find_place("Seveso").place
    return place.lat, place.lng


def _preferences(**changes: object) -> SearchPreferences:
    settings = {"area": AreaPolicy(radius_km=30, home=_seveso())}
    settings.update(changes)
    return SearchPreferences(**settings)


def _kept(jobs: list[dict], preferences: SearchPreferences | None = None) -> list[dict]:
    return process_jobs(jobs, preferences or _preferences()).jobs


def test_safe_urls() -> None:
    assert is_safe_job_url("https://example.ch/job/1") is True
    assert is_safe_job_url("javascript:alert(1)") is False
    assert is_safe_job_url("https://user@example.ch/job/1") is False
    assert is_safe_job_url("ftp://example.ch/job") is False
    assert is_safe_job_url(None) is False


def test_italian_portal_jobs_are_kept_when_the_place_is_in_the_area() -> None:
    job = _job(url="https://www.subito.it/annuncio/5", source="subito.it", city="Milano MI")
    assert len(_kept([job])) == 1


def test_out_of_area_and_unknown_places_are_excluded_with_a_reason() -> None:
    far = _job(city="Lugano", url="https://example.ch/job/2")
    unclear = _job(city="Lombardia", url="https://example.ch/job/3")
    result = process_jobs([far, unclear, _job()], _preferences())
    assert len(result.jobs) == 1
    excluded = result.stats["jobs.ch"].excluded
    assert excluded["out_of_area"] == 1
    assert excluded["uncertain_location"] == 1


def test_uncertain_locations_can_be_included_and_stay_marked() -> None:
    unclear = _job(city="Lombardia", url="https://example.ch/job/3")
    kept = _kept([unclear], _preferences(include_uncertain_location=True))
    assert len(kept) == 1
    assert kept[0]["location_certainty"] == "region_only"
    assert kept[0]["area_status"] == "uncertain"


def test_invalid_job_urls_are_excluded() -> None:
    result = process_jobs([_job(url="javascript:alert(1)")], _preferences())
    assert result.jobs == []
    assert result.stats["jobs.ch"].excluded["invalid_url"] == 1


def test_senior_listings_are_kept_unless_the_user_excludes_that_level() -> None:
    senior = _job(title="Senior Python Developer", url="https://example.ch/job/4")
    assert len(_kept([senior])) == 1
    only_junior = _preferences(seniority_levels=frozenset({"junior", "unknown"}))
    assert _kept([senior], only_junior) == []


def test_category_and_contract_preferences() -> None:
    waiter = _job(title="Cameriere di sala", url="https://example.ch/job/5")
    internship = _job(title="Stage sviluppatore", url="https://example.ch/job/6")
    only_tech = _preferences(categories=frozenset({"tech"}))
    assert _kept([waiter], only_tech) == []
    no_internships = _preferences(contract_types=frozenset({"permanent", "unknown"}))
    assert _kept([internship], no_internships) == []


def test_identical_url_is_deduplicated_and_counted() -> None:
    result = process_jobs([_job(), _job(title="Sviluppatore Python copy")], _preferences())
    assert len(result.jobs) == 1
    assert result.stats["jobs.ch"].duplicates == 1


def test_same_job_on_two_portals_is_merged_and_keeps_both_links() -> None:
    first = _job(url="https://www.jobs.ch/job/1")
    second = _job(url="https://www.jobscout24.ch/job/9", source="jobscout24.ch")
    kept = _kept([first, second])
    assert len(kept) == 1
    assert {reference["source"] for reference in kept[0]["sources"]} == {"jobs.ch", "jobscout24.ch"}


def test_merge_does_not_depend_on_input_order() -> None:
    first = _job(url="https://www.jobs.ch/job/1")
    second = _job(url="https://www.jobscout24.ch/job/9", source="jobscout24.ch")
    forward = _kept([first, second])[0]
    backward = _kept([second, first])[0]
    assert forward["url"] == backward["url"]
    assert forward["sources"] == backward["sources"]


def test_same_title_and_company_on_the_same_portal_stay_separate() -> None:
    first = _job(url="https://www.jobs.ch/job/1")
    second = _job(url="https://www.jobs.ch/job/2")
    assert len(_kept([first, second])) == 2


def test_similar_titles_at_different_companies_or_places_are_not_merged() -> None:
    first = _job(url="https://www.jobs.ch/job/1")
    other_company = _job(url="https://www.jobscout24.ch/job/9", source="jobscout24.ch", company="Other SA")
    other_place = _job(url="https://www.indeed.ch/job/7", source="indeed.ch", city="Mendrisio")
    assert len(_kept([first, other_company, other_place])) == 3


def test_jobs_without_company_and_agency_jobs_are_not_merged_by_content() -> None:
    no_company_a = _job(company="", url="https://www.jobs.ch/job/1")
    no_company_b = _job(company="", url="https://www.jobscout24.ch/job/2", source="jobscout24.ch")
    agency_a = _job(source="randstad.ch", company="Randstad SA", url="https://www.randstad.ch/it/lavoro/a_1111/")
    agency_b = _job(source="adecco.ch", company="Randstad SA", url="https://www.adecco.com/it-ch/b_2222")
    assert len(_kept([no_company_a, no_company_b])) == 2
    assert len(_kept([agency_a, agency_b])) == 2


def test_jobs_are_sorted_by_newest_date_first_when_merging_ties() -> None:
    old_job = _job(title="Sviluppatore Java", date="2026-05-01", url="https://x.ch/1")
    new_job = _job(title="Sviluppatore PHP", date="2026-06-12", url="https://x.ch/2", company="B SA")
    eu_date_job = _job(title="Sviluppatore Go", date="11.06.2026", url="https://x.ch/3", company="C SA")
    result = _kept([old_job, new_job, eu_date_job])
    assert [job["published"] for job in result] == ["2026-06-12", "2026-06-11", "2026-05-01"]


def test_unknown_date_is_not_invented() -> None:
    assert normalize_job(_job(date="3 giorni fa"))["published"] == ""
    assert sort_date("3 giorni fa") == ""


def test_tracking_parameters_do_not_change_normalized_url() -> None:
    clean_url = normalize_url("https://x.ch/job?id=5")
    tracked_url = normalize_url("https://x.ch/job?id=5&utm_source=feed&utm_medium=x&gclid=abc#top")
    assert clean_url == tracked_url
    assert normalize_url("HTTPS://X.ch:443/job/") == normalize_url("https://x.ch/job")


def test_normalized_job_has_country_region_and_source_references() -> None:
    swiss = normalize_job(_job())
    italian = normalize_job(_job(city="Monza MB", source="indeed.it", url="https://it.indeed.com/x"))
    assert (swiss["country"], swiss["region"]) == ("CH", "TI")
    assert (italian["country"], italian["region"], italian["province"]) == ("IT", "LOM", "MB")
    assert swiss["sources"] == [{"source": "jobs.ch", "url": "https://example.ch/job/1"}]
    assert source_country("indeed.it") == "IT"
    assert source_country("frontaliereticino.ch") == "CH"


def test_category_from_title() -> None:
    assert categorize_job("Magazziniere turno notte") == "logistics"
    assert categorize_job("Elettricista AFC") == "technical"
    assert categorize_job("Cameriere di sala") == "food_service"
    assert categorize_job("Tornitore CNC Fanuc") == "production"
    assert categorize_job("Meccanico manutentore di autoveicoli") == "production"
    assert categorize_job("Direttore generale") == "other"


def test_software_and_ai_titles_are_tech_without_false_positives() -> None:
    assert categorize_job("Sviluppatore Backend Python") == "tech"
    assert categorize_job("Sistemista Linux") == "tech"
    assert categorize_job("AI Engineer") == "tech"
    assert categorize_job("Machine Learning Engineer") == "tech"
    assert categorize_job("Assistant Manager") == "other"
    assert categorize_job("Business Developer") == "other"
