"""Page furniture (login walls, buttons, cookie notices) never ends up in a description."""

import pytest

from description_text import LINE_SEPARATOR, clean_description, description_paragraphs, detect_language, shorten
from job_model import normalize_job

LINKEDIN_WALL = LINE_SEPARATOR.join([
    "Graduate data scientist",
    "Bending Spoons Milano",
    "Candidati",
    "Iscriviti o accedi per trovare il tuo prossimo lavoro",
    "Accedi per candidarti per il ruolo Graduate data scientist presso Bending Spoons",
    "Email o telefono",
    "Password",
    "Mostra",
    "Hai dimenticato la password? Accedi",
    "Accedi con l’email",
    "oppure",
    "Non hai un account LinkedIn? Iscriviti ora",
    "Cliccando su “Continua” per iscriverti o accedere, accetti il Contratto di licenza, "
    "l’Informativa sulla privacy e l’Informativa sui cookie di LinkedIn. LinkedIn è parzialmente "
    "supportato da annunci pubblicitari, il che significa che potremmo utilizzare i tuoi dati per mostrarti "
    "contenuti sponsorizzati e annunci che riteniamo possano interessarti.",
    "8 ore fa",
    "Sii tra i primi 25 candidati",
    "Guarda chi è stato assunto da Bending Spoons per questo ruolo",
])

REAL_TEXT = (
    "Lavorerai con il team dati su modelli di previsione della domanda e pipeline in Python. "
    "Richiesta laurea magistrale in ambito quantitativo."
)


def test_a_page_that_is_only_a_login_wall_has_no_description() -> None:
    assert clean_description(LINKEDIN_WALL, "Graduate data scientist", "Bending Spoons") == ""


def test_the_listing_text_survives_around_buttons_and_a_single_notice() -> None:
    text = LINE_SEPARATOR.join([
        "Graduate data scientist", "Bending Spoons Milano", "Candidati", "Salva", REAL_TEXT,
        "Segnala offerta di lavoro", "Cliccando su Continua accetti le condizioni.",
    ])

    cleaned = clean_description(text, "Graduate data scientist", "Bending Spoons")

    assert cleaned == REAL_TEXT


def test_text_that_still_carries_the_sign_in_form_is_dropped_so_it_is_read_again() -> None:
    text = LINKEDIN_WALL + LINE_SEPARATOR + "Discover relevant posts and expert insights." + LINE_SEPARATOR + "Career"

    assert clean_description(text, "Graduate data scientist", "Bending Spoons") == ""


def test_english_buttons_and_notices_are_removed() -> None:
    text = LINE_SEPARATOR.join([
        "Sign in to apply", "Explore top LinkedIn content", "Show more", "Apply", REAL_TEXT,
    ])

    assert clean_description(text) == REAL_TEXT


def test_the_english_login_wall_is_dropped_as_a_whole() -> None:
    text = LINE_SEPARATOR.join([
        "Welcome to your professional community", "Sign in with email",
        "By clicking “Continue” to join or sign in, you agree to LinkedIn User Agreement, Privacy Policy.",
        REAL_TEXT,
    ])

    assert clean_description(text) == ""


def test_buttons_counters_and_salary_notices_are_removed() -> None:
    text = LINE_SEPARATOR.join([
        "1 giorno fa 77 candidati", "Candidati Salva", "Mavriq ha fornito un livello di retribuzione",
        "Questo livello è fornito da Mavriq. La tua retribuzione effettiva dipende dalle competenze.",
        REAL_TEXT,
    ])

    assert clean_description(text) == REAL_TEXT


def test_a_repeated_line_is_kept_once_but_short_bullets_may_repeat() -> None:
    sentence = "Cerchiamo una persona motivata per il nostro ufficio di Lugano."
    text = LINE_SEPARATOR.join(["Python", sentence, "Python", sentence])

    assert clean_description(text) == LINE_SEPARATOR.join(["Python", sentence, "Python"])


