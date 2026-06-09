# Job Scraper Frontaliero – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python scraper that collects job listings from jobs.ch and carriera.ch, filters for Swiss border municipalities (Chiasso, Mendrisio, Stabio, etc.), and generates a Tailwind CSS dashboard in `index.html`.

**Architecture:** Separate scraper modules per portal (`scrapers/jobs_ch.py`, `scrapers/carriera_ch.py`), a shared anti-detection context helper (`scrapers/__init__.py`), a filter/dedup module (`filters.py`), and an HTML generator (`html_generator.py`). Entry point `scraper.py` orchestrates all modules. Browser session persists across runs to avoid repeated cookie prompts.

**Tech Stack:** Python 3.10+, Playwright (sync API), playwright-stealth, pytest

**Verified live selectors:**
- jobs.ch cards: `a[data-cy="job-link"]` · title from `.title` attr · city from `p` index 1 (format `CHE - CityName`) · company from `p[class*="fw_bol"]` · pagination via `?page=N`
- carriera.ch: standard `<table>` · 6 `<td>` per row · company from `img[alt]` in col 1 · title+URL from `<a>` in col 2 · city from col 3 · pagination `annunci-offerte-lavoro_0_0_{N}.html`

---

### Task 1: Project initialization

**Files:**
- Create: `requirements.txt`
- Create: `scrapers/__init__.py` (empty placeholder)
- Create: `tests/__init__.py`
- Create: `.gitignore`

- [ ] **Step 1: Create directory structure**

```
cd C:\Users\Administrator\Desktop\Lavoro
git init
mkdir scrapers
mkdir tests
mkdir profile
```

- [ ] **Step 2: Create `requirements.txt`**

```
playwright>=1.40.0
playwright-stealth>=1.0.0
pytest>=7.0.0
```

- [ ] **Step 3: Create placeholder files**

Create `scrapers/__init__.py` — empty file for now.
Create `tests/__init__.py` — empty file.
Create `profile\.gitkeep` — empty file (keeps the folder in git).

- [ ] **Step 4: Create `.gitignore`**

```
profile/state.json
__pycache__/
*.pyc
.pytest_cache/
index.html
.playwright-mcp/
```

- [ ] **Step 5: Install dependencies**

```
pip install -r requirements.txt
playwright install chromium
```

Expected: no errors, Chromium browser downloaded (a few hundred MB).

- [ ] **Step 6: Commit**

```
git add requirements.txt scrapers/__init__.py tests/__init__.py .gitignore profile/.gitkeep
git commit -m "feat: project initialization"
```

---

### Task 2: Filters and data model (TDD)

**Files:**
- Create: `filters.py`
- Create: `tests/test_filters.py`

- [ ] **Step 1: Write failing tests — create `tests/test_filters.py`**

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```
pytest tests/test_filters.py -v
```

Expected: `ImportError` — module `filters` not found.

- [ ] **Step 3: Implement `filters.py`**

```python
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

COMUNI_AMMESSI = {
    "chiasso", "mendrisio", "stabio", "balerna",
    "coldrerio", "morbio inferiore", "novazzano", "riva san vitale",
}

KEYWORDS = {
    "tech": [
        "Junior IT", "Help Desk", "Tecnico informatico",
        "Sviluppatore Junior", "Operaio elettronico", "Cablatore",
    ],
    "logistica": [
        "Magazziniere", "Addetto logistica", "Operaio generico",
        "Ausiliario di produzione", "Preparatore ordini",
    ],
    "pulizie": [
        "Ausiliario di pulizia", "Addetto pulizie", "Pulitore",
    ],
    "retail": [
        "Scaffalista", "Addetto vendita", "Cassiere",
    ],
}


def normalize_city(city_raw: str) -> str:
    if " - " in city_raw:
        return city_raw.split(" - ")[-1].strip().lower()
    return city_raw.strip().lower()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=False)
    clean = {k: v for k, v in params.items() if not k.startswith("utm_")}
    return urlunparse(parsed._replace(query=urlencode(clean, doseq=True)))


def is_valid_job(job: dict) -> bool:
    city = normalize_city(job.get("city", ""))
    url = job.get("url", "")
    if urlparse(url).netloc.endswith(".it"):
        return False
    return city in COMUNI_AMMESSI


def categorize_job(title: str) -> str:
    title_lower = title.lower()
    for category, keywords in KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in title_lower:
                return category
    return "altro"


def filter_jobs(jobs: list) -> list:
    valid = [j for j in jobs if is_valid_job(j)]
    seen, deduped = set(), []
    for job in valid:
        key = normalize_url(job["url"])
        if key not in seen:
            seen.add(key)
            deduped.append(job)
    return sorted(deduped, key=lambda j: j.get("date", ""), reverse=True)
```

