from filters import normalize_city, normalize_url, is_valid_job, filter_jobs, categorize_job


def test_normalize_city_simple():
    assert normalize_city("Chiasso") == "chiasso"


def test_normalize_city_with_prefix():
    assert normalize_city("CHE - Chiasso") == "chiasso"


def test_normalize_city_strips_whitespace():
    assert normalize_city("  Mendrisio  ") == "mendrisio"


def test_normalize_url_removes_utm():
    url = "https://www.jobs.ch/en/vacancies/detail/abc/?utm_source=google&utm_medium=cpc"
    clean = normalize_url(url)
    assert "utm_source" not in clean
    assert "utm_medium" not in clean
    assert "abc" in clean


def test_normalize_url_keeps_important_params():
    url = "https://www.jobs.ch/en/vacancies/detail/abc/?term=test"
    assert "term=test" in normalize_url(url)


def test_is_valid_job_accepts_whitelist_city():
    job = {"city": "Chiasso", "url": "https://www.jobs.ch/en/vacancies/detail/abc/"}
    assert is_valid_job(job) is True


def test_is_valid_job_rejects_italian_url():
    job = {"city": "Chiasso", "url": "https://www.lavoro.it/annuncio/123"}
    assert is_valid_job(job) is False


def test_is_valid_job_rejects_non_whitelist_city():
    job = {"city": "Lugano", "url": "https://www.jobs.ch/en/vacancies/detail/abc/"}
    assert is_valid_job(job) is False


def test_is_valid_job_accepts_prefix_city():
    job = {"city": "CHE - Mendrisio", "url": "https://www.jobs.ch/en/vacancies/detail/abc/"}
    assert is_valid_job(job) is True


def test_filter_jobs_deduplicates():
    jobs = [
        {"title": "A", "company": "X", "city": "Chiasso", "date": "2026-06-09",
         "url": "https://jobs.ch/en/vacancies/detail/abc/?utm_source=a", "category": "tech", "source": "jobs.ch"},
        {"title": "A", "company": "X", "city": "Chiasso", "date": "2026-06-09",
         "url": "https://jobs.ch/en/vacancies/detail/abc/?utm_source=b", "category": "tech", "source": "carriera.ch"},
    ]
    assert len(filter_jobs(jobs)) == 1


def test_filter_jobs_excludes_invalid_city():
    jobs = [
        {"title": "A", "company": "X", "city": "Lugano", "date": "2026-06-09",
         "url": "https://jobs.ch/en/vacancies/detail/xyz/", "category": "tech", "source": "jobs.ch"},
    ]
    assert filter_jobs(jobs) == []


def test_filter_jobs_sorts_by_date_desc():
    jobs = [
        {"title": "A", "company": "X", "city": "Chiasso", "date": "2026-06-01",
         "url": "https://jobs.ch/en/vacancies/detail/a/", "category": "tech", "source": "jobs.ch"},
        {"title": "B", "company": "Y", "city": "Chiasso", "date": "2026-06-09",
         "url": "https://jobs.ch/en/vacancies/detail/b/", "category": "tech", "source": "jobs.ch"},
    ]
    result = filter_jobs(jobs)
    assert result[0]["title"] == "B"


def test_categorize_job_tech():
    assert categorize_job("Junior IT Support Specialist") == "tech"


def test_categorize_job_logistica():
    assert categorize_job("Addetto logistica part-time") == "logistica"


def test_categorize_job_unknown():
    assert categorize_job("Responsabile contabile") == "altro"
