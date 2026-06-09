"""
Analisi AI degli annunci di lavoro tramite Groq (Llama 3.3 70B) — completamente gratuito.

Richiede la variabile d'ambiente GROQ_API_KEY impostata.
Aggiunge a ogni annuncio i campi:
  - llm_adatto     (bool) : True se il lavoro è adatto al profilo
  - llm_motivo     (str)  : breve spiegazione (max ~10 parole)
  - llm_descrizione (str) : 2-3 frasi su cosa si fa concretamente nel lavoro
"""

import os
import json

PROFILO = """
Candidato: Giacomo Negri, 20 anni, Barlassina (MB), Italia.
Titolo di studio: diploma in Informatica e Telecomunicazioni (maturità giugno 2026, istituto Jean Monnet) — primo impiego.
Tipo di lavoro: qualsiasi settore, full time, frontaliero in Ticino (Svizzera). Vuole lavorare in Svizzera per il buon stipendio.
Distanza massima: 35-40 minuti di auto da Barlassina (MB). Ha patente e macchina propria.
Lingue: italiano madrelingua, inglese B1/B2.
Esperienza: 1 mese di stage (PCTO) presso TCR Tecora Srl (Cogliate, MB) — azienda di monitoraggio ambientale:
  - Progetto IoT: sistema controllo umidità con Raspberry Pi 3B+, programmazione in C su Linux (Raspbian)
  - Assemblaggio hardware: saldatura professionale, crimpatura cavi, test con multimetro
  - Assistenza post-vendita: diagnosi guasti, sostituzione componenti elettronici
  - Logistica/spedizioni: imballaggio, pallet in legno, etichettatura consegne internazionali
Hard skills: C, Linux, IoT, Raspberry Pi, saldatura, assemblaggio elettronico, multimetro.
Soft skills: teamwork, autonomia, gestione del tempo.
Disponibile per: QUALSIASI lavoro (IT, logistica, magazzino, pulizie, retail, produzione, assemblaggio, cablaggio, ecc.)
NON adatto SOLO se: richiede laurea magistrale/specialistica, oppure richiede residenza svizzera obbligatoria (permesso C/B richiesto espressamente), oppure richiede 3+ anni di esperienza specifica.
"""


def _chiedi_llm(job: dict) -> dict:
    """Chiama Groq (Llama 3.3 70B) e restituisce il job arricchito."""
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    descrizione = job.get("description", "").strip()
    testo_annuncio = (
        f"Titolo: {job.get('title', '—')}\n"
        f"Azienda: {job.get('company', '—')}\n"
        f"Città: {job.get('city', '—')}\n"
        f"Categoria: {job.get('category', '—')}\n"
        + (f"Descrizione: {descrizione[:800]}" if descrizione else "")
    )

    try:
        risposta = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=500,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Sei un consulente del lavoro italiano. Rispondi SOLO con JSON valido, nessun testo extra.\n"
                        f"Profilo candidato:\n{PROFILO}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Analizza questo annuncio:\n\n{testo_annuncio}\n\n"
                        "Rispondi con questo JSON (tutti i campi obbligatori):\n"
                        "{\n"
                        '  "adatto": true o false,\n'
                        '  "motivo": "max 12 parole: motivo principale per cui è adatto o non adatto",\n'
                        '  "descrizione": "Descrizione completa in 5-7 frasi che spiega: '
                        "(1) cosa si fa ogni giorno nel lavoro (compiti concreti), "
                        "(2) quali competenze o esperienza sono richieste, "
                        "(3) se Giacomo con il suo profilo specifico è in grado di farlo e perché. "
                        'Sii diretto e preciso, evita frasi generiche."\n'
                        "}"
                    ),
                },
            ],
        )
        contenuto = risposta.choices[0].message.content.strip()
        # Rimuove eventuali backtick markdown
        contenuto = contenuto.strip("`").lstrip("json").strip()
        result = json.loads(contenuto)
        job["llm_adatto"]      = bool(result.get("adatto", True))
        job["llm_motivo"]      = str(result.get("motivo", ""))[:120]
        job["llm_descrizione"] = str(result.get("descrizione", ""))[:1000]
    except Exception as e:
        # In caso di errore mantiene l'annuncio visibile senza nota AI
        job["llm_adatto"]      = True
        job["llm_motivo"]      = ""
        job["llm_descrizione"] = ""

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
