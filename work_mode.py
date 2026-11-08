"""Remote and hybrid work, read from the location text first and the listing text second.

The location text ("Remoto in Lomazzo", "Ibrido a Milano") is what portals use on purpose.
The title and description are only trusted for clear statements such as "100% remoto" or
"hybrid". A generic word is never enough: "smart working" alone, "remote" inside a
sentence that denies it, or a company that is "remote-friendly" all leave the mode unknown.
An empty string means "not stated", which is not the same as proof that the job is on site.
"""

import re

import geo

WORK_MODE_UNKNOWN = geo.WORK_MODE_ONSITE
_DESCRIPTION_CHARS_READ = 1500

_REMOTE_STATEMENT = re.compile(
    r"\b(?:100\s?%\s*(?:da\s)?(?:remoto|remote)|full[\s-]?remote|fully[\s-]remote|"
    r"(?:completamente|interamente|totalmente)\s+(?:da\s)?remoto|"
    r"lavoro\s+(?:completamente\s+|interamente\s+|totalmente\s+)?da\s+remoto|"
    r"remote[\s-]only|100\s?%\s*(?:home\s?office|smart\s?working))\b",
    re.IGNORECASE)
_HYBRID_STATEMENT = re.compile(
    r"\b(?:ibrido|ibrida|hybrid|modalit[àa]\s+mista|"
    r"\d\s+giorni\s+(?:a\s+settimana\s+)?(?:in\s+(?:ufficio|sede)|da\s+remoto)|"
    r"\d\s+days\s+(?:a|per)\s+week\s+(?:in\s+the\s+office|remote|from\s+home))\b",
    re.IGNORECASE)
# A denial close to the word: "no remote", "non è previsto lo smart working", "senza telelavoro".
_DENIAL_NEAR_REMOTE = re.compile(
    r"\b(?:no|non|senza|not|without|niente|nessun[oa]?|assenza\s+di|impossibile)\b[^.|;]{0,40}"
    r"\b(?:remot[oae]|remote|smart\s?working|home\s?office|telelavoro|hybrid|ibrid[oa])\b",
    re.IGNORECASE)


# A denial after the word: "remote is not possible", "smart working non previsto".
_DENIAL_AFTER_REMOTE = re.compile(
    r"\b(?:remot[oae]|remote|smart\s?working|home\s?office|telelavoro|hybrid|ibrid[oa])\b[^.|;]{0,40}"
    r"\b(?:not|non|isn't|aren't)\b\s+(?:\w+\s+)?(?:possible|available|allowed|offered|previst[oaie]|possibile|"
    r"disponibile|ammess[oa]|consentit[oa])\b",
    re.IGNORECASE)


def work_mode_of_job(location_text: str, title: str, description: str) -> tuple[str, str]:
    """Return (mode, evidence). Mode is 'remote', 'hybrid' or '' (not stated)."""
    mode_from_location = geo.work_mode_of(location_text)
    if mode_from_location:
        return mode_from_location, f"location: {location_text.strip()[:60]}"
    return work_mode_from_text(f"{title or ''} | {(description or '')[:_DESCRIPTION_CHARS_READ]}")


def work_mode_from_text(text: str) -> tuple[str, str]:
    """Remote or hybrid only when the text says so clearly and does not deny it."""
    if _DENIAL_NEAR_REMOTE.search(text) or _DENIAL_AFTER_REMOTE.search(text):
        return WORK_MODE_UNKNOWN, ""
    hybrid = _HYBRID_STATEMENT.search(text)
    if hybrid is not None:
        return geo.WORK_MODE_HYBRID, f"text: {hybrid.group(0)}"
    remote = _REMOTE_STATEMENT.search(text)
    if remote is not None:
        return geo.WORK_MODE_REMOTE, f"text: {remote.group(0)}"
    return WORK_MODE_UNKNOWN, ""