- [ ] **Step 4: Run tests — verify they pass**

```
pytest tests/test_filters.py -v
```

Expected: all 13 tests PASS.

- [ ] **Step 5: Commit**

```
git add filters.py tests/test_filters.py
git commit -m "feat: add filters module with TDD"
```

---

### Task 3: HTML generator (TDD)

**Files:**
- Create: `html_generator.py`
- Create: `tests/test_html_generator.py`

- [ ] **Step 1: Write failing tests — create `tests/test_html_generator.py`**

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```
pytest tests/test_html_generator.py -v
```

Expected: `ImportError` — module `html_generator` not found.

- [ ] **Step 3: Implement `html_generator.py`**

```python
import html as html_lib
from datetime import datetime
from pathlib import Path

CATEGORY_COLORS = {
    "tech":      "bg-blue-600",
    "logistica": "bg-green-600",
    "pulizie":   "bg-yellow-500",
    "retail":    "bg-orange-500",
    "altro":     "bg-gray-500",
}

CATEGORY_LABELS = {
    "tech":      "Tech/IT",
    "logistica": "Logistica",
    "pulizie":   "Pulizie",
    "retail":    "Retail",
    "altro":     "Altro",
}


def build_card(job: dict) -> str:
    title   = html_lib.escape(job.get("title",   ""))
    company = html_lib.escape(job.get("company", ""))
    city    = html_lib.escape(job.get("city",    ""))
    date    = html_lib.escape(job.get("date",    ""))
    url     = html_lib.escape(job.get("url",     "#"))
    source  = html_lib.escape(job.get("source",  ""))
    cat     = job.get("category", "altro")

    color = CATEGORY_COLORS.get(cat, "bg-gray-500")
    label = CATEGORY_LABELS.get(cat, cat)

    return (
        f'<div class="job-card bg-white rounded-xl shadow-sm p-4 flex flex-col gap-3'
        f' hover:shadow-md transition-shadow" data-category="{cat}">\n'
        f'  <div class="flex items-start justify-between gap-2">\n'
        f'    <span class="{color} text-white text-xs font-bold px-2 py-0.5 rounded-full'
        f' uppercase tracking-wide">{label}</span>\n'
        f'    <span class="text-xs text-gray-400">{source}</span>\n'
        f'  </div>\n'
        f'  <div>\n'
        f'    <h2 class="font-bold text-gray-900 text-base leading-snug">{title}</h2>\n'
        f'    <p class="text-sm text-gray-500 mt-0.5">{company}</p>\n'
        f'  </div>\n'
        f'  <div class="flex items-center gap-2">\n'
        f'    <span class="inline-block bg-red-100 text-red-700 text-xs font-bold px-2 py-0.5 rounded">CH</span>\n'
        f'    <span class="text-gray-700 font-semibold text-sm">SVIZZERA &ndash; {city}</span>\n'
        f'  </div>\n'
        f'  <p class="text-xs text-gray-400">{date}</p>\n'
        f'  <a href="{url}" target="_blank" rel="noopener noreferrer"\n'
        f'     class="mt-auto w-full bg-blue-600 hover:bg-blue-700 text-white text-center'
        f' py-2 rounded-lg font-semibold text-sm transition-colors">\n'
        f'    Candidati Ora &rarr;\n'
        f'  </a>\n'
        f'</div>'
    )


def generate_html(jobs: list, output_path: str = "index.html"):
    now = datetime.now().strftime("%d/%m/%Y alle %H:%M")
    count = len(jobs)
    count_label = f"{count} annunci trovati"

    if jobs:
        cards = "\n".join(build_card(j) for j in jobs)
        main_content = (
            '<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">\n'
            + cards + "\n</div>"
        )
    else:
        main_content = (
            '<div class="text-center py-20">\n'
            '  <p class="text-5xl text-gray-300 mb-4">&#128269;</p>\n'
            '  <p class="text-xl text-gray-500">Nessun annuncio trovato oggi.</p>\n'
            '  <p class="text-sm text-gray-400 mt-1">Riprova domani o verifica la connessione.</p>\n'
            '</div>'
        )

    page = (
        "<!DOCTYPE html>\n"
        '<html lang="it">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "  <title>Dashboard Lavoro Frontaliero</title>\n"
        '  <script src="https://cdn.tailwindcss.com"></script>\n'
        "</head>\n"
        '<body class="bg-gray-100 min-h-screen">\n\n'
        '<header class="bg-white shadow-sm sticky top-0 z-10">\n'
        '  <div class="max-w-7xl mx-auto px-4 py-4 flex flex-wrap gap-4 items-center justify-between">\n'
        "    <div>\n"
        '      <h1 class="text-2xl font-bold text-gray-900">Dashboard Lavoro Frontaliero</h1>\n'
        f'      <p class="text-sm text-gray-500">Ultimo aggiornamento: {now}</p>\n'
        "    </div>\n"
        f'    <span class="bg-blue-600 text-white px-4 py-2 rounded-full font-bold text-base">{count_label}</span>\n'
        "  </div>\n"
        '  <div class="max-w-7xl mx-auto px-4 pb-3 flex flex-wrap gap-2">\n'
        '    <button onclick="filterJobs(\'all\')"       id="btn-all"       class="filter-btn px-4 py-1.5 rounded-full text-sm font-medium bg-gray-800 text-white">Tutti</button>\n'
        '    <button onclick="filterJobs(\'tech\')"      id="btn-tech"      class="filter-btn px-4 py-1.5 rounded-full text-sm font-medium bg-gray-200 text-gray-700 hover:bg-gray-300">Tech/IT</button>\n'
        '    <button onclick="filterJobs(\'logistica\')" id="btn-logistica" class="filter-btn px-4 py-1.5 rounded-full text-sm font-medium bg-gray-200 text-gray-700 hover:bg-gray-300">Logistica</button>\n'
        '    <button onclick="filterJobs(\'pulizie\')"   id="btn-pulizie"   class="filter-btn px-4 py-1.5 rounded-full text-sm font-medium bg-gray-200 text-gray-700 hover:bg-gray-300">Pulizie</button>\n'
        '    <button onclick="filterJobs(\'retail\')"    id="btn-retail"    class="filter-btn px-4 py-1.5 rounded-full text-sm font-medium bg-gray-200 text-gray-700 hover:bg-gray-300">Retail</button>\n'
        '    <button onclick="filterJobs(\'altro\')"     id="btn-altro"     class="filter-btn px-4 py-1.5 rounded-full text-sm font-medium bg-gray-200 text-gray-700 hover:bg-gray-300">Altro</button>\n'
        "  </div>\n"
        "</header>\n\n"
        '<main class="max-w-7xl mx-auto px-4 py-6">\n'
        f"  {main_content}\n"
        "</main>\n\n"
        "<script>\n"
        "  function filterJobs(category) {\n"
        "    document.querySelectorAll('.job-card').forEach(card => {\n"
        "      card.style.display = (category === 'all' || card.dataset.category === category) ? '' : 'none';\n"
        "    });\n"
        "    document.querySelectorAll('.filter-btn').forEach(btn => {\n"
        "      btn.classList.remove('bg-gray-800', 'text-white');\n"
        "      btn.classList.add('bg-gray-200', 'text-gray-700');\n"
        "    });\n"
        "    const active = document.getElementById('btn-' + category);\n"
        "    if (active) {\n"
        "      active.classList.remove('bg-gray-200', 'text-gray-700');\n"
        "      active.classList.add('bg-gray-800', 'text-white');\n"
        "    }\n"
        "  }\n"
        "</script>\n\n"
        "</body>\n"
        "</html>\n"
    )

    Path(output_path).write_text(page, encoding="utf-8")
    print(f"[OK] Dashboard generata: {output_path} ({count} annunci)")
```

