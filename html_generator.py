import html as html_lib
from datetime import datetime
from pathlib import Path

# (badge_bg, badge_text, btn_active_bg, btn_active_text, label)
CATEGORY = {
    "tech":         ("#1e3a5f", "#60a5fa", "#2563eb", "#fff",      "Tech / IT"),
    "logistica":    ("#14452f", "#34d399", "#059669", "#fff",      "Logistica"),
    "produzione":   ("#0f3543", "#22d3ee", "#0891b2", "#fff",      "Produzione"),
    "ristorazione": ("#4a1942", "#f472b6", "#db2777", "#fff",      "Ristorazione"),
    "pulizie":      ("#3d3209", "#fbbf24", "#d97706", "#fff",      "Pulizie"),
    "retail":       ("#431a07", "#fb923c", "#ea580c", "#fff",      "Retail"),
    "trasporti":    ("#2e1a6e", "#a78bfa", "#7c3aed", "#fff",      "Trasporti"),
    "altro":        ("#1f2937", "#9ca3af", "#4b5563", "#fff",      "Altro"),
}

SOURCE_LABEL = {
    "jobs.ch":      "jobs.ch",
    "carriera.ch":  "carriera.ch",
    "gigroup.ch":   "Gi Group",
    "randstad.ch":  "Randstad",
}


def _e(s: str) -> str:
    return html_lib.escape(str(s))


def build_card(job: dict) -> str:
    title   = _e(job.get("title",   ""))
    company = _e(job.get("company", ""))
    city    = _e(job.get("city",    ""))
    date    = _e(job.get("date",    ""))
    raw_url = job.get("url", "#")
    url     = _e(raw_url if raw_url.startswith(("https://", "http://")) else "#")
    source  = SOURCE_LABEL.get(job.get("source", ""), _e(job.get("source", "")))
    cat     = job.get("category", "altro")

    badge_bg, badge_txt, _, _, cat_label = CATEGORY.get(cat, CATEGORY["altro"])

    # Descrizione: LLM se disponibile, altrimenti testo grezzo ripulito
    llm_desc = job.get("llm_descrizione", "").strip()
    raw_desc  = job.get("description",    "").strip()
    if llm_desc:
        desc = _e(llm_desc)
    elif raw_desc:
        cleaned = raw_desc.replace(" | ", " ").strip()
        desc = _e(cleaned[:350]) + ("…" if len(cleaned) > 350 else "")
    else:
        desc = ""

    # Badge AI
    llm_adatto = job.get("llm_adatto")
    llm_motivo = _e(job.get("llm_motivo", ""))
    ai_filter  = "none"

    if llm_adatto is True:
        ai_filter  = "adatto"
        ai_html = (
            '<div style="background:#052e16;border:1px solid #166534" '
            'class="rounded-lg px-3 py-2 flex items-start gap-2">'
            '<span style="color:#4ade80;font-size:14px;margin-top:1px">✔</span>'
            '<div>'
            '<span style="color:#4ade80;font-size:11px;font-weight:700;letter-spacing:.05em">'
            'ADATTO</span>'
            + (f'<p style="color:#86efac;font-size:12px;margin:2px 0 0">{llm_motivo}</p>' if llm_motivo else "")
            + '</div></div>\n'
        )
    elif llm_adatto is False:
        ai_filter  = "non_adatto"
        ai_html = (
            '<div style="background:#2d0a0a;border:1px solid #7f1d1d" '
            'class="rounded-lg px-3 py-2 flex items-start gap-2">'
            '<span style="color:#f87171;font-size:14px;margin-top:1px">✘</span>'
            '<div>'
            '<span style="color:#f87171;font-size:11px;font-weight:700;letter-spacing:.05em">'
            'NON ADATTO</span>'
            + (f'<p style="color:#fca5a5;font-size:12px;margin:2px 0 0">{llm_motivo}</p>' if llm_motivo else "")
            + '</div></div>\n'
        )
    else:
        ai_html = ""

    desc_block = (
        f'<p style="color:#9ca3af;font-size:13px;line-height:1.6" '
        f'class="line-clamp-4">{desc}</p>\n'
        if desc else ""
    )

    return f"""<div class="job-card" data-category="{_e(cat)}" data-ai="{ai_filter}"
  style="background:#161b22;border:1px solid #30363d;border-radius:12px;padding:18px;
         display:flex;flex-direction:column;gap:14px;">

  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px">
    <span style="background:{badge_bg};color:{badge_txt};font-size:10px;font-weight:700;
                 letter-spacing:.08em;padding:3px 10px;border-radius:999px;text-transform:uppercase">
      {cat_label}
    </span>
    <span style="color:#6e7681;font-size:11px;background:#21262d;padding:2px 8px;
                 border-radius:6px;white-space:nowrap">{source}</span>
  </div>

  <div>
    <h2 style="color:#e6edf3;font-size:15px;font-weight:700;line-height:1.4;margin:0 0 4px">{title}</h2>
    <p style="color:#7d8590;font-size:13px;margin:0">{company}</p>
  </div>

  {desc_block}

  <div style="display:flex;align-items:center;gap:6px">
    <span style="color:#f0883e;font-size:13px">📍</span>
    <span style="color:#e6edf3;font-size:13px;font-weight:600">{city}</span>
    <span style="color:#6e7681;font-size:12px">· 🇨🇭 Svizzera</span>
  </div>

  {ai_html}

  <div style="display:flex;align-items:center;justify-content:space-between;margin-top:auto">
    <span style="color:#6e7681;font-size:11px">🗓 {date}</span>
  </div>

  <a href="{url}" target="_blank" rel="noopener noreferrer"
     style="display:block;text-align:center;background:linear-gradient(135deg,#1d4ed8,#4f46e5);
            color:#fff;font-size:13px;font-weight:700;padding:10px;border-radius:8px;
            text-decoration:none;letter-spacing:.03em;transition:opacity .15s"
     onmouseover="this.style.opacity='.85'" onmouseout="this.style.opacity='1'">
    Candidati ora →
  </a>
</div>"""


