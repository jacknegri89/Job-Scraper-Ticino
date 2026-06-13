"""
Analisi AI degli annunci di lavoro tramite OpenAI (gpt-4o-mini).

Richiede la variabile d'ambiente OPENAI_API_KEY impostata.
Aggiunge a ogni annuncio i campi:
  - llm_adatto      (bool|None) : True/False se analizzato, None se chiamata fallita
  - llm_motivo      (str)       : breve spiegazione (max ~10 parole)
  - llm_descrizione (str)       : 3-4 frasi su cosa si fa concretamente nel lavoro
"""

import os
import re
import json
import time

# gpt-4o-mini Tier 1: 500 RPM → 1 chiamata ogni 1.5s è più che sicuro
_DELAY_BETWEEN_CALLS = 1.5
_MAX_RETRY           = 4
_RATE_LIMIT_WAIT     = 20   # secondi di attesa base al 429 transitorio

PROFILO = """
Giacomo, 20 anni, Barlassina (MB). Cerca lavoro full-time frontaliero Ticino. Primo impiego.
Diploma informatica 2026. Stage: IoT, saldatura, assemblaggio, logistica. Auto propria. EN B1.

NON ADATTO se anche solo uno di questi:
- Richiede laurea (medicina, psicologia, legge, farmacia, fisioterapia, ecc.) o PhD
- Titolo protetto: medico, psicologo, infermiere diplomato/specializzato, farmacista, fisioterapista, ergoterapista, ostetrica, avvocato
- Stage riservato a studenti universitari di discipline specifiche
- Residenza svizzera obbligatoria (permesso B/C esplicito)
- 3+ anni di esperienza specifica richiesta

ADATTO in tutti gli altri casi (operaio, magazzino, pulizie, ristorazione, retail, IT junior, ecc.).
"""

_SYSTEM_MSG = (
    "Sei un consulente del lavoro italiano. Rispondi SOLO con JSON valido, nessun testo extra.\n"
    f"Profilo candidato:\n{PROFILO}"
)

# NB: graffe singole — il riempimento usa .replace(), non .format()
_USER_PROMPT = """\
Analizza questo annuncio di lavoro:

{testo}

Rispondi con questo JSON (tutti i campi obbligatori):
{
  "adatto": true o false,
  "motivo": "max 12 parole: motivo principale. Se adatto: punto di forza (es: lavoro manuale, no laurea, patente B sufficiente). Se non adatto: ostacolo preciso (es: richiede laurea triennale, residenza CH, 5 anni esperienza).",
  "descrizione": "Rispondi con 4-5 frasi CONCRETE e SPECIFICHE:\n1. Cosa si fa fisicamente ogni giorno (azioni, strumenti, macchine, ambienti).\n2. Orari/turni/contratto se visibili nell'annuncio.\n3. Competenze o certificati esplicitamente richiesti.\n4. Perché Giacomo (diploma informatica, stage IoT/saldatura/logistica, neolaureato, frontaliero) è adatto O quale specifica barriera lo esclude.",
  "stipendio_lordo": numero intero CHF/mese stimato (es. 3200) oppure null se non deducibile. Basa la stima sul ruolo, settore e livello entry-level in Canton Ticino. Usa i contratti collettivi svizzeri tipici per il settore.
}"""


class _QuotaEsaurita(Exception):
    """Credito/quota OpenAI esaurito: inutile ritentare, si interrompe l'analisi."""


def _is_quota_exhausted(exc: Exception) -> bool:
    return "insufficient_quota" in str(exc).lower()


def _is_rate_limit(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("429", "rate_limit", "rate limit", "too many"))


def _stipendio_valido(raw) -> int | None:
    """Il modello a volte risponde con null, stringhe o zeri: accetta solo interi > 0."""
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    return None


def _applica_risposta(job: dict, result: dict) -> None:
    """Copia i campi della risposta JSON del modello sull'annuncio."""
    job["llm_adatto"]          = bool(result.get("adatto", True))
    job["llm_motivo"]          = str(result.get("motivo", ""))[:120]
    job["llm_descrizione"]     = str(result.get("descrizione", ""))[:2000]
    job["llm_stipendio_lordo"] = _stipendio_valido(result.get("stipendio_lordo"))


def _testo_annuncio(job: dict) -> str:
    """Testo dell'annuncio passato al modello."""
    descrizione = job.get("description", "").strip()
    righe = (
        f"Titolo: {job.get('title', '—')}\n"
        f"Azienda: {job.get('company', '—')}\n"
        f"Città: {job.get('city', '—')}\n"
        f"Categoria: {job.get('category', '—')}\n"
    )
    if descrizione:
        righe += f"Descrizione completa:\n{descrizione[:1500]}"
    return righe


