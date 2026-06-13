"""
Stima netto mensile per un NUOVO frontaliero italiano in Canton Ticino.

Regime applicabile: Accordo CH-IT 2020 ratificato con L. 83/2023,
in vigore dal 17/07/2023. Giacomo inizia a lavorare dopo tale data → "nuovo frontaliero".

Schema fiscale:
  1. La Svizzera trattiene la Quellensteuer (ritenuta alla fonte federale + cantonale Ticino).
  2. Il lavoratore paga i contributi sociali svizzeri (AVS, AI, AD, LAAINF...).
  3. L'Italia può tassare il reddito con IRPEF, ma:
       - I primi 10.000 CHF/anno sono esenti.
       - Si detrae l'intero credito per imposte pagate in CH.
       - Si applica la detrazione per lavoro dipendente (art. 13 TUIR).

STIMA APPROSSIMATIVA — scostamento ±15-20%.
Dipende da: CCNL applicato, età, contributi volontari, situazione familiare.
Per il calcolo preciso: rivolgersi a un CAF o consulente del lavoro.
"""

CHF_EUR = 0.96   # tasso di cambio indicativo CHF→EUR (aggiorna se necessario)


def _soc_ch(lordo: float) -> float:
    """
    Contributi sociali a carico del dipendente (Svizzera, 2025).
    AVS 5.3 + AI 0.7 + IPG 0.25 + AD 1.1 + LAAINF ~1.2 + LPP rischio ~1.0 = 9.55%
    LPP-risparmio inizia a 25 anni → Giacomo (20 a.) non ha ancora tale quota.
    """
    return lordo * 0.0955


def _quellensteuer_rate(lordo_annuo: float) -> float:
    """
    Aliquota Quellensteuer Ticino 2025 — codice B0 (celibe/nubile, senza figli, no culto).
    Approssimazione delle tabelle cantonali; aliquota marginale effettiva sull'imponibile.
    """
    brackets = [
        (18_000, 0.030), (21_000, 0.045), (24_000, 0.060),
        (27_000, 0.075), (30_000, 0.090), (35_000, 0.100),
        (40_000, 0.110), (45_000, 0.115), (50_000, 0.120),
        (60_000, 0.130), (80_000, 0.145), (100_000, 0.155),
    ]
    for soglia, rate in brackets:
        if lordo_annuo <= soglia:
            return rate
    return 0.170


def _irpef_mensile(lordo_chf: float, qs_mensile_chf: float) -> float:
    """
    IRPEF aggiuntiva mensile da versare in Italia (€) per nuovo frontaliero.
    Logica:
      - Esenzione primi 10.000 CHF/anno → non tassati in Italia.
      - IRPEF lorda su imponibile eccedente (scaglioni 2024).
      - Detrazione lavoro dipendente (art. 13 TUIR 2024, semplificata).
      - Credito d'imposta per Quellensteuer già pagata (proporzionale).
    """
    annuo_chf = lordo_chf * 12
    ESENZIONE = 10_000  # CHF/anno

    imponibile_it_chf = max(0.0, annuo_chf - ESENZIONE)
    imponibile_it_eur = imponibile_it_chf * CHF_EUR

    if imponibile_it_eur <= 0:
        return 0.0

    # IRPEF lorda (scaglioni 2024)
    if imponibile_it_eur <= 28_000:
        irpef = imponibile_it_eur * 0.23
    elif imponibile_it_eur <= 50_000:
        irpef = 6_440 + (imponibile_it_eur - 28_000) * 0.35
    else:
        irpef = 14_140 + (imponibile_it_eur - 50_000) * 0.43

    # Detrazione per lavoro dipendente (art. 13 TUIR, semplificata 2024)
    reddito_eur = annuo_chf * CHF_EUR
    if reddito_eur <= 15_000:
        detrazione = 1_880.0
    elif reddito_eur <= 28_000:
        detrazione = 1_910 - (reddito_eur - 15_000) * 720 / 13_000
    elif reddito_eur <= 50_000:
        detrazione = 1_190 - (reddito_eur - 28_000) * 1_190 / 22_000
    else:
        detrazione = 0.0
    irpef = max(0.0, irpef - detrazione)

    # Credito d'imposta per Quellensteuer (proporzionale alla quota tassabile in IT)
    frazione = imponibile_it_chf / annuo_chf if annuo_chf else 0
    credito   = (qs_mensile_chf * 12) * CHF_EUR * frazione
    irpef     = max(0.0, irpef - credito)

    return irpef / 12   # mensile in EUR


def calcola_netto(lordo_chf: int) -> dict:
    """
    Stima il netto mensile portato a casa in Italia da un nuovo frontaliero
    che lavora in Canton Ticino con stipendio lordo di `lordo_chf` CHF/mese.

    Ritorna:
      lordo_chf   int   stipendio lordo (CHF/mese)
      soc_chf     int   contributi sociali CH carico dipendente
      qs_chf      int   Quellensteuer Ticino (ritenuta alla fonte)
      irpef_eur   int   IRPEF aggiuntiva italiana mensile (€)
      netto_chf   int   netto finale in CHF
      netto_eur   int   netto finale in EUR (≈ portato a casa in Italia)

    Ritorna {} se lordo_chf non è valido.
    """
    if not lordo_chf or lordo_chf <= 0:
        return {}

    soc      = _soc_ch(lordo_chf)
    base_qs  = lordo_chf - soc
    qs_rate  = _quellensteuer_rate(lordo_chf * 12)
    qs       = base_qs * qs_rate
    netto_ch = lordo_chf - soc - qs

    irpef_eur       = _irpef_mensile(lordo_chf, qs)
    irpef_chf       = irpef_eur / CHF_EUR
    netto_finale_chf = netto_ch - irpef_chf
    netto_finale_eur = netto_finale_chf * CHF_EUR

    return {
        "lordo_chf": int(lordo_chf),
        "soc_chf":   int(round(soc)),
        "qs_chf":    int(round(qs)),
        "irpef_eur": int(round(irpef_eur)),
        "netto_chf": int(round(netto_finale_chf)),
        "netto_eur": int(round(netto_finale_eur)),
    }
