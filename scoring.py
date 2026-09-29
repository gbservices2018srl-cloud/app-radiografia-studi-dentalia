"""
ALGORITMO DI ANALISI  -  segnaposto
-----------------------------------
Qui andrà il tuo algoritmo. L'app chiama solo `calcola(risposte)` e si aspetta
in uscita un dizionario { area_id: punteggio 0-100 }.
Finché qui c'è la versione base, il punteggio è la media delle risposte
dell'area convertita in percentuale (1 = 0%, 5 = 100%).
Puoi aggiungere pesi, correlazioni tra domande, soglie ecc. senza toccare altro.
"""

from questions import AREAS


def calcola(risposte: dict) -> dict:
    punteggi = {}
    for area in AREAS:
        valori = [int(risposte[d["id"]]) for d in area["domande"] if d["id"] in risposte]
        if not valori:
            punteggi[area["id"]] = 0
            continue
        media = sum(valori) / len(valori)
        punteggi[area["id"]] = round((media - 1) / 4 * 100)
    return punteggi


def livello(punteggio: int) -> tuple:
    """Restituisce (etichetta, classe css) per il report."""
    if punteggio < 50:
        return "Critico", "critico"
    if punteggio < 75:
        return "Da migliorare", "medio"
    return "Buono", "buono"
