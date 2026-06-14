"""AI job analysis through OpenAI (gpt-4o-mini)."""

from __future__ import annotations

import importlib
import json
import os
import re
import time
from typing import Any

Job = dict[str, Any]
JsonObject = dict[str, Any]

AI_SUITABLE = "ai_suitable"
AI_REASON = "ai_reason"
AI_DESCRIPTION = "ai_description"
AI_GROSS_SALARY = "estimated_gross_salary_chf"

_LEGACY_AI_FIELDS = {
    "llm_adatto": AI_SUITABLE,
    "llm_motivo": AI_REASON,
    "llm_descrizione": AI_DESCRIPTION,
    "llm_stipendio_lordo": AI_GROSS_SALARY,
}
_DELAY_BETWEEN_CALLS = 1.5
_MAX_RETRIES = 4
_RATE_LIMIT_WAIT = 20
_PROFILE_ATTRS = ("CANDIDATE_PROFILE", "PROFILE")
_GENERIC_CANDIDATE_PROFILE = (
    "Generic candidate profile. Evaluate job fit from the job posting and any "
    "candidate details supplied in user_config.py. Do not infer personal details "
    "that are not explicitly provided."
)

_USER_PROMPT_TEMPLATE = """\
Analyze this job posting:

{job_text}

Return this JSON object. All fields are required and values must be in English:
{
  "suitable": true or false,
  "reason": "max 12 words: the main reason. If suitable, state the main strength. If not suitable, state the exact blocker.",
  "description": "Write 4-5 concrete and specific sentences:\n1. What the worker physically does each day, including actions, tools, machines, and environments.\n2. Working hours, shifts, or contract type when visible in the posting.\n3. Explicitly required skills, certificates, or permits.\n4. Why the configured candidate profile fits, or which specific barrier excludes it.",
  "gross_salary": estimated gross CHF/month as an integer (example: 3200), or null if not inferable. Base the estimate on the role, sector, and entry-level pay in Ticino, using common Swiss collective agreements when applicable.
}"""


class _QuotaExhaustedError(Exception):
    """OpenAI credit is exhausted, so retrying this run is not useful."""


def normalize_ai_fields(job: Job) -> Job:
    """Move old cache keys to the current English AI field names."""
    for old_key, new_key in _LEGACY_AI_FIELDS.items():
        if new_key not in job and old_key in job:
            job[new_key] = job[old_key]
        job.pop(old_key, None)
    _set_job_defaults(job)
    return job


def analyze_jobs(jobs: list[Job]) -> list[Job]:
    """Analyze jobs with the LLM and store results in English field names."""
    jobs = [normalize_ai_fields(job) for job in jobs]
    if not _can_analyze_with_ai():
        return jobs

    client = _create_openai_client()
    if client is None or not jobs:
        return jobs

    pending_count = _count_pending_jobs(jobs)
    _print_analysis_start(jobs, pending_count)
    analyzed_jobs = _analyze_pending_jobs(client, jobs)
    _print_summary(analyzed_jobs)
    return analyzed_jobs


def _can_analyze_with_ai() -> bool:
    if not os.environ.get("OPENAI_API_KEY"):
        print("[LLM] OPENAI_API_KEY is not set; skipping AI analysis. Set it and rerun.")
        return False
    return True


def _create_openai_client() -> Any | None:
    try:
        from openai import OpenAI
    except ImportError:
        print("[LLM] Package 'openai' is not installed; run 'pip install -r requirements.txt' and rerun.")
        return None
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def _count_pending_jobs(jobs: list[Job]) -> int:
    return sum(1 for job in jobs if job.get(AI_SUITABLE) is None)


def _print_analysis_start(jobs: list[Job], pending_count: int) -> None:
    cached_count = len(jobs) - pending_count
    if cached_count:
        print(f"[LLM] {cached_count} jobs already analyzed in cache; analyzing {pending_count} missing jobs.")
    estimated_minutes = int(pending_count * _DELAY_BETWEEN_CALLS / 60) + 1
    print(f"[LLM] AI analysis for {pending_count} jobs (estimate: ~{estimated_minutes} min); gpt-4o-mini.")


def _analyze_pending_jobs(client: Any, jobs: list[Job]) -> list[Job]:
    analyzed_jobs: list[Job] = []
    try:
        for index, job in enumerate(jobs, start=1):
            analyzed_jobs.append(_analyze_one_if_needed(client, job, index, len(jobs)))
    except _QuotaExhaustedError as exc:
        print(f"  [LLM] quota exhausted: {exc}")
        print("  [LLM] Add credit or update billing at platform.openai.com, then rerun with --reanalyze.")
    except KeyboardInterrupt:
        print(f"\n  [LLM] Interrupted with Ctrl+C after {len(analyzed_jobs)} jobs; saving partial results.")
    return _append_unprocessed_jobs(analyzed_jobs, jobs)


def _analyze_one_if_needed(client: Any, job: Job, index: int, total_jobs: int) -> Job:
    if job.get(AI_SUITABLE) is not None:
        return job
    analyzed_job = _request_llm_analysis(client, job, index)
    _sleep_between_calls(index, total_jobs)
    _print_progress(index, total_jobs)
    return analyzed_job


def _sleep_between_calls(index: int, total_jobs: int) -> None:
    if index < total_jobs:
        time.sleep(_DELAY_BETWEEN_CALLS)


def _print_progress(index: int, total_jobs: int) -> None:
    if index % 10 != 0 and index != total_jobs:
        return
    print(f"  [LLM] {index}/{total_jobs} processed.")


