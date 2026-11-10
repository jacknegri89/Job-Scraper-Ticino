"""Cleaning and language detection for the text of a job description.

A portal page holds more than the listing: login walls, cookie notices, buttons, "similar
jobs". This module removes that furniture so only the text of the listing is stored,
shown and rated. Lines are joined with " | " when stored (see LINE_SEPARATOR).
"""

import re

LINE_SEPARATOR = " | "

# After furniture was removed, less than this (and no real sentence) means nothing of the listing was there.
MIN_USEFUL_CHARS = 80
# Repeated lines are dropped only when they are long enough to be a sentence, not a bullet.
MIN_REPEATED_LINE_CHARS = 12
# A short rest still counts as a listing when one line is a real sentence of at least this size.
MIN_SENTENCE_CHARS = 30
MIN_SENTENCE_WORDS = 5
# How much of a description is read to guess its language.
# 'Company City' header lines sit in the first lines of the text; the city has a few words at most.
HEADER_LINES = 6
MAX_PLACE_WORDS = 4
MAX_HEADER_CHARS = 60
_ROLE_TAGS = frozenset({"per questo ruolo", "for this role", "pour ce poste", "für diese rolle"})
_PLACE_CONNECTORS = frozenset({"di", "del", "della", "sul", "sulla", "in", "e", "al", "d'adda", "sopra", "sotto"})
LANGUAGE_SAMPLE_CHARS = 1500
MIN_LANGUAGE_HITS = 6
LANGUAGE_MARGIN = 1.5

# Whole lines that are buttons, form labels or notices of a portal, in Italian, English,
# German and French. They are compared in lowercase, with straight apostrophes.
_BOILERPLATE_LINE_PATTERNS = tuple(re.compile(pattern) for pattern in (
    # Login walls and sign-up prompts (LinkedIn and similar)
    r"iscriviti o accedi.*", r"iscriviti per salvare.*",
    r"welcome to your professional community", r"sign in with .*", r"by clicking .*", r"continue with .*",
    r"(\d+ \w+ (fa|ago) )?\d+ (candidati|candidature|applicants?)", r"candidati salva", r"apply save",
    r".* ha fornito un livello di retribuzione", r"questo livello . fornito da .*",
    r"invia un messaggio diretto all.autore.*",
    r"send a direct message to the author.*",
    r"explore top linkedin content", r"with the open to work feature.*", r"from live videos.*",
    r"imposta avviso", r"accedi per impostare .*", r"(create|set) (a )?job alert.*", r"sign in to set .*", r"join or sign in.*", r"sign in to (create|set up) .*", r"accedi per (candidarti|ricevere|valutare|personalizzare|vedere|salvare|inviare).*", r"email o telefono", r"password", r"mostra", r"nascondi",
    r"hai dimenticato la password.*", r"accedi con l.email", r"oppure", r"continua",
    r"non hai un account.*", r"cliccando su .*", r"linkedin . parzialmente supportato.*",
    r"registrati( ora| subito| gratis)?", r"crea (un )?account( gratuito)?", r"unisciti ora",
    r"sign in", r"sign in to (apply|continue|view|see|save).*", r"join now", r"join linkedin", r"agree . join.*", r"by clicking continue.*", r"forgot password.*",
    r"email or phone", r"new to linkedin.*", r"log in", r"log in to (apply|continue|view|see|save).*", r"create (an )?account",
    r"anmelden", r"passwort vergessen.*", r"se connecter", r"mot de passe oubli.*",
    # Buttons and counters
    r"candidati( ora)?", r"salva", r"salvato", r"segnala( questa)? offerta.*", r"condividi", r"copia link",
    r"invia candidatura.*", r"candidatura semplice", r"apply( now)?", r"save", r"saved", r"share",
    r"report this job.*", r"easy apply", r"show more", r"show less", r"mostra altro", r"mostra meno",
    r"sii tra i primi \d+ candidati", r"guarda chi . stato assunto.*",
    r"be among the first \d+ applicants", r"see who .* has hired.*",
    r"\d+ (candidati|candidature|applicants?)", r"oltre \d+ candidati", r"over \d+ applicants",
    r"\d+ (minut[io]|or[ae]|giorn[io]|settiman[ae]|mes[ei]) fa",
    r"\d+ (minutes?|hours?|days?|weeks?|months?) ago", r"(reposted )?\d+ (hours?|days?|weeks?) ago",
    r"(pubblicato|publicado|posted|reposted|ripubblicato)( \d+ \w+ fa| \d+ \w+ ago)?",
    # AI helpers and recommendations
    r"usa l.ia per .*", r"ottieni i suggerimenti dell.ia.*", r"il mio profilo . adeguato.*",
    r"personalizza il mio cv", r"use ai to assess.*", r"get ai-powered advice.*",
    r"am i a good fit.*", r"tailor my resume",
    # Similar jobs, alerts, footers
    r"offerte di lavoro simili.*", r"mostra offerte simili.*", r"similar jobs.*", r"imposta un job alert.*",
    r"ottieni notifiche.*", r"altre persone hanno anche cercato.*", r"people also viewed.*",
    r"home / offerte di lavoro.*", r"inserisci la tua email.*",
    r"informativa sulla privacy", r"informativa sui cookie", r"contratto di licenza",
    r"condizioni d.uso", r"centro assistenza", r"linkedin corporation.*", r"(©|\(c\)|copyright) ?\d{4}.*",
    r"user agreement", r"privacy policy", r"cookie policy", r"copyright policy", r"brand policy",
    # Cookie banners
    r"(accetta|rifiuta|gestisci)( tutti)?( i)? cookie( non essenziali| opzionali)?", r"utilizziamo (i )?cookie.*", r"usiamo (i )?cookie.*",
    r"we use cookies.*", r"accept( all)? cookies", r"cookie settings",
))

