"""Read seniority and contract type from a listing, with the evidence used.

The rules are deterministic. A title word such as "senior" is only a signal for the
seniority of the role, never a reason to throw the listing away: the user chooses
which levels to see. When the text gives no clear signal the answer is "unknown".
"""

import re

SENIORITY_JUNIOR = "junior"
SENIORITY_MID = "mid"
SENIORITY_SENIOR = "senior"
SENIORITY_MANAGER = "manager"
SENIORITY_UNKNOWN = "unknown"
SENIORITY_LEVELS = (SENIORITY_JUNIOR, SENIORITY_MID, SENIORITY_SENIOR, SENIORITY_MANAGER, SENIORITY_UNKNOWN)

CONTRACT_PERMANENT = "permanent"
CONTRACT_FIXED_TERM = "fixed_term"
CONTRACT_APPRENTICESHIP = "apprenticeship"
CONTRACT_INTERNSHIP = "internship"
CONTRACT_FREELANCE = "freelance"
CONTRACT_TEMP_AGENCY = "temp_agency"
CONTRACT_UNKNOWN = "unknown"
CONTRACT_TYPES = (
    CONTRACT_PERMANENT, CONTRACT_FIXED_TERM, CONTRACT_APPRENTICESHIP, CONTRACT_INTERNSHIP,
    CONTRACT_FREELANCE, CONTRACT_TEMP_AGENCY, CONTRACT_UNKNOWN,
)

# Years of experience asked for: at least this many means senior, this few means junior.
SENIOR_YEARS = 5
MID_YEARS = 3
MAX_JUNIOR_YEARS = 2
_DESCRIPTION_CHARS_READ = 1500

_MANAGER_TITLE = re.compile(
    r"\b(manager|responsabile|head of|direttore|director|capo\s?(?:reparto|progetto|team)|"
    r"team leader|teamleiter|leiter|chief|cto|cio)\b", re.IGNORECASE)
_SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|principal|staff engineer|esperto|(?:tech|technical|team|engineering)\s+lead|"
    r"lead\s+(?:developer|engineer|sviluppatore|programmatore|architect|data|software|devops|qa|analyst))\b",
    re.IGNORECASE)
_JUNIOR_TITLE = re.compile(
    r"\b(junior|jr\.?|entry[\s-]?level|neolaureat\w*|neodiplomat\w*|trainee|graduate|"
    r"apprendist\w*|stagist\w*|tirocin\w*|intern|praktikant\w*|lehrling)\b", re.IGNORECASE)
_MID_TITLE = re.compile(r"\b(mid[\s-]?level|middle|intermediate)\b", re.IGNORECASE)
_YEARS_REQUIRED = re.compile(
    r"(?:almeno|minimo|min\.?|oltre|più di|mindestens|at least|minimum)?\s*(\d{1,2})\s?\+?\s*"
    r"(?:anni|years|jahre)\b[^.|]{0,25}(?:esperienza|experience|erfahrung)", re.IGNORECASE)

_CONTRACT_RULES = (
    (CONTRACT_APPRENTICESHIP, re.compile(r"apprendistato|lehrstelle|apprenticeship", re.IGNORECASE)),
    (CONTRACT_INTERNSHIP, re.compile(r"\bstage\b|tirocinio|internship|praktikum|\bintern\b", re.IGNORECASE)),
    (CONTRACT_TEMP_AGENCY, re.compile(r"somministrazion|interinal|temporary staffing|temporaer|temporär", re.IGNORECASE)),
    (CONTRACT_FREELANCE, re.compile(r"partita iva|p\.\s?iva|freelance|libero professionista|consulenza a progetto", re.IGNORECASE)),
    # "indeterminato" contains "determinato", so the permanent rule must come first.
    (CONTRACT_PERMANENT, re.compile(r"indeterminato|unbefristet|permanent|festanstellung", re.IGNORECASE)),
    (CONTRACT_FIXED_TERM, re.compile(r"\bdeterminato|\bbefristet|fixed[\s-]term", re.IGNORECASE)),
)


def classify_seniority(title: str, description: str = "") -> tuple[str, str]:
    """Return (level, evidence). The title decides; years of experience are a fallback."""
    title_level = _level_from_title(title or "")
    if title_level is not None:
        return title_level
    years_level = _level_from_years((description or "")[:_DESCRIPTION_CHARS_READ])
    if years_level is not None:
        return years_level
    return SENIORITY_UNKNOWN, ""


def _level_from_title(title: str) -> tuple[str, str] | None:
    matches = {
        SENIORITY_MANAGER: _MANAGER_TITLE.search(title),
        SENIORITY_SENIOR: _SENIOR_TITLE.search(title),
        SENIORITY_JUNIOR: _JUNIOR_TITLE.search(title),
        SENIORITY_MID: _MID_TITLE.search(title),
    }
    found = {level: match.group(0) for level, match in matches.items() if match is not None}
    if not found:
        return None
    if SENIORITY_JUNIOR in found and (SENIORITY_SENIOR in found or SENIORITY_MANAGER in found):
        return SENIORITY_UNKNOWN, "title mixes junior and senior words"
    for level in (SENIORITY_MANAGER, SENIORITY_SENIOR, SENIORITY_JUNIOR, SENIORITY_MID):
        if level in found:
            return level, f"title: {found[level]}"
    return None


def _level_from_years(description: str) -> tuple[str, str] | None:
    found = _YEARS_REQUIRED.search(description)
    if found is None:
        return None
    years = int(found.group(1))
    evidence = f"description: {found.group(0).strip()}"
    if years >= SENIOR_YEARS:
        return SENIORITY_SENIOR, evidence
    if years >= MID_YEARS:
        return SENIORITY_MID, evidence
    if years <= MAX_JUNIOR_YEARS:
        return SENIORITY_JUNIOR, evidence
    return None


def classify_contract(title: str, description: str = "") -> str:
    """Return the contract type written in the listing, or 'unknown'."""
    text = f"{title or ''} {(description or '')[:_DESCRIPTION_CHARS_READ]}"
    for contract_type, pattern in _CONTRACT_RULES:
        if pattern.search(text):
            return contract_type
    return CONTRACT_UNKNOWN
