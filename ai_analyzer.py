"""AI job analysis through OpenAI (gpt-4o-mini)."""

from __future__ import annotations

import importlib
import json
import os
import re
import time
from typing import Any

# Requires the OPENAI_API_KEY environment variable.
#
# Adds these compatibility keys to each job:
#   llm_adatto             (bool | None) - True/False when analyzed, None on failure
#   llm_motivo             (str)         - short explanation
#   llm_descrizione        (str)         - 4-5 concrete sentences about the job
#   llm_stipendio_lordo    (int | None)  - estimated gross CHF/month

Job = dict[str, Any]
JsonObject = dict[str, Any]

_DELAY_BETWEEN_CALLS = 1.5
_MAX_RETRIES = 4
_RATE_LIMIT_WAIT = 20
_PROFILE_ATTRS = ("CANDIDATE_PROFILE", "PROFILE")
_GENERIC_CANDIDATE_PROFILE = (
    "Generic candidate profile. Evaluate job fit from the job posting and any "
    "candidate details supplied in user_config.py. Do not infer personal details "
    "that are not explicitly provided."
)


class _QuotaExhaustedError(Exception):
    """OpenAI credit is exhausted, so retrying this run is not useful."""


def _load_candidate_profile() -> str:
    try:
        config = importlib.import_module("user_config")
    except ModuleNotFoundError as exc:
        if exc.name == "user_config":
            return _GENERIC_CANDIDATE_PROFILE
        raise

    profile_text = ""
    for attribute_name in _PROFILE_ATTRS:
        profile_text = str(getattr(config, attribute_name, "") or "").strip()
        if profile_text:
            break
    return profile_text or _GENERIC_CANDIDATE_PROFILE


def _build_system_message(candidate_profile: str) -> str:
    return (
        "You are an employment consultant. Return only valid JSON with no extra text.\n"
        "Candidate profile from local user_config.py:\n"
        f"{candidate_profile}"
    )


_CANDIDATE_PROFILE = _load_candidate_profile()
_SYSTEM_MESSAGE = _build_system_message(_CANDIDATE_PROFILE)

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
    suitable = result.get("suitable", result.get("adatto", True))
    reason = result.get("reason", result.get("motivo", ""))
    description = result.get("description", result.get("descrizione", ""))
    gross_salary = result.get("gross_salary", result.get("stipendio_lordo"))

    job["llm_adatto"] = bool(suitable)
    job["llm_motivo"] = str(reason)[:120]
    job["llm_descrizione"] = str(description)[:2000]
    job["llm_stipendio_lordo"] = _valid_gross_salary(gross_salary)


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


def _request_llm_analysis(client: Any, job: Job, job_index: int) -> Job:
    user_content = _USER_PROMPT_TEMPLATE.replace("{job_text}", _job_text(job))
    wait = _RATE_LIMIT_WAIT

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": _SYSTEM_MESSAGE},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                max_tokens=700,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("model returned an empty response")
            _apply_llm_result(job, _decode_model_json(content))
            return job

        except (json.JSONDecodeError, ValueError) as exc:
            if attempt < _MAX_RETRIES:
                print(
                    f"  [LLM] #{job_index} invalid JSON "
                    f"(attempt {attempt}/{_MAX_RETRIES}); retrying."
                )
                time.sleep(2)
            else:
                short_error = str(exc)[:120].replace("\n", " ")
                print(
                    f"  [LLM] #{job_index} JSON error: {short_error}. "
                    "This job will be left unanalyzed and can be retried on the next run."
                )
                break
        except Exception as exc:
            if _is_quota_exhausted(exc):
                raise _QuotaExhaustedError(str(exc)[:200]) from exc
            if _is_rate_limit(exc) and attempt < _MAX_RETRIES:
                print(
                    f"  [LLM] #{job_index} rate-limited "
                    f"(attempt {attempt}/{_MAX_RETRIES}); waiting {wait}s before retry."
                )
                time.sleep(wait)
                wait = min(wait * 2, 120)
            else:
                short_error = str(exc)[:150].replace("\n", " ")
                print(
                    f"  [LLM] #{job_index} API error: {type(exc).__name__}: {short_error}. "
                    "Check the API key, network, and model access before retrying."
                )
                break

    job["llm_adatto"] = None
    job["llm_motivo"] = ""
    job["llm_descrizione"] = ""
    job["llm_stipendio_lordo"] = None
    return job


def _set_defaults(jobs: list[Job]) -> list[Job]:
    for job in jobs:
        job.setdefault("llm_adatto", None)
        job.setdefault("llm_motivo", "")
        job.setdefault("llm_descrizione", "")
        job.setdefault("llm_stipendio_lordo", None)
    return jobs


def analyze_jobs(jobs: list[Job]) -> list[Job]:
    """Analyze jobs with the LLM while preserving the existing public function."""
    if not os.environ.get("OPENAI_API_KEY"):
        print("[LLM] OPENAI_API_KEY is not set; skipping AI analysis. Set it and rerun.")
        return _set_defaults(jobs)

    try:
        from openai import OpenAI
    except ImportError:
        print("[LLM] Package 'openai' is not installed; run 'pip install -r requirements.txt' and rerun.")
        return _set_defaults(jobs)

    if not jobs:
        return jobs

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    pending_count = sum(1 for job in jobs if job.get("llm_adatto") is None)
    if pending_count < len(jobs):
        cached_count = len(jobs) - pending_count
        print(f"[LLM] {cached_count} jobs already analyzed in cache; analyzing {pending_count} missing jobs.")

    estimated_minutes = int(pending_count * _DELAY_BETWEEN_CALLS / 60) + 1
    print(f"[LLM] AI analysis for {pending_count} jobs (estimate: ~{estimated_minutes} min); gpt-4o-mini.")

    analyzed_jobs: list[Job] = []
    try:
        for index, job in enumerate(jobs, start=1):
            if job.get("llm_adatto") is not None:
                analyzed_jobs.append(job)
                continue

            try:
                analyzed_jobs.append(_request_llm_analysis(client, job, index))
            except _QuotaExhaustedError as exc:
                print(f"  [LLM] quota exhausted: {exc}")
                print("  [LLM] Add credit or update billing at platform.openai.com, then rerun with --reanalyze.")
                break

            if index < len(jobs):
                time.sleep(_DELAY_BETWEEN_CALLS)
            if index % 10 == 0 or index == len(jobs):
                successful_count = sum(1 for job in analyzed_jobs if job.get("llm_adatto") is not None)
                print(f"  [LLM] {index}/{len(jobs)}; {successful_count} analyzed successfully.")
    except KeyboardInterrupt:
        print(
            f"\n  [LLM] Interrupted with Ctrl+C after {len(analyzed_jobs)} jobs; "
            "saving partial results."
        )

    if len(analyzed_jobs) < len(jobs):
        analyzed_jobs.extend(_set_defaults(jobs[len(analyzed_jobs) :]))

    suitable_count = sum(1 for job in analyzed_jobs if job.get("llm_adatto") is True)
    unsuitable_count = sum(1 for job in analyzed_jobs if job.get("llm_adatto") is False)
    unanalyzed_count = sum(1 for job in analyzed_jobs if job.get("llm_adatto") is None)
    print(
        f"[LLM] {suitable_count} suitable; "
        f"{unsuitable_count} unsuitable; {unanalyzed_count} unanalyzed."
    )
    return analyzed_jobs