# Opening words of the lines of a sign-in form; two different ones mean the page is a login wall.
_LOGIN_WALL_MARKERS = (
    "iscriviti o accedi", "hai dimenticato la password", "cliccando su", "non hai un account linkedin",
    "email o telefono", "sign in with email", "welcome to your professional community",
    "by clicking", "join or sign in", "forgot password", "new to linkedin",
)
MIN_LOGIN_WALL_MARKERS = 2

# Lines such as "Seniority level" or "Employment type" are labels of the listing sidebar.
_SIDEBAR_LABELS = frozenset({
    "livello di anzianità", "tipo di impiego", "funzione lavorativa", "settori",
    "seniority level", "employment type", "job function", "industries",
})


def clean_description(text: str, title: str = "", company: str = "") -> str:
    """Return the listing text without page furniture, or "" if nothing useful is left.

    Safe to run again on text that is already clean. A short text that lost nothing is kept
    as it is: only after furniture was removed must what remains be long enough to be a listing.
    """
    lines = _split_lines(text)
    if _is_login_wall_page(lines):
        return ""
    kept_lines: list[str] = []
    seen_long_lines: set[str] = set()
    removed_something = False
    for position, line in enumerate(lines):
        if _is_furniture(line, title, company, position) or _is_repeated(line, seen_long_lines):
            removed_something = True
            continue
        kept_lines.append(line)
    kept_lines = _drop_sidebar_labels(kept_lines)
    cleaned = LINE_SEPARATOR.join(kept_lines)
    if removed_something and len(cleaned) < MIN_USEFUL_CHARS and not _has_sentence(kept_lines):
        return ""
    return cleaned


def _has_sentence(lines: list[str]) -> bool:
    """A line with several words is real text; a leftover name or place is not."""
    return any(len(line) >= MIN_SENTENCE_CHARS and len(line.split()) >= MIN_SENTENCE_WORDS for line in lines)


def _is_login_wall_page(lines: list[str]) -> bool:
    """Text taken from a whole login-wall page: what surrounds the sign-in form cannot be trusted.

    The listing text is read from its own part of the page (see _description_selectors); text
    that still carries the sign-in form was read from the wrong place and is dropped, so the
    next scan reads the page again.
    """
    markers_found = {marker for line in lines for marker in _LOGIN_WALL_MARKERS if _normal(line).startswith(marker)}
    return len(markers_found) >= MIN_LOGIN_WALL_MARKERS


def _is_repeated(line: str, seen_long_lines: set[str]) -> bool:
    if len(line) < MIN_REPEATED_LINE_CHARS:
        return False
    key = line.lower()
    if key in seen_long_lines:
        return True
    seen_long_lines.add(key)
    return False


