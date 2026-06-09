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
