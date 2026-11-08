"""Read and write the jobs cache safely.

- Every save goes to a temporary file first and replaces the cache in one step.
- Before the cache is replaced, the previous version is copied to a backup file.
- The first time a cache from before the freshness fields is saved, a one-time backup
  of the original file is kept next to it, so a migration can never lose data.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

from ai_analyzer import normalize_ai_fields
from job_model import normalize_job

CACHE_SCHEMA_VERSION = 2
SCHEMA_FIELD = "schema"
ROLLING_BACKUP_SUFFIX = ".bak"
MIGRATION_BACKUP_SUFFIX = ".pre-v2.bak"


class CacheFormatError(ValueError):
    """The cache file exists but is not a list of jobs."""


def read_raw_jobs(cache_file: Path) -> list[dict]:
    """Read the cache as stored, without changing anything."""
    if not cache_file.exists():
        return []
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    if not isinstance(data, list) or any(not isinstance(job, dict) for job in data):
        raise CacheFormatError(f"Invalid cache format in {cache_file}; the cache was not changed.")
    return data


def load_jobs(cache_file: Path) -> list[dict]:
    """Read the cache and bring every job to the current shape."""
    return [normalize_job(normalize_ai_fields(job)) for job in read_raw_jobs(cache_file)]


def needs_migration(cache_file: Path) -> bool:
    """True when the stored cache still has jobs written before schema 2."""
    try:
        raw_jobs = read_raw_jobs(cache_file)
    except (ValueError, OSError):
        return False
    return any(job.get(SCHEMA_FIELD) != CACHE_SCHEMA_VERSION for job in raw_jobs)


def save_jobs(cache_file: Path, jobs: list[dict]) -> None:
    """Atomically replace the cache, keeping backups of what was there before."""
    stamped_jobs = [{**normalize_ai_fields(job), SCHEMA_FIELD: CACHE_SCHEMA_VERSION} for job in jobs]
    content = json.dumps(stamped_jobs, ensure_ascii=False, indent=2)
    _backup_before_replacing(cache_file)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cache_file.parent,
                                         prefix=".jobs-cache-", suffix=".tmp", delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
        os.replace(temporary_path, cache_file)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


# Caches already backed up by this process. A run saves twice (after the scan and after the
# analysis); the second save must not replace the backup of the previous run with the first.
_BACKED_UP_IN_THIS_RUN: set[Path] = set()


def _backup_before_replacing(cache_file: Path) -> None:
    if not cache_file.exists():
        return
    if needs_migration(cache_file):
        migration_backup = cache_file.with_name(cache_file.name + MIGRATION_BACKUP_SUFFIX)
        if not migration_backup.exists():
            shutil.copy2(cache_file, migration_backup)
    resolved_path = cache_file.resolve()
    if resolved_path in _BACKED_UP_IN_THIS_RUN:
        return
    shutil.copy2(cache_file, cache_file.with_name(cache_file.name + ROLLING_BACKUP_SUFFIX))
    _BACKED_UP_IN_THIS_RUN.add(resolved_path)