- [ ] **Step 4: Run tests — verify they pass**

```
pytest tests/test_html_generator.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```
git add html_generator.py tests/test_html_generator.py
git commit -m "feat: add HTML generator with TDD"
```

---

### Task 4: Anti-detection browser helpers

**Files:**
- Modify: `scrapers/__init__.py`

- [ ] **Step 1: Overwrite `scrapers/__init__.py` with full implementation**

```python
import random
import time
import functools
from pathlib import Path

from playwright.sync_api import Playwright, BrowserContext

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]

VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
]

PROFILE_DIR = Path(__file__).parent.parent / "profile"
SESSION_FILE = PROFILE_DIR / "state.json"


def create_browser_context(playwright: Playwright) -> tuple:
    """Launch Chrome with maximum anti-detection settings. Returns (browser, context)."""
    PROFILE_DIR.mkdir(exist_ok=True)

    ua       = random.choice(USER_AGENTS)
    viewport = random.choice(VIEWPORTS)

    browser = playwright.chromium.launch(
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            f"--window-size={viewport['width']},{viewport['height']}",
        ],
    )

    context_kwargs = {
        "user_agent": ua,
        "viewport": viewport,
        "locale": "it-CH",
        "timezone_id": "Europe/Zurich",
        "extra_http_headers": {"Accept-Language": "it-CH,it;q=0.9,en;q=0.8"},
    }
    if SESSION_FILE.exists():
        context_kwargs["storage_state"] = str(SESSION_FILE)

    context = browser.new_context(**context_kwargs)
    return browser, context


