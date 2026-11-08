"""CHF to EUR exchange rate with a visible source and date.

Two modes:
- "ecb": the daily European Central Bank reference rate, cached for a day.
- "manual": a rate the user types in the settings.
If the ECB cannot be reached, the manual rate is used and the result says so.
"""

import json
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
FX_CACHE_FILE = Path("fx_cache.json")
FX_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
FX_REQUEST_TIMEOUT_SECONDS = 5
FX_MAX_RESPONSE_BYTES = 200_000

FX_MODE_ECB = "ecb"
FX_MODE_MANUAL = "manual"
DEFAULT_MANUAL_EUR_PER_CHF = 1.09
MIN_PLAUSIBLE_EUR_PER_CHF = 0.5
MAX_PLAUSIBLE_EUR_PER_CHF = 2.0

# The ECB quotes how many CHF buy one EUR; the rate is read from a fixed host only.
_CHF_RATE_PATTERN = re.compile(r"currency=['\"]CHF['\"]\s+rate=['\"]([0-9.]+)['\"]")
_DATE_PATTERN = re.compile(r"time=['\"](\d{4}-\d{2}-\d{2})['\"]")


@dataclass(frozen=True)
class FxRate:
    eur_per_chf: float
    source: str
    date: str


def is_plausible_rate(eur_per_chf: float) -> bool:
    return MIN_PLAUSIBLE_EUR_PER_CHF <= eur_per_chf <= MAX_PLAUSIBLE_EUR_PER_CHF


def parse_ecb_xml(xml_text: str) -> FxRate | None:
    """Read the CHF rate from the ECB daily file without using an XML parser."""
    rate_match = _CHF_RATE_PATTERN.search(xml_text)
    date_match = _DATE_PATTERN.search(xml_text)
    if rate_match is None or date_match is None:
        return None
    chf_per_eur = float(rate_match.group(1))
    if chf_per_eur <= 0:
        return None
    eur_per_chf = round(1 / chf_per_eur, 4)
    if not is_plausible_rate(eur_per_chf):
        return None
    return FxRate(eur_per_chf=eur_per_chf, source="ECB reference rate", date=date_match.group(1))


def manual_rate(eur_per_chf: float | None) -> FxRate:
    rate = eur_per_chf
    if rate is None or not is_plausible_rate(rate):
        rate = DEFAULT_MANUAL_EUR_PER_CHF
    return FxRate(eur_per_chf=float(rate), source="manual rate", date="")


def get_fx_rate(mode: str = FX_MODE_ECB, manual_eur_per_chf: float | None = None,
                cache_file: Path = FX_CACHE_FILE) -> FxRate:
    """Return the rate to use. Never raises: falls back to the manual rate."""
    if mode == FX_MODE_MANUAL:
        return manual_rate(manual_eur_per_chf)
    cached_rate = _read_fresh_cache(cache_file)
    if cached_rate is not None:
        return cached_rate
    downloaded_rate = _download_ecb_rate()
    if downloaded_rate is None:
        return manual_rate(manual_eur_per_chf)
    _write_cache(cache_file, downloaded_rate)
    return downloaded_rate


def _download_ecb_rate() -> FxRate | None:
    request = urllib.request.Request(ECB_DAILY_URL, headers={"User-Agent": "JobScraper"})
    try:
        with urllib.request.urlopen(request, timeout=FX_REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 - the URL is a fixed https constant
            body = response.read(FX_MAX_RESPONSE_BYTES)
    except OSError:
        return None
    return parse_ecb_xml(body.decode("utf-8", errors="replace"))


def _read_fresh_cache(cache_file: Path) -> FxRate | None:
    try:
        age_seconds = time.time() - cache_file.stat().st_mtime
        if age_seconds > FX_CACHE_MAX_AGE_SECONDS:
            return None
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        rate = FxRate(float(data["eur_per_chf"]), str(data["source"]), str(data["date"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not is_plausible_rate(rate.eur_per_chf):
        return None
    return rate


def _write_cache(cache_file: Path, rate: FxRate) -> None:
    data = {"eur_per_chf": rate.eur_per_chf, "source": rate.source, "date": rate.date}
    try:
        cache_file.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
