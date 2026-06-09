"""
Analisi AI degli annunci di lavoro tramite Groq (Llama 3.3 70B) — completamente gratuito.

Richiede la variabile d'ambiente GROQ_API_KEY impostata.
Aggiunge a ogni annuncio i campi:
  - llm_adatto  (bool)  : True se il lavoro è adatto al profilo
  - llm_motivo  (str)   : breve spiegazione (max ~10 parole)
"""

import os
import json

PROFILO = """
Candidato: Giacomo Negri, 20 anni.
Titolo di studio: diploma IT (istituto Jean Monnet, giugno 2026) — primo impiego.
Tipo di lavoro cercato: frontaliero in Ticino (Svizzera), Mendrisiotto.
Competenze: informatica di base (diploma tecnico), nessuna esperienza lavorativa significativa.
Disponibile per: tech/IT junior, logistica, pulizie, retail, lavori manuali generici.
NON adatto: lavori che richiedono anni di esperienza, laurea specialistica, residenza svizzera obbligatoria.
"""


def _chiedi_llm(job: dict) -> dict:
    """Chiama Groq (Llama 3.3 70B) e restituisce il job arricchito."""
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    testo_annuncio = (
        f"Titolo: {job.get('title', '—')}\n"
        f"Azienda: {job.get('company', '—')}\n"
        f"Città: {job.get('city', '—')}\n"
        f"Categoria: {job.get('category', '—')}"
    )

    try:
        risposta = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=80,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Sei un consulente del lavoro italiano.\n"
                        f"Profilo candidato:\n{PROFILO}\n"
                        "Rispondi SOLO con JSON valido, nessun testo extra."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Questo annuncio è adatto al candidato?\n\n{testo_annuncio}\n\n"
                        'Rispondi con: {"adatto": true/false, "motivo": "max 10 parole in italiano"}'
                    ),
                },
            ],
        )
        contenuto = risposta.choices[0].message.content.strip()
        # Rimuove eventuali backtick markdown
        contenuto = contenuto.strip("`").lstrip("json").strip()
        result = json.loads(contenuto)
        job["llm_adatto"] = bool(result.get("adatto", True))
        job["llm_motivo"] = str(result.get("motivo", ""))[:120]
    except Exception as e:
        # In caso di errore mantiene l'annuncio visibile senza nota AI
        job["llm_adatto"] = True
        job["llm_motivo"] = ""

    return job


def analyze_jobs(jobs: list) -> list:
    """
    Analizza la lista di annunci con Llama 3.3 70B su Groq (gratuito).
    Se GROQ_API_KEY non è impostata, restituisce la lista invariata.
    """
    if not os.environ.get("GROQ_API_KEY"):
        print("[LLM] GROQ_API_KEY non trovata — analisi AI saltata.")
        return jobs

    if not jobs:
        return jobs

    print(f"[LLM] Analisi AI di {len(jobs)} annunci con Llama 3.3 70B (Groq)…")

    analizzati = []
    for i, job in enumerate(jobs, start=1):
        analizzati.append(_chiedi_llm(job))
        if i % 10 == 0 or i == len(jobs):
            print(f"[LLM] {i}/{len(jobs)} analizzati…")

    adatti = sum(1 for j in analizzati if j.get("llm_adatto", True))
    print(f"[LLM] Risultato: {adatti}/{len(analizzati)} annunci adatti al tuo profilo.")
    return analizzati