def test_a_short_genuine_description_is_not_thrown_away() -> None:
    assert clean_description("Posizione 100% remoto.") == "Posizione 100% remoto."


def test_a_requirement_that_looks_like_a_button_word_is_not_removed() -> None:
    text = "Registrati all'albo professionale degli ingegneri | Password management con strumenti open source"

    assert clean_description(text) == text


def test_cleaning_twice_changes_nothing() -> None:
    text = LINKEDIN_WALL + LINE_SEPARATOR + REAL_TEXT

    once = clean_description(text, "Graduate data scientist", "Bending Spoons")

    assert clean_description(once, "Graduate data scientist", "Bending Spoons") == once


def _stored_job(description: str) -> dict:
    return {"title": "Graduate data scientist", "company": "Bending Spoons", "city": "Milano", "source": "linkedin.it",
            "url": "https://it.linkedin.com/jobs/view/1", "description": description}


def test_normalizing_a_job_drops_a_description_that_is_a_login_wall() -> None:
    job = normalize_job(_stored_job(LINKEDIN_WALL + LINE_SEPARATOR + REAL_TEXT))

    assert job["description"] == ""


def test_normalizing_a_job_keeps_the_text_of_a_description_with_only_buttons_around_it() -> None:
    job = normalize_job(_stored_job("Candidati" + LINE_SEPARATOR + "Salva" + LINE_SEPARATOR + REAL_TEXT))

    assert job["description"] == REAL_TEXT


def test_paragraphs_are_the_stored_lines() -> None:
    assert description_paragraphs("Uno | Due | Tre") == ["Uno", "Due", "Tre"]
    assert description_paragraphs("") == []


@pytest.mark.parametrize(("text", "language"), [
    ("Cerchiamo una persona con esperienza nello sviluppo di applicazioni per la nostra azienda, che lavori con il team.", "it"),
    ("We are looking for a developer with experience in the cloud, and you will work with our team on the platform.", "en"),
    ("Wir suchen eine Entwicklerin mit Erfahrung in der Cloud und Kenntnisse im Team für unsere Aufgaben.", "de"),
    ("Nous recherchons une personne avec de l'expérience dans le cloud pour notre équipe et les missions du poste.", "fr"),
    ("Python Java Kubernetes", ""),
    ("", ""),
])
def test_language_is_guessed_from_common_words(text: str, language: str) -> None:
    assert detect_language(text) == language


def test_a_long_description_is_cut_at_a_whole_line() -> None:
    lines = ["Prima riga completa del testo.", "Seconda riga completa del testo.", "Terza riga completa del testo."]
    text = LINE_SEPARATOR.join(lines)

    assert shorten(text, 70) == LINE_SEPARATOR.join(lines[:2])
    assert shorten(text, 1000) == text


def test_a_text_without_line_breaks_is_cut_at_the_limit() -> None:
    assert shorten("x" * 100, 40) == "x" * 40


class _FakeElement:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self) -> str:
        return self._text


class _FakePage:
    """A page that answers selectors from a dictionary, as the real page would."""

    def __init__(self, texts_by_selector: dict[str, str], body: str = "") -> None:
        self._texts = texts_by_selector
        self._body = body

    def query_selector(self, selector: str) -> _FakeElement | None:
        if selector in self._texts:
            return _FakeElement(self._texts[selector])
        return None

    def evaluate(self, _script: str) -> str:
        return self._body


def test_the_listing_text_is_read_from_its_own_part_of_the_linkedin_page_not_from_main() -> None:
    from scrapers import _description_text

    listing = "Lavorerai con il team dati su modelli di previsione. " * 4
    page = _FakePage({
        ".show-more-less-html__markup": listing,
        "main": LINKEDIN_WALL.replace(LINE_SEPARATOR, "\n") + "\n" + listing,
    })

    assert _description_text(page) == listing


