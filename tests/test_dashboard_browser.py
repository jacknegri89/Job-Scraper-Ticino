"""The generated dashboard in a real Chromium: the translate buttons, hostile and very long text.

It needs the Playwright browser (python -m playwright install chromium) and is skipped when it
is not installed. Nothing here touches the internet: Google Translate is never really opened.
"""

import time
from pathlib import Path

import pytest

import dashboard_builder

sync_api = pytest.importorskip("playwright.sync_api")

ENGLISH_TEXT = (
    "We are looking for a developer with experience in the cloud, and you will work with our team on the platform. "
    "You will build services for our customers and the team."
)
GERMAN_TEXT = (
    "Wir suchen eine Entwicklerin mit Erfahrung in der Cloud und Kenntnisse im Team für unsere Aufgaben, "
    "die mit uns und unseren Kunden arbeitet."
)
FRENCH_TEXT = (
    "Nous recherchons une personne avec de l'expérience dans le cloud pour notre équipe et les missions "
    "du poste dans une entreprise."
)
ITALIAN_TEXT = (
    "Cerchiamo una persona con esperienza nello sviluppo di applicazioni per la nostra azienda, che lavori con il "
    "team e con i clienti."
)

# Records what the page does with the translator and with window.open, before the page's own script runs.
RECORDER = """
window.__opened = [];
window.open = (address) => { window.__opened.push(String(address)); return null; };
window.__injected = false;
"""


def _job(title: str, description: str, **extra: object) -> dict:
    job = {"title": title, "company": "Rossi SA", "city": "Chiasso", "date": "2026-11-05", "category": "tech",
           "url": "https://www.jobs.ch/it/annuncio/" + str(abs(hash(title)) % 10000), "source": "jobs.ch",
           "description": description}
    job.update(extra)
    return job


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        try:
            chromium = playwright.chromium.launch()
        except Exception as error:
            pytest.skip(f"Chromium is not installed: {type(error).__name__}")
        yield chromium
        chromium.close()


def _open_dashboard(browser, tmp_path: Path, jobs: list[dict], init_script: str = "", width: int = 1280):
    output = tmp_path / "index.html"
    dashboard_builder.generate_html(jobs, output)
    context = browser.new_context(viewport={"width": width, "height": 900})
    page = context.new_page()
    problems: list[str] = []
    page.on("pageerror", lambda error: problems.append(f"pageerror: {error}"))
    page.on("console", lambda message: problems.append(f"{message.type}: {message.text}")
            if message.type == "error" else None)
    page.add_init_script(RECORDER + init_script)
    page.goto(output.as_uri())
    return context, page, problems


def _first_paragraph(page) -> str:
    return page.inner_text(".desc-text p")


def _note(page) -> str:
    return page.inner_text(".desc-note")