def _append_unprocessed_jobs(analyzed_jobs: list[Job], jobs: list[Job]) -> list[Job]:
    if len(analyzed_jobs) < len(jobs):
        rest = [normalize_ai_fields(job) for job in jobs[len(analyzed_jobs):]]
        analyzed_jobs.extend(rest)
    return analyzed_jobs


def _request_llm_analysis(client: Any, job: Job, job_index: int) -> Job:
    user_content = _USER_PROMPT_TEMPLATE.replace("{job_text}", _job_text(job))
    wait = _RATE_LIMIT_WAIT
    for attempt in range(1, _MAX_RETRIES + 1):
        result = _try_llm_request(client, job, job_index, user_content, attempt, wait)
        if result is not None:
            return result
        wait = min(wait * 2, 120)
    _mark_unanalyzed(job)
    return job


def _try_llm_request(client: Any, job: Job, job_index: int, user_content: str, attempt: int, wait: int) -> Job | None:
    try:
        content = _call_openai(client, user_content)
        _apply_llm_result(job, _decode_model_json(content))
        return job
    except (json.JSONDecodeError, ValueError) as exc:
        _handle_json_error(job_index, attempt, exc)
    except Exception as exc:
        _handle_api_error(job_index, attempt, wait, exc)
    return None


def _call_openai(client: Any, user_content: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _system_message()},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=700,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("model returned an empty response")
    return content


def _system_message() -> str:
    return (
        "You are an employment consultant. Return only valid JSON with no extra text.\n"
        "Candidate profile from local user_config.py:\n"
        f"{_load_candidate_profile()}"
    )


def _handle_json_error(job_index: int, attempt: int, exc: Exception) -> None:
    if attempt < _MAX_RETRIES:
        print(f"  [LLM] #{job_index} invalid JSON (attempt {attempt}/{_MAX_RETRIES}); retrying.")
        time.sleep(2)
        return
    short_error = str(exc)[:120].replace("\n", " ")
    print(f"  [LLM] #{job_index} JSON error: {short_error}. This job can be retried later.")


def _handle_api_error(job_index: int, attempt: int, wait: int, exc: Exception) -> None:
    if _is_quota_exhausted(exc):
        raise _QuotaExhaustedError(str(exc)[:200]) from exc
    if _is_rate_limit(exc) and attempt < _MAX_RETRIES:
        print(f"  [LLM] #{job_index} rate-limited (attempt {attempt}/{_MAX_RETRIES}); waiting {wait}s.")
        time.sleep(wait)
        return
    short_error = str(exc)[:150].replace("\n", " ")
    print(f"  [LLM] #{job_index} API error: {type(exc).__name__}: {short_error}. Check API access.")


def _load_candidate_profile() -> str:
    try:
        config = importlib.import_module("user_config")
    except ModuleNotFoundError as exc:
        if exc.name == "user_config":
            return _GENERIC_CANDIDATE_PROFILE
        raise
    return _profile_from_config(config)


def _profile_from_config(config: Any) -> str:
    for attribute_name in _PROFILE_ATTRS:
        profile_text = str(getattr(config, attribute_name, "") or "").strip()
        if profile_text:
            return profile_text
    return _GENERIC_CANDIDATE_PROFILE


def _is_quota_exhausted(exc: Exception) -> bool:
    return "insufficient_quota" in str(exc).lower()


def _is_rate_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("429", "rate_limit", "rate limit", "too many"))


def _valid_gross_salary(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    return None


def _apply_llm_result(job: Job, result: JsonObject) -> None:
    job[AI_SUITABLE] = bool(result.get("suitable", True))
    job[AI_REASON] = str(result.get("reason", ""))[:120]
    job[AI_DESCRIPTION] = str(result.get("description", ""))[:2000]
    job[AI_GROSS_SALARY] = _valid_gross_salary(result.get("gross_salary"))


def _job_text(job: Job) -> str:
    description = str(job.get("description") or "").strip()
    lines = (
        f"Title: {job.get('title', '-')}\n"
        f"Company: {job.get('company', '-')}\n"
        f"City: {job.get('city', '-')}\n"
        f"Category: {job.get('category', '-')}\n"
    )
    if description:
        lines += f"Full description:\n{description[:1500]}"
    return lines


def _strip_json_fence(content: str) -> str:
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    return re.sub(r"\s*```$", "", content).strip()


def _decode_model_json(content: str) -> JsonObject:
    parsed = json.loads(_strip_json_fence(content))
    if not isinstance(parsed, dict):
        raise ValueError("model response must be a JSON object")
    return parsed


def _mark_unanalyzed(job: Job) -> None:
    job[AI_SUITABLE] = None
    job[AI_REASON] = ""
    job[AI_DESCRIPTION] = ""
    job[AI_GROSS_SALARY] = None


def _set_job_defaults(job: Job) -> None:
    job.setdefault(AI_SUITABLE, None)
    job.setdefault(AI_REASON, "")
    job.setdefault(AI_DESCRIPTION, "")
    job.setdefault(AI_GROSS_SALARY, None)


def _print_summary(jobs: list[Job]) -> None:
    suitable_count = sum(1 for job in jobs if job.get(AI_SUITABLE) is True)
    unsuitable_count = sum(1 for job in jobs if job.get(AI_SUITABLE) is False)
    unanalyzed_count = sum(1 for job in jobs if job.get(AI_SUITABLE) is None)
    print(f"[LLM] {suitable_count} suitable; {unsuitable_count} unsuitable; {unanalyzed_count} unanalyzed.")