def generate_html(jobs: list, output_path: str = "index.html"):
    now   = datetime.now().strftime("%d/%m/%Y alle %H:%M")
    count = len(jobs)

    # Conteggi per categoria (per le label dei bottoni)
    cat_counts: dict[str, int] = {}
    for j in jobs:
        cat_counts[j.get("category", "altro")] = cat_counts.get(j.get("category", "altro"), 0) + 1
    adatti = sum(1 for j in jobs if j.get("llm_adatto") is True)

    if jobs:
        cards_html = '\n'.join(build_card(j) for j in jobs)
        grid = (
            '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px">\n'
            + cards_html + '\n</div>'
        )
    else:
        grid = (
            '<div style="text-align:center;padding:80px 20px">'
            '<div style="font-size:48px;margin-bottom:16px">🔍</div>'
            '<p style="color:#e6edf3;font-size:20px;font-weight:600">Nessun annuncio trovato</p>'
            '<p style="color:#7d8590;font-size:14px;margin-top:8px">Riprova domani o verifica la connessione.</p>'
            '</div>'
        )

    def cat_btn(cat_id: str) -> str:
        _, _, abg, atxt, lbl = CATEGORY.get(cat_id, CATEGORY["altro"])
        n = cat_counts.get(cat_id, 0)
        label_txt = f"{lbl}" + (f" <span style='opacity:.6;font-size:10px'>({n})</span>" if n else "")
        return (
            f'<button onclick="filterJobs(\'{cat_id}\')" id="btn-{cat_id}" '
            f'data-active-bg="{abg}" data-active-txt="{atxt}" '
            f'class="filter-btn" style="background:#21262d;color:#8b949e;border:1px solid #30363d;'
            f'padding:5px 14px;border-radius:999px;font-size:12px;font-weight:600;cursor:pointer;'
            f'white-space:nowrap;transition:all .15s">{label_txt}</button>'
        )

    cat_buttons = "\n          ".join(cat_btn(c) for c in CATEGORY)

    adatti_label = f"✔ Adatti AI" + (f" ({adatti})" if adatti else "")

    page = f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Lavoro Frontaliero · Ticino</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0d1117; color: #e6edf3; font-family: -apple-system, BlinkMacSystemFont,
            'Segoe UI', 'Inter', sans-serif; min-height: 100vh; }}
    ::-webkit-scrollbar {{ width: 6px; }}
    ::-webkit-scrollbar-track {{ background: #0d1117; }}
    ::-webkit-scrollbar-thumb {{ background: #30363d; border-radius: 3px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: #484f58; }}
    .job-card {{ transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease; }}
    .job-card:hover {{ transform: translateY(-4px);
                       box-shadow: 0 12px 40px rgba(0,0,0,.55);
                       border-color: #6e7681 !important; }}
    .filter-btn:hover {{ opacity: .85; }}
    .line-clamp-4 {{ display: -webkit-box; -webkit-line-clamp: 4;
                     -webkit-box-orient: vertical; overflow: hidden; }}
  </style>
</head>
<body>

<!-- HEADER -->
<header style="background:#161b22;border-bottom:1px solid #30363d;position:sticky;top:0;z-index:50">
  <div style="max-width:1280px;margin:0 auto;padding:16px 20px">

    <!-- Titolo + contatore -->
    <div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px">
      <div>
        <h1 style="font-size:22px;font-weight:800;color:#e6edf3;letter-spacing:-.02em">
          <span style="color:#f0883e">🇨🇭</span> Lavoro Frontaliero
          <span style="color:#30363d;font-weight:300">·</span>
          <span style="color:#58a6ff">Ticino</span>
        </h1>
        <p style="color:#7d8590;font-size:12px;margin-top:3px">
          Aggiornato il {now}
          {"&nbsp;·&nbsp;<span style='color:#3fb950'>✔ " + str(adatti) + " adatti per te</span>" if adatti else ""}
        </p>
      </div>
      <span style="background:#1f6feb33;color:#58a6ff;border:1px solid #1f6feb;
                   padding:5px 16px;border-radius:999px;font-weight:700;font-size:14px">
        {count} annunci
      </span>
    </div>

    <!-- Filtri -->
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:14px;align-items:center">
      <button onclick="filterJobs('all')" id="btn-all"
        class="filter-btn"
        style="background:#e6edf3;color:#0d1117;border:none;padding:5px 14px;
               border-radius:999px;font-size:12px;font-weight:700;cursor:pointer;
               white-space:nowrap;transition:all .15s">
        Tutti ({count})
      </button>
      {cat_buttons}
      <button onclick="filterAI('adatto')" id="btn-adatto"
        class="filter-btn"
        style="background:#052e16;color:#3fb950;border:1px solid #238636;
               padding:5px 14px;border-radius:999px;font-size:12px;font-weight:600;
               cursor:pointer;white-space:nowrap;transition:all .15s">
        {adatti_label}
      </button>
    </div>

  </div>
</header>

<!-- MAIN -->
<main style="max-width:1280px;margin:0 auto;padding:24px 20px">
  {grid}
</main>

<footer style="text-align:center;padding:40px 20px;color:#484f58;font-size:12px">
  Dati raccolti da jobs.ch · carriera.ch · Gi Group CH · Randstad CH
</footer>

<script>
  const BTN_DEFAULT = {{ bg:'#21262d', color:'#8b949e', border:'1px solid #30363d' }};

  function resetButtons() {{
    document.querySelectorAll('.filter-btn').forEach(b => {{
      if (b.id === 'btn-all') {{
        b.style.background = '#21262d';
        b.style.color = '#8b949e';
        b.style.border = '1px solid #30363d';
      }} else if (b.id === 'btn-adatto') {{
        b.style.background = '#052e16';
        b.style.color = '#3fb950';
        b.style.border = '1px solid #238636';
      }} else {{
        b.style.background = '#21262d';
        b.style.color = '#8b949e';
        b.style.border = '1px solid #30363d';
      }}
    }});
  }}

  function filterJobs(cat) {{
    document.querySelectorAll('.job-card').forEach(c => {{
      c.style.display = (cat === 'all' || c.dataset.category === cat) ? '' : 'none';
    }});
    resetButtons();
    const btn = document.getElementById('btn-' + cat);
    if (btn) {{
      if (cat === 'all') {{
        btn.style.background = '#e6edf3';
        btn.style.color = '#0d1117';
        btn.style.border = 'none';
      }} else {{
        btn.style.background = btn.dataset.activeBg || '#58a6ff';
        btn.style.color = btn.dataset.activeTxt || '#0d1117';
        btn.style.border = 'none';
      }}
    }}
  }}

  function filterAI(val) {{
    document.querySelectorAll('.job-card').forEach(c => {{
      c.style.display = (c.dataset.ai === val) ? '' : 'none';
    }});
    resetButtons();
    const btn = document.getElementById('btn-adatto');
    if (btn) {{
      btn.style.background = '#1a7f37';
      btn.style.color = '#ffffff';
      btn.style.border = 'none';
    }}
  }}
</script>

</body>
</html>
"""

    Path(output_path).write_text(page, encoding="utf-8")
    print(f"[OK] Dashboard generata: {output_path} ({count} annunci)")