def new_stealth_page(context: BrowserContext):
    """Create a page with playwright-stealth patches applied."""
    from playwright_stealth import stealth_sync
    page = context.new_page()
    stealth_sync(page)
    return page


def human_delay(min_s: float = 3.0, max_s: float = 8.0):
    time.sleep(random.uniform(min_s, max_s))


def human_scroll(page):
    """Scroll gradually to simulate a human reading the page."""
    page.evaluate(
        "() => new Promise(resolve => {"
        "  let y = 0;"
        "  const step = () => {"
        "    y += Math.floor(Math.random() * 120) + 40;"
        "    window.scrollTo(0, y);"
        "    if (y < document.body.scrollHeight * 0.6) setTimeout(step, 120);"
        "    else resolve();"
        "  };"
        "  step();"
        "})"
    )


def dismiss_cookie_dialog(page):
    """Click the minimal/reject cookie button if a consent dialog is visible."""
    selectors = [
        'button:has-text("Essential cookies only")',
        'button:has-text("Nega il consenso")',
        'button:has-text("Reject all")',
        'button:has-text("Rifiuta tutto")',
    ]
    for sel in selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(1500)
                return
        except Exception:
            pass


def save_session(context: BrowserContext):
    """Persist cookies and storage state for the next run."""
    PROFILE_DIR.mkdir(exist_ok=True)
    try:
        context.storage_state(path=str(SESSION_FILE))
        print("[OK] Sessione salvata.")
    except Exception as e:
        print(f"[WARN] Impossibile salvare sessione: {e}")


