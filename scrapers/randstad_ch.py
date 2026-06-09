"""
Scraper per Randstad Svizzera (www.randstad.ch/it/lavoro/re-ticino/)

Struttura verificata live:
- URL lista: /it/lavoro/re-ticino/ → 38 annunci Ticino
- Titolo:  a[href con UUID] > h3
- Città:   riga "City, Ticino" nel testo del card
- Data:    riga "D. Mese YYYY" (es. "9. Giugno 2026")
- URL:     link relativo, base https://www.randstad.ch
- Azienda: sempre "Randstad SA"
"""

from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from filters import categorize_job

BASE_URL = "https://www.randstad.ch"
LIST_URL = "https://www.randstad.ch/it/lavoro/re-ticino/"

# Estrazione via JS: più affidabile dei CSS selector con classi dinamiche
_JS_EXTRACT = """
() => {
  const MESI = {
    'gennaio':1,'febbraio':2,'marzo':3,'aprile':4,'maggio':5,'giugno':6,
    'luglio':7,'agosto':8,'settembre':9,'ottobre':10,'novembre':11,'dicembre':12
  };
  const links = Array.from(document.querySelectorAll('a[href*="/it/lavoro/"]'))
    .filter(a => /[a-f0-9]{8}-[a-f0-9]{4}/.test(a.getAttribute('href') || ''));

  return links.map(a => {
    const li = a.closest('li');
    const lines = (li ? li.innerText.trim() : '')
      .split('\\n').map(s => s.trim()).filter(Boolean);

    const title = (a.querySelector('h3') || {}).innerText || '';

    // Riga "Città, Cantone" (contiene virgola e spazio)
    const cityLine = lines.find(l => l.includes(', ')) || '';
    const city = cityLine.split(',')[0].trim();

    // Riga con la data → "D. Mese YYYY"
    const dateLine = lines.find(l => /\\d+\\.\\s+\\w+\\s+\\d{4}/.test(l)) || '';
    const dm = dateLine.match(/(\\d+)\\.\\s+(\\w+)\\s+(\\d{4})/);
    let date = dateLine;
    if (dm) {
      const mes = MESI[dm[2].toLowerCase()];
      if (mes) {
        date = dm[3] + '-' + String(mes).padStart(2, '0') + '-' + dm[1].padStart(2, '0');
      }
    }

    return {
      title: title.trim(),
      city:  city,
      date:  date,
      url:   'https://www.randstad.ch' + a.getAttribute('href'),
    };
  }).filter(j => j.title && j.url);
}
"""


@retry(max_attempts=3)
def scrape_randstad_ch(context) -> list:
    all_jobs = []
    page = new_stealth_page(context)

    print(f"  [randstad.ch] Carico offerte Ticino…")
    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=30000)
    dismiss_cookie_dialog(page)
    page.wait_for_timeout(2000)

    # Scroll per triggerare il lazy-load
    human_scroll(page)
    page.wait_for_timeout(1500)

    # Clicca "Visualizza altri 30" se presente (carica il resto degli annunci)
    try:
        btn = page.query_selector('button:has-text("Visualizza altri")')
        if btn and btn.is_visible():
            btn.click()
            page.wait_for_timeout(2500)
            human_scroll(page)
            page.wait_for_timeout(1000)
    except Exception:
        pass

    # Estrai tutti gli annunci visibili tramite JS
    try:
        jobs_raw = page.evaluate(_JS_EXTRACT)
    except Exception as e:
        print(f"  [randstad.ch] Errore JS: {e}")
        page.close()
        return []

    for job in jobs_raw:
        title = job.get("title", "").strip()
        city  = job.get("city",  "").strip()
        url   = job.get("url",   "").strip()
        if not title or not url:
            continue
        all_jobs.append({
            "title":    title,
            "company":  "Randstad SA",
            "city":     city,
            "date":     job.get("date", ""),
            "url":      url,
            "category": categorize_job(title),
            "source":   "randstad.ch",
        })

    print(f"  [randstad.ch] {len(all_jobs)} annunci trovati")
    page.close()
    human_delay(2.0, 4.0)
    return all_jobs