def _wait_for_note(page, expected_part: str, timeout_seconds: float = 8.0) -> None:
    """Poll the status text; the page's CSP forbids eval, so wait_for_function cannot be used."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if expected_part in _note(page):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"the note never said {expected_part!r}; it says {_note(page)!r}")


WORKING_TRANSLATOR = """
window.Translator = {
  availability: async () => "available",
  create: async () => ({ translate: async (text) => "[IT] " + text }),
};
"""


def test_a_browser_without_a_translator_keeps_the_text_and_never_opens_google_by_itself(browser, tmp_path) -> None:
    context, page, problems = _open_dashboard(browser, tmp_path, [_job("Developer", ENGLISH_TEXT)],
                                              "delete window.Translator;")
    original = _first_paragraph(page)

    page.click('[data-action="translate"]')
    _wait_for_note(page, "cannot translate")

    assert _first_paragraph(page) == original
    assert page.evaluate("window.__opened.length") == 0, "Google must not be opened by the first button"
    assert page.is_visible('[data-action="translate-online"]')
    assert "send the text to Google Translate" in _note(page).replace("You can ", "").lower() or "Google" in _note(page)
    assert "Translated" not in _note(page)
    assert problems == []
    context.close()


def test_a_translator_that_never_answers_gives_up_and_keeps_the_text(browser, tmp_path) -> None:
    never = "window.Translator = { availability: () => new Promise(() => {}), create: () => new Promise(() => {}) };"
    context, page, _problems = _open_dashboard(browser, tmp_path, [_job("Developer", ENGLISH_TEXT)], never)
    original = _first_paragraph(page)

    page.click('[data-action="translate"]')
    _wait_for_note(page, "cannot translate")

    assert _first_paragraph(page) == original
    assert page.is_enabled('[data-action="translate"]'), "the button must work again after a timeout"
    assert page.evaluate("window.__opened.length") == 0
    context.close()


def test_a_translator_that_is_unavailable_for_the_language_keeps_the_text(browser, tmp_path) -> None:
    unavailable = 'window.Translator = { availability: async () => "unavailable", create: async () => { throw new Error("no"); } };'
    context, page, _problems = _open_dashboard(browser, tmp_path, [_job("Developer", ENGLISH_TEXT)], unavailable)
    original = _first_paragraph(page)

    page.click('[data-action="translate"]')
    _wait_for_note(page, "cannot translate")

    assert _first_paragraph(page) == original
    assert page.is_visible('[data-action="translate-online"]')
    context.close()


def test_a_translation_that_fails_halfway_puts_the_whole_original_back(browser, tmp_path) -> None:
    text = " | ".join([ENGLISH_TEXT, ENGLISH_TEXT.replace("developer", "tester"), ENGLISH_TEXT.replace("developer", "designer")])
    failing = """
    let calls = 0;
    window.Translator = { availability: async () => "available", create: async () => ({
      translate: async (text) => { calls++; if (calls === 2) { throw new Error("boom"); } return "[IT] " + text; }
    }) };
    """
    context, page, _problems = _open_dashboard(browser, tmp_path, [_job("Developer", text)], failing)
    originals = page.eval_on_selector_all(".desc-text p", "paragraphs => paragraphs.map(p => p.textContent)")

    page.click('[data-action="translate"]')
    _wait_for_note(page, "did not work")

    assert page.eval_on_selector_all(".desc-text p", "paragraphs => paragraphs.map(p => p.textContent)") == originals
    assert "Translated" not in _note(page)
    assert page.inner_text('[data-action="translate"]') == "Translate to Italian"
    assert page.is_visible('[data-action="translate-online"]')
    context.close()


def test_a_translator_that_returns_the_same_text_is_not_reported_as_a_translation(browser, tmp_path) -> None:
    echo = 'window.Translator = { availability: async () => "available", create: async () => ({ translate: async (t) => t }) };'
    context, page, _problems = _open_dashboard(browser, tmp_path, [_job("Developer", ENGLISH_TEXT)], echo)

    page.click('[data-action="translate"]')
    _wait_for_note(page, "did not work")

    assert "Translated" not in _note(page)
    assert page.evaluate("document.querySelector('.desc').dataset.translated || ''") != "yes"
    context.close()


def test_an_empty_translation_is_a_failure(browser, tmp_path) -> None:
    empty = 'window.Translator = { availability: async () => "available", create: async () => ({ translate: async () => "  " }) };'
    context, page, _problems = _open_dashboard(browser, tmp_path, [_job("Developer", ENGLISH_TEXT)], empty)
    original = _first_paragraph(page)

    page.click('[data-action="translate"]')
    _wait_for_note(page, "did not work")

    assert _first_paragraph(page) == original
    context.close()


def test_a_working_translator_translates_on_the_device_and_can_go_back(browser, tmp_path) -> None:
    context, page, problems = _open_dashboard(browser, tmp_path, [_job("Developer", ENGLISH_TEXT)], WORKING_TRANSLATOR)
    original = _first_paragraph(page)

    page.click('[data-action="translate"]')
    _wait_for_note(page, "Translated")

    assert _first_paragraph(page) == "[IT] " + original
    assert page.get_attribute(".desc-text", "lang") == "it"
    assert page.evaluate("window.__opened.length") == 0, "nothing leaves the page when the browser translates"
    assert not page.is_visible('[data-action="translate-online"]')

    page.click('[data-action="translate"]')

    assert _first_paragraph(page) == original
    assert page.get_attribute(".desc-text", "lang") == "en"
    assert _note(page) == ""
    assert problems == []
    context.close()


def test_google_translate_opens_only_from_its_own_button_and_the_page_says_the_text_is_sent(browser, tmp_path) -> None:
    context, page, _problems = _open_dashboard(browser, tmp_path, [_job("Developer", ENGLISH_TEXT)], "delete window.Translator;")

    page.click('[data-action="translate"]')
    _wait_for_note(page, "cannot translate")
    assert page.evaluate("window.__opened.length") == 0

    page.click('[data-action="translate-online"]')

    opened = page.evaluate("window.__opened")
    assert len(opened) == 1
    assert opened[0].startswith("https://translate.google.com/?sl=en&tl=it&text=")
    assert "We%20are%20looking%20for%20a%20developer" in opened[0]
    assert "sent the text to google translate" in _note(page).lower()
    assert "send the text to google translate" in page.inner_text('[data-action="translate-online"]').lower()
    context.close()


def test_a_very_long_text_is_cut_for_google_at_a_whole_word_and_the_note_says_so(browser, tmp_path) -> None:
    long_text = " | ".join(f"Paragraph {number}: {ENGLISH_TEXT}" for number in range(60))
    context, page, _problems = _open_dashboard(browser, tmp_path, [_job("Developer", long_text)], "delete window.Translator;")

    page.click('[data-action="translate"]')
    _wait_for_note(page, "cannot translate")
    page.click('[data-action="translate-online"]')

    address = page.evaluate("window.__opened[0]")
    assert len(address) < 3700
    assert not address.endswith("%")
    assert "start of the text" in _note(page)
    context.close()


def test_the_translate_button_follows_the_language_of_each_listing(browser, tmp_path) -> None:
    jobs = [_job("Developer one", ENGLISH_TEXT), _job("Entwickler zwei", GERMAN_TEXT),
            _job("Developpeur trois", FRENCH_TEXT), _job("Sviluppatore quattro", ITALIAN_TEXT)]
    context, page, _problems = _open_dashboard(browser, tmp_path, jobs)

    sources = page.eval_on_selector_all('[data-action="translate"]', "buttons => buttons.map(b => b.dataset.from).sort()")

    assert sources == ["de", "en", "fr"]
    assert page.eval_on_selector_all(".desc", "descriptions => descriptions.filter(d => d.dataset.lang === 'it').length") == 1
    context.close()


# ---- hostile, special and very long content

HOSTILE_TEXT = " | ".join([
    '<img src=x onerror="window.__injected=true"> ' + ENGLISH_TEXT,
    "</script><script>window.__injected = true</script> and the rest of the sentence for the team.",
    "<b>bold</b> &amp; &lt;i&gt; \"quotes\" 'single' `tick` ${template} {{braces}} %s %d \\ backslash",
    "Emoji \U0001F680\U0001F468‍\U0001F4BB, CJK 中文编程工程师, Arabic مطور برمجيات, accents àèìòùüßç, combining é.",
    "javascript:alert(1) and data:text/html,<script>window.__injected=true</script>",
])
UNBREAKABLE = "A" * 3000 + "https://example.com/" + "b" * 2000


@pytest.mark.parametrize("width", [375, 1280])
def test_hostile_special_and_very_long_text_is_shown_as_text_and_never_breaks_the_layout(browser, tmp_path, width) -> None:
    jobs = [
        _job("<script>window.__injected=true</script> Title " + "Long " * 60, HOSTILE_TEXT,
             company='<img src=x onerror="window.__injected=true">'),
        _job("Unbreakable text", UNBREAKABLE + " | " + ENGLISH_TEXT),
        _job("Very long listing", " | ".join(f"Paragraph {number}: {ENGLISH_TEXT}" for number in range(60))),
    ]
    context, page, problems = _open_dashboard(browser, tmp_path, jobs, width=width)

    assert page.evaluate("window.__injected") is False, "text from a portal must never run as code"
    assert page.evaluate("document.querySelectorAll('.card img, .desc img, .card-main script').length") == 0
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no horizontal scroll"
    assert page.evaluate("[...document.querySelectorAll('.card')].every(c => c.scrollWidth <= c.clientWidth + 1)")
    shown = page.inner_text(".desc-text")
    assert "<img src=x" in shown and "</script><script>" in shown, "markup is displayed as text"
    assert "中文" in shown and "مطور" in shown and "\U0001F680" in shown
    assert problems == [], problems
    context.close()


def test_a_very_long_listing_is_shortened_and_can_be_opened_and_closed(browser, tmp_path) -> None:
    text = " | ".join(f"Paragraph {number}: {ENGLISH_TEXT}" for number in range(60))
    context, page, _problems = _open_dashboard(browser, tmp_path, [_job("Very long listing", text)])
    closed_height = page.evaluate("document.querySelector('.desc-text').getBoundingClientRect().height")

    page.click('[data-action="expand"]')
    open_height = page.evaluate("document.querySelector('.desc-text').getBoundingClientRect().height")
    assert open_height > closed_height * 5
    assert page.get_attribute('[data-action="expand"]', "aria-expanded") == "true"

    page.click('[data-action="expand"]')
    assert page.evaluate("document.querySelector('.desc-text').getBoundingClientRect().height") == closed_height
    context.close()