def shorten(text: str, max_chars: int) -> str:
    """Cut a description at the last whole line that fits, so no sentence ends mid-word."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_separator = cut.rfind(LINE_SEPARATOR)
    if last_separator < max_chars // 2:
        return cut
    return cut[:last_separator]


def description_paragraphs(text: str) -> list[str]:
    """The stored description as separate lines, ready to be shown one per paragraph."""
    return _split_lines(text)


def _split_lines(text: str) -> list[str]:
    raw_text = str(text or "")
    if "\n" in raw_text:
        parts = raw_text.splitlines()
    else:
        parts = raw_text.split(LINE_SEPARATOR)
    return [" ".join(part.split()) for part in parts if part.strip()]


def _normal(line: str) -> str:
    straight = line.replace("’", "'").replace("‘", "'").replace("´", "'").replace("`", "'")
    return " ".join(straight.lower().split()).strip(" .:;!?")


def _is_furniture(line: str, title: str, company: str, position: int) -> bool:
    normal_line = _normal(line)
    if not normal_line:
        return True
    if any(pattern.fullmatch(normal_line) for pattern in _BOILERPLATE_LINE_PATTERNS):
        return True
    if position >= HEADER_LINES:
        return False
    # Only the top of the page repeats the title and the company; the same words later are real text.
    return _repeats_title(normal_line, _normal(title), _normal(company)) or _is_company_header(line, _normal(company))


def _repeats_title(normal_line: str, normal_title: str, normal_company: str) -> bool:
    """LinkedIn repeats 'Title | Company City' at the top of the text; the card shows it already."""
    if not normal_title or not normal_line.startswith(normal_title):
        return False
    rest = normal_line[len(normal_title):].strip(" -|,")
    if not rest:
        return True
    # With words left over it is only a header when the company is named in it, never a sentence about the role.
    return bool(normal_company) and normal_company in rest and len(rest) <= len(normal_company) + MAX_HEADER_CHARS


def _is_company_header(line: str, normal_company: str) -> bool:
    """'Company City' or 'Company per questo ruolo' under the title adds nothing.

    The words after the company must look like a place (capitalized words) or be the
    "for this role" tag: a sentence such as "Acme is hiring" or "Acme è leader" is kept.
    """
    normal_line = _normal(line)
    if not normal_company or not normal_line.startswith(normal_company):
        return False
    rest = line.strip()[len(normal_company):].strip(" -|,")
    if _normal(rest) in _ROLE_TAGS:
        return True
    rest_words = rest.replace(",", " ").split()
    if len(rest_words) > MAX_PLACE_WORDS or len(normal_line) > len(normal_company) + MAX_HEADER_CHARS:
        return False
    return all(word[:1].isupper() or word.lower() in _PLACE_CONNECTORS for word in rest_words)


def _drop_sidebar_labels(lines: list[str]) -> list[str]:
    """Sidebar labels such as 'Seniority level' stand alone and carry no information."""
    return [line for line in lines if _normal(line) not in _SIDEBAR_LABELS]


# ---- language

_STOPWORDS = {
    "it": frozenset(
        "il lo la i gli le un uno una di del della dei delle degli da dal dalla in nel nella con su per tra fra "
        "e ed o ma che non si come sono siamo hai ha hanno essere sei questo questa questi queste nostro nostra "
        "tuo tua suo sua anche più sul alla alle agli al ai cui dove quando se candidato esperienza lavoro "
        "azienda ricerchiamo offriamo requisiti competenze conoscenza".split()),
    "en": frozenset(
        "the a an of to and in is are you your we our with for on as be will this that these those from by or at "
        "have has can not they their it its who which about experience work team role skills ability looking "
        "join strong working years candidate requirements responsibilities".split()),
    "de": frozenset(
        "der die das den dem des ein eine einen einem einer und oder mit für von zu im in ist sind wir sie du "
        "auf als bei nach über wird werden haben hat nicht auch aus durch erfahrung aufgaben kenntnisse "
        "unser unsere ihre ihr team stelle bewerbung".split()),
    "fr": frozenset(
        "le la les un une des du de et ou avec pour dans sur est sont vous nous votre notre au aux par que qui "
        "ce cette ces pas plus expérience poste équipe missions profil compétences entreprise "
        "recherchons".split()),
}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def detect_language(text: str) -> str:
    """Guess "it", "en", "de" or "fr" from common words; "" when it is not clear enough."""
    sample = str(text or "")[:LANGUAGE_SAMPLE_CHARS].lower()
    words = _WORD.findall(sample)
    scores = {language: sum(1 for word in words if word in stopwords) for language, stopwords in _STOPWORDS.items()}
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_language, best_score = ranked[0]
    second_score = ranked[1][1]
    if best_score < MIN_LANGUAGE_HITS:
        return ""
    if best_score < second_score * LANGUAGE_MARGIN:
        return ""
    return best_language