def _chiedi_llm(client, job: dict, job_idx: int) -> dict:
    user_content = _USER_PROMPT.replace("{testo}", _testo_annuncio(job))

    wait = _RATE_LIMIT_WAIT
    for attempt in range(1, _MAX_RETRY + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": _SYSTEM_MSG},
                    {"role": "user",   "content": user_content},
                ],
                temperature=0.0,
                max_tokens=700,
                response_format={"type": "json_object"},
            )
            contenuto = response.choices[0].message.content
            if not contenuto:
                raise ValueError("risposta vuota dal modello (refusal o filtro contenuti)")
            contenuto = re.sub(r'^```(?:json)?\s*', '', contenuto.strip())
            contenuto = re.sub(r'\s*```$',          '', contenuto).strip()
            _applica_risposta(job, json.loads(contenuto))
            return job

        except json.JSONDecodeError as e:
            if attempt < _MAX_RETRY:
                print(f"  [LLM] #{job_idx} JSON malformato (tent. {attempt}/{_MAX_RETRY}) — riprovo…")
                time.sleep(2)
            else:
                print(f"  [LLM] #{job_idx} ERRORE JSON: {str(e)[:100]}")
                break
        except Exception as e:
            if _is_quota_exhausted(e):
                raise _QuotaEsaurita(str(e)[:200])
            if _is_rate_limit(e) and attempt < _MAX_RETRY:
                print(f"  [LLM] #{job_idx} rate-limit (tent. {attempt}/{_MAX_RETRY})"
                      f" — attendo {wait}s…")
                time.sleep(wait)
                wait = min(wait * 2, 120)
            else:
                short_err = str(e)[:150].replace("\n", " ")
                print(f"  [LLM] #{job_idx} ERRORE: {type(e).__name__}: {short_err}")
                break

    job["llm_adatto"]      = None
    job["llm_motivo"]      = ""
    job["llm_descrizione"] = ""
    return job


def _set_defaults(jobs: list) -> list:
    for job in jobs:
        job.setdefault("llm_adatto",          None)
        job.setdefault("llm_motivo",          "")
        job.setdefault("llm_descrizione",     "")
        job.setdefault("llm_stipendio_lordo", None)
    return jobs


def analyze_jobs(jobs: list) -> list:
    """
    Analizza la lista di annunci con gpt-4o-mini (OpenAI).
    Se OPENAI_API_KEY non è impostata o il pacchetto openai manca,
    restituisce la lista invariata (analisi saltata, dati intatti).
    """
    if not os.environ.get("OPENAI_API_KEY"):
        print("[LLM] OPENAI_API_KEY non trovata — analisi AI saltata.")
        return _set_defaults(jobs)

    try:
        from openai import OpenAI
    except ImportError:
        print("[LLM] Pacchetto 'openai' non installato (python -m pip install openai) — analisi saltata.")
        return _set_defaults(jobs)

    if not jobs:
        return jobs

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    da_fare = sum(1 for j in jobs if j.get("llm_adatto") is None)
    if da_fare < len(jobs):
        print(f"[LLM] {len(jobs) - da_fare} annunci già analizzati in cache — analizzo solo i {da_fare} mancanti.")
    stima = int(da_fare * _DELAY_BETWEEN_CALLS / 60) + 1
    print(f"[LLM] Analisi AI di {da_fare} annunci (stima: ~{stima} min) — gpt-4o-mini…")

    analizzati = []
    try:
        for i, job in enumerate(jobs, start=1):
            # Già analizzato in un run precedente (cache): non ripagare la chiamata
            if job.get("llm_adatto") is not None:
                analizzati.append(job)
                continue
            try:
                analizzati.append(_chiedi_llm(client, job, i))
            except _QuotaEsaurita as e:
                print(f"  [LLM] QUOTA ESAURITA: {e}")
                print("  [LLM] Interrompo l'analisi — gli annunci restanti non vengono analizzati.")
                print("  [LLM] Ricarica il credito su platform.openai.com e rilancia: python scraper.py --reanalyze")
                break
            if i < len(jobs):
                time.sleep(_DELAY_BETWEEN_CALLS)
            if i % 10 == 0 or i == len(jobs):
                ok = sum(1 for j in analizzati if j.get("llm_adatto") is not None)
                print(f"  [LLM] {i}/{len(jobs)} — {ok} analizzati con successo")
    except KeyboardInterrupt:
        print(f"\n  [LLM] Interrotto manualmente (Ctrl+C) dopo {len(analizzati)} annunci — salvo i risultati parziali.")

    # Gli annunci non processati (quota esaurita, Ctrl+C) escono con i default,
    # così la cache resta coerente e --reanalyze riparte da dove si era fermato
    if len(analizzati) < len(jobs):
        analizzati.extend(_set_defaults(jobs[len(analizzati):]))

    adatti     = sum(1 for j in analizzati if j.get("llm_adatto") is True)
    non_adatti = sum(1 for j in analizzati if j.get("llm_adatto") is False)
    non_anal   = sum(1 for j in analizzati if j.get("llm_adatto") is None)
    print(f"[LLM] {adatti} adatti · {non_adatti} non adatti · {non_anal} non analizzati.")
    return analizzati