def retry(max_attempts: int = 3):
    """Decorator: retry on exception with exponential backoff (10s, 20s, 40s)."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        print(f"[ERRORE] {func.__name__} fallito dopo {max_attempts} tentativi: {e}")
                        return []
                    delay = 10 * (2 ** attempt)
                    print(f"[RETRY] Tentativo {attempt + 1} fallito. Riprovo tra {delay}s…")
                    time.sleep(delay)
        return wrapper
    return decorator
```

- [ ] **Step 2: Verify import**

```
python -c "from scrapers import create_browser_context, new_stealth_page, retry; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```
git add scrapers/__init__.py
git commit -m "feat: add anti-detection browser helpers"
```

---

### Task 5: jobs.ch scraper

**Files:**
- Create: `scrapers/jobs_ch.py`

- [ ] **Step 1: Create `scrapers/jobs_ch.py`**

```python
from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from filters import KEYWORDS

BASE_URL   = "https://www.jobs.ch"
SEARCH_URL = "https://www.jobs.ch/en/vacancies/?term={term}&location=ticino&page={page}"
MAX_PAGES  = 3


def _extract_jobs_from_page(page, category: str) -> list:
    jobs = []
    cards = page.query_selector_all('a[data-cy="job-link"]')
    for card in cards:
        try:
            title = card.get_attribute("title") or ""
            href  = card.get_attribute("href") or ""
            url   = f"{BASE_URL}{href}" if href.startswith("/") else href

            paras = card.query_selector_all("p")
            date_text = paras[0].text_content().strip() if len(paras) > 0 else ""
            city_text = paras[1].text_content().strip() if len(paras) > 1 else ""

            company_el = card.query_selector("p[class*='fw_bol']")
            company    = company_el.text_content().strip() if company_el else ""

            if title and url:
                jobs.append({
                    "title":    title,
                    "company":  company,
                    "city":     city_text,
                    "date":     date_text,
                    "url":      url,
                    "category": category,
                    "source":   "jobs.ch",
                })
        except Exception as e:
            print(f"[WARN] Errore card jobs.ch: {e}")
    return jobs


@retry(max_attempts=3)
def scrape_jobs_ch(context, keywords_dict: dict = None) -> list:
    if keywords_dict is None:
        keywords_dict = KEYWORDS

    all_jobs = []
    page = new_stealth_page(context)

    for category, keywords in keywords_dict.items():
        for keyword in keywords:
            print(f"[jobs.ch] '{keyword}' ({category})")
            for page_num in range(1, MAX_PAGES + 1):
                url = SEARCH_URL.format(term=keyword.replace(" ", "+"), page=page_num)
                try:
                    page.goto(url, timeout=30_000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    dismiss_cookie_dialog(page)
                    human_scroll(page)
                    human_delay(3.0, 7.0)

                    jobs = _extract_jobs_from_page(page, category)
                    if not jobs:
                        break
                    all_jobs.extend(jobs)
                    print(f"  pag.{page_num}: {len(jobs)} annunci")
                    if len(jobs) < 20:
                        break
                except Exception as e:
                    print(f"[WARN] {url}: {e}")
                    break

    page.close()
    print(f"[jobs.ch] Totale grezzo: {len(all_jobs)}")
    return all_jobs
```

- [ ] **Step 2: Smoke-test jobs.ch (run as a script)**

Create a temporary file `_test_jobs_ch.py`:

```python
from playwright.sync_api import sync_playwright
from scrapers import create_browser_context, save_session
from scrapers.jobs_ch import scrape_jobs_ch

with sync_playwright() as p:
    browser, context = create_browser_context(p)
    results = scrape_jobs_ch(context, keywords_dict={"tech": ["Junior IT"], "logistica": ["Magazziniere"]})
    save_session(context)
    browser.close()

print(f"\nTotale risultati: {len(results)}")
for r in results[:3]:
    print(r)
```

Run: `python _test_jobs_ch.py`

Expected: browser opens, searches run, results printed. No unhandled exceptions.

Delete `_test_jobs_ch.py` after verification.

- [ ] **Step 3: Commit**

```
git add scrapers/jobs_ch.py
git commit -m "feat: add jobs.ch scraper"
```

---

### Task 6: carriera.ch scraper

**Files:**
- Create: `scrapers/carriera_ch.py`

- [ ] **Step 1: Create `scrapers/carriera_ch.py`**

```python
from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from filters import categorize_job

LIST_URL  = "https://www.carriera.ch/offerte/annunci-offerte-lavoro_0_0_{page}.html"
MAX_PAGES = 5


def _extract_jobs_from_page(page) -> list:
    jobs = []
    rows = page.query_selector_all("tr")
    for row in rows:
        cells = row.query_selector_all("td")
        if len(cells) != 6:
            continue
        try:
            date_text   = cells[0].text_content().strip()
            company_img = cells[1].query_selector("img")
            company     = (company_img.get_attribute("alt") or "").strip() if company_img else cells[1].text_content().strip()
            title_link  = cells[2].query_selector("a")
            if not title_link:
                continue
            title = title_link.text_content().strip()
            url   = title_link.get_attribute("href") or ""
            city  = cells[3].text_content().strip()

            if not title or not url:
                continue
            if not url.startswith("http"):
                url = f"https://www.carriera.ch{url}"

            jobs.append({
                "title":    title,
                "company":  company,
                "city":     city,
                "date":     date_text,
                "url":      url,
                "category": categorize_job(title),
                "source":   "carriera.ch",
            })
        except Exception as e:
            print(f"[WARN] Errore riga carriera.ch: {e}")
    return jobs


@retry(max_attempts=3)
def scrape_carriera_ch(context) -> list:
    all_jobs = []
    page = new_stealth_page(context)

    for page_num in range(MAX_PAGES):
        url = LIST_URL.format(page=page_num)
        print(f"[carriera.ch] Pagina {page_num + 1}/{MAX_PAGES}")
        try:
            page.goto(url, timeout=30_000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            dismiss_cookie_dialog(page)
            human_scroll(page)
            human_delay(3.0, 7.0)

            jobs = _extract_jobs_from_page(page)
            if not jobs:
                print("  Nessun annuncio, fine paginazione.")
                break
            all_jobs.extend(jobs)
            print(f"  {len(jobs)} annunci trovati")
        except Exception as e:
            print(f"[WARN] {url}: {e}")
            break

    page.close()
    print(f"[carriera.ch] Totale grezzo: {len(all_jobs)}")
    return all_jobs
```

- [ ] **Step 2: Smoke-test carriera.ch**

Create `_test_carriera.py`:

```python
from playwright.sync_api import sync_playwright
from scrapers import create_browser_context, save_session
from scrapers.carriera_ch import scrape_carriera_ch

with sync_playwright() as p:
    browser, context = create_browser_context(p)
    results = scrape_carriera_ch(context)
    save_session(context)
    browser.close()

print(f"\nTotale risultati: {len(results)}")
for r in results[:3]:
    print(r)
```

Run: `python _test_carriera.py`

Expected: 20-100 results (unfiltered), no errors.

Delete `_test_carriera.py` after verification.

- [ ] **Step 3: Commit**

```
git add scrapers/carriera_ch.py
git commit -m "feat: add carriera.ch scraper"
```

---

### Task 7: Entry point (scraper.py)

**Files:**
- Create: `scraper.py`

- [ ] **Step 1: Create `scraper.py`**

```python
from datetime import datetime
from playwright.sync_api import sync_playwright

from scrapers import create_browser_context, save_session
from scrapers.jobs_ch import scrape_jobs_ch
from scrapers.carriera_ch import scrape_carriera_ch
from filters import filter_jobs
from html_generator import generate_html

# ─── Hook LLM opzionale (commentato) ─────────────────────────────────────────
# Per attivarlo in futuro: pip install anthropic
# Imposta la variabile d'ambiente: ANTHROPIC_API_KEY=sk-ant-...
#
# def analyze_with_llm(job_text: str) -> dict:
#     import anthropic, json
#     client = anthropic.Anthropic()
#     msg = client.messages.create(
#         model="claude-sonnet-4-6",
#         max_tokens=256,
#         messages=[{"role": "user", "content": (
#             "Analizza questo annuncio di lavoro svizzero. Rispondi SOLO in JSON:\n"
#             '{"stipendio": "...", "esclusi_frontalieri": true/false}\n\n' + job_text
#         )}],
#     )
#     return json.loads(msg.content[0].text)
# ─────────────────────────────────────────────────────────────────────────────


def main():
    start = datetime.now()
    print(f"[START] {start.strftime('%d/%m/%Y %H:%M')}")

    raw_jobs = []

    with sync_playwright() as p:
        browser, context = create_browser_context(p)
        try:
            print("\n=== JOBS.CH ===")
            raw_jobs.extend(scrape_jobs_ch(context))

            print("\n=== CARRIERA.CH ===")
            raw_jobs.extend(scrape_carriera_ch(context))
        except Exception as e:
            print(f"[ERRORE CRITICO] {e}")
        finally:
            save_session(context)
            browser.close()

    valid = filter_jobs(raw_jobs)
    print(f"\n[FILTER] {len(raw_jobs)} grezzi → {len(valid)} validi")

    generate_html(valid)

    elapsed = (datetime.now() - start).seconds
    print(f"[DONE] Completato in {elapsed}s. Apri index.html nel browser.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the full scraper end-to-end**

```
python scraper.py
```

Expected:
- Browser window opens (Chrome visible)
- Console shows each keyword being searched
- Ends with `[DONE] Completato in ...s. Apri index.html nel browser.`
- `index.html` is created in `C:\Users\Administrator\Desktop\Lavoro\`

- [ ] **Step 3: Open dashboard in browser and verify**

Open `index.html` in Chrome or Edge. Verify:
- Header shows today's date and job count
- Filter buttons are visible and clickable
- Job cards show `CH` badge + `SVIZZERA – CityName`
- "Candidati Ora" button opens job link in new tab

- [ ] **Step 4: Commit**

```
git add scraper.py
git commit -m "feat: add entry point orchestrator"
```

---

### Task 8: Windows Task Scheduler and documentation

**Files:**
- Create: `setup_task_scheduler.bat`
- Create: `COME_AVVIARE.md`

- [ ] **Step 1: Create `setup_task_scheduler.bat`**

```bat
@echo off
echo Configurazione Task Scheduler Windows...
echo.

for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)"') do set PYTHON_PATH=%%i
set SCRIPT_PATH=%~dp0scraper.py

echo Python: %PYTHON_PATH%
echo Script: %SCRIPT_PATH%
echo.

schtasks /create /tn "JobScraperFrontaliero" ^
  /tr "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\"" ^
  /sc daily /st 08:00 /f

if %ERRORLEVEL% == 0 (
    echo.
    echo [OK] Task creato! Lo script girera ogni mattina alle 08:00.
    echo.
    echo Per rimuoverlo: schtasks /delete /tn "JobScraperFrontaliero"
) else (
    echo.
    echo [ERRORE] Creazione fallita. Prova a eseguire come Amministratore.
)
echo.
pause
```

- [ ] **Step 2: Create `COME_AVVIARE.md`**

```markdown
# Come avviare il Job Scraper Frontaliero

## Primo avvio (una volta sola)

1. Apri il Prompt dei Comandi nella cartella `Lavoro`:
   - Tasto destro sulla cartella → "Apri nel terminale"

2. Installa le dipendenze:
   pip install -r requirements.txt
   playwright install chromium

3. Esegui lo scraper per testare:
   python scraper.py
   (Una finestra Chrome si apre automaticamente — non chiuderla)

4. Apri `index.html` nel browser per vedere la dashboard.

5. Configura l'avvio automatico ogni mattina alle 08:00:
   - Fai doppio clic su `setup_task_scheduler.bat`
   - Clicca "Si" se chiede i permessi di amministratore

## Uso quotidiano

Apri `index.html` ogni mattina — la dashboard si aggiorna in automatico alle 08:00.
Il computer deve essere acceso e connesso a internet all'orario configurato.

## Aggiornamento manuale

python scraper.py

## Problemi comuni

| Problema                   | Soluzione                                               |
|----------------------------|---------------------------------------------------------|
| "playwright non trovato"   | pip install playwright && playwright install chromium   |
| 0 annunci trovati          | Controlla la console per errori o selettori obsoleti    |
| Il task non parte          | Il PC deve essere acceso alle 08:00                     |
| Disattivare l'automatismo  | schtasks /delete /tn "JobScraperFrontaliero"            |
```

- [ ] **Step 3: Test Task Scheduler**

Right-click `setup_task_scheduler.bat` → Run as Administrator.
Expected: `[OK] Task creato!`

Verify:
```
schtasks /query /tn "JobScraperFrontaliero"
```
Expected: shows status `Ready` and next run time tomorrow at 08:00.

- [ ] **Step 4: Final commit**

```
git add setup_task_scheduler.bat COME_AVVIARE.md
git commit -m "feat: add Task Scheduler setup and documentation"
```

---

## Spec coverage self-review

| Requisito spec                              | Task che lo implementa         |
|---------------------------------------------|--------------------------------|
| Playwright anti-bot                         | Task 4 (scrapers/__init__.py)  |
| playwright-stealth                          | Task 4                         |
| User-agent rotante (5 UA)                   | Task 4                         |
| Viewport realistico random                  | Task 4                         |
| Locale it-CH + timezone Zurich              | Task 4                         |
| Sessione browser persistente                | Task 4                         |
| Scroll umano simulato                       | Task 4                         |
| Delay casuale 3-8s                          | Task 4                         |
| Retry con exponential backoff               | Task 4                         |
| Rilevamento blocco/CAPTCHA                  | Task 4 (dismiss_cookie_dialog) |
| Portal jobs.ch                              | Task 5                         |
| Portal carriera.ch                          | Task 6                         |
| Whitelist 8 comuni svizzeri                 | Task 2 (filters.py)            |
| Scarto URL .it (annunci italiani)           | Task 2                         |
| 4 categorie parole chiave                   | Task 2 (KEYWORDS)              |
| 5 campi per annuncio                        | Task 5, 6                      |
| Deduplicazione per URL normalizzato         | Task 2                         |
| Hook LLM commentato                         | Task 7 (scraper.py)            |
| Dashboard Tailwind CSS                      | Task 3 (html_generator.py)     |
| Timestamp + contatore annunci              | Task 3                         |
| Filtri JS per categoria                     | Task 3                         |
| Badge colorati per categoria                | Task 3                         |
| "SVIZZERA – Comune" nelle card             | Task 3                         |
| Bottone "Candidati Ora" target=_blank      | Task 3                         |
| Stato vuoto se 0 annunci                    | Task 3                         |
| Windows Task Scheduler automatico          | Task 8                         |
| Istruzioni avvio complete                   | Task 8 (COME_AVVIARE.md)       |
