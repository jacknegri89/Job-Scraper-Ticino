from html_generator import build_card, generate_html

SAMPLE_JOB = {
    "title": "Tecnico IT Junior",
    "company": "Manpower SA",
    "city": "Chiasso",
    "date": "2026-06-09",
    "url": "https://www.jobs.ch/en/vacancies/detail/abc/",
    "category": "tech",
    "source": "jobs.ch",
}


def test_build_card_contains_title():
    assert "Tecnico IT Junior" in build_card(SAMPLE_JOB)


def test_build_card_contains_company():
    assert "Manpower SA" in build_card(SAMPLE_JOB)


def test_build_card_contains_city():
    card = build_card(SAMPLE_JOB)
    assert "SVIZZERA" in card
    assert "Chiasso" in card


def test_build_card_has_apply_link():
    card = build_card(SAMPLE_JOB)
    assert 'href="https://www.jobs.ch/en/vacancies/detail/abc/"' in card
    assert 'target="_blank"' in card


def test_build_card_has_category_attribute():
    assert 'data-category="tech"' in build_card(SAMPLE_JOB)


def test_build_card_escapes_html():
    job = {**SAMPLE_JOB, "title": '<script>alert("xss")</script>'}
    card = build_card(job)
    assert "<script>" not in card
    assert "&lt;script&gt;" in card


def test_generate_html_creates_file(tmp_path):
    out = tmp_path / "index.html"
    generate_html([SAMPLE_JOB], output_path=str(out))
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "Tecnico IT Junior" in content
    assert "tailwindcss" in content


def test_generate_html_empty_state(tmp_path):
    out = tmp_path / "index.html"
    generate_html([], output_path=str(out))
    assert "Nessun annuncio" in out.read_text(encoding="utf-8")


def test_generate_html_shows_count(tmp_path):
    out = tmp_path / "index.html"
    generate_html([SAMPLE_JOB], output_path=str(out))
    content = out.read_text(encoding="utf-8")
    assert "1 annunci" in content or "1 annuncio" in content