def test_the_text_read_from_a_page_is_cleaned_before_it_is_stored() -> None:
    from scrapers import _clean_description_text

    page_text = LINKEDIN_WALL.replace(LINE_SEPARATOR, "\n") + "\n" + REAL_TEXT

    # A page that is mostly a login wall leaves nothing: the listing is read again next scan.
    assert _clean_description_text(page_text) == ""
    two_lines = REAL_TEXT.replace(". ", ".\n")
    assert _clean_description_text("Candidati\nSalva\n" + two_lines) == REAL_TEXT.replace(". ", "." + LINE_SEPARATOR)


# ---- real sentences that merely resemble page furniture must survive

LEGITIMATE_LINES = [
    "Candidati con almeno 3 anni di esperienza in Python sono i benvenuti.",
    "Salva i dati in un database PostgreSQL e crea i report per il team.",
    "Mostra capacità di problem solving e attenzione al dettaglio.",
    "Accedi ai sistemi aziendali tramite VPN e gestisci i permessi degli utenti.",
    "Password management e identity access management con strumenti open source.",
    "Condividi le conoscenze con il team e partecipa alle review del codice.",
    "Registrati all'albo professionale degli ingegneri.",
    "Cerchiamo la persona ideale per questo ruolo, con spirito di squadra.",
    "We are hiring the right person for this role and the whole team will support you.",
    "Sign in to Azure Portal and configure the virtual networks for our customers.",
    "Log in to the Linux servers to check the logs and restart the services.",
    "Apply for the certification within the first six months after you join the team.",
    "Gestisci i cookie di sessione e le policy di sicurezza dell'applicazione web.",
    "Oltre 10 anni di esperienza nel settore sono un plus per questa posizione.",
    "Pubblicato il manuale operativo, dovrai mantenerlo aggiornato ogni trimestre.",
]


@pytest.mark.parametrize("line", LEGITIMATE_LINES)
def test_a_real_sentence_that_looks_like_page_furniture_is_kept(line: str) -> None:
    surrounding = LINE_SEPARATOR.join(["Candidati", line, "Salva"])

    assert clean_description(surrounding, "Backend Developer", "Acme") == line
    assert clean_description(line) == line


def test_a_sentence_that_starts_with_the_job_title_or_company_is_kept() -> None:
    text = LINE_SEPARATOR.join([
        "Data Scientist con esperienza in modelli di previsione e forecasting per il retail.",
        "Acme è leader nel settore della logistica e investe nella formazione.",
        "Acme is hiring engineers who like to build reliable systems from scratch.",
    ])

    # Same words in the first lines as the title and company: still sentences, not headers.
    assert clean_description(text, "Data Scientist", "Acme") == text
    assert clean_description(text, "Data Scientist", "") == text


def test_the_title_and_company_header_at_the_top_of_a_linkedin_page_is_removed() -> None:
    text = LINE_SEPARATOR.join([
        "Backend Developer", "Acme Milano", "Acme Sesto San Giovanni", "Acme per questo ruolo",
        "Backend Developer | Acme Milano", REAL_TEXT,
    ])

    assert clean_description(text, "Backend Developer", "Acme") == REAL_TEXT


def test_the_same_words_far_from_the_top_are_not_taken_for_a_header() -> None:
    filler = [f"Riga di descrizione numero {number} con compiti e requisiti del ruolo." for number in range(8)]
    text = LINE_SEPARATOR.join([*filler, "Acme Milano"])

    assert clean_description(text, "Backend Developer", "Acme").endswith("Acme Milano")


def test_the_rest_of_the_listing_text_keeps_its_order_and_paragraphs() -> None:
    lines = [
        "Mansioni principali", "Sviluppo di servizi backend in Python.", "Revisione del codice con il team.",
        "Requisiti", "Laurea in informatica o esperienza equivalente.", "Conoscenza di SQL.",
    ]
    text = LINE_SEPARATOR.join(["Candidati", *lines, "Segnala offerta di lavoro"])

    assert description_paragraphs(clean_description(text)) == lines
