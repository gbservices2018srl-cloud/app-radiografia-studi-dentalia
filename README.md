# Radiografia Studio · Dentalia

Check-up iniziale di uno studio dentistico: questionario per aree → grafico a ragno → report di azione. Le valutazioni vengono salvate nel database.

## Accesso e ruoli

- **Amministratore**: vede tutte le valutazioni, filtra per commerciale, crea/disattiva i commerciali e ne reimposta la password (menu → *Commerciali*).
- **Pannello /admin**: attivazione delle richieste di accesso, creazione/disattivazione account, numeri per commerciale.
- **Commerciale**: vede e crea solo le proprie valutazioni. Il suo nome, telefono ed email compaiono sul report consegnato al cliente.

Il primo amministratore viene creato automaticamente al primo avvio con le variabili `ADMIN_EMAIL` e `ADMIN_PASSWORD`
(in locale, se non impostate: `admin@example.com` / `admin123` — da cambiare subito da *Cambia password*).

## Preventivi

- **Listino servizi** (menu → *Listino servizi*, solo admin): ogni servizio si collega a un'area della radiografia.
- **Crea preventivo da un report**: dal report della radiografia → *Crea preventivo da questo report*. Compare il pannello
  *Voci suggerite dalla radiografia* con le aree ordinate dalla più critica: spunti le voci e finiscono nel preventivo
  (quelle delle aree sotto 75 sono già selezionate). Puoi aggiungere altre voci dal listino o voci libere.
- Sconto per riga e sconto globale, IVA per riga (predefinita 22%), totali calcolati in tempo reale.
- **Archivio** (scheda *Preventivi*): ricerca, filtro per stato e per commerciale, totali per stato, duplicazione.
  Numerazione automatica per anno (2026/001, 2026/002…).
- **Stampa**: pagina A4 con intestazione aziendale, dati del consulente, spazio firme → *Stampa / Salva PDF*.
- **Dati aziendali** (menu → *Dati aziendali*, solo admin): ragione sociale, P. IVA, IBAN, condizioni predefinite.

Al primo avvio il listino viene precaricato con servizi di esempio: modificali con i tuoi prezzi reali.

## Versione dimostrativa per smartphone

`demo/index.html` è un file unico che funziona senza server: aprilo sul telefono (o pubblicalo su GitHub Pages)
per mostrare l'app ai clienti. I dati restano solo su quel dispositivo e non c'è login: per l'uso reale serve la versione online.
Se modifichi le domande in `questions.py`, ricorda di aggiornarle anche nel file demo (sezione `DATI`).

## Brand

Logo e palette Dentalia sono in `static/brand/` (logo completo, simbolo, scritta, versioni bianche, favicon)
e nelle variabili colore in cima a `static/style.css`: blu notte `#062039`, oro `#cca165`.
Per cambiare un colore in tutta l'app basta modificarlo lì.

## Struttura

| File | Cosa contiene |
|---|---|
| `questions.py` | Aree, domande e azioni suggerite. **Si modifica qui il questionario.** |
| `scoring.py` | Algoritmo di analisi (`calcola`) e soglie (`livello`). **Qui va il tuo algoritmo.** |
| `app.py` | Pagine web, login, database |
| `demo/index.html` | Versione dimostrativa offline per smartphone |
| `templates/`, `static/` | Grafica |
| `render.yaml` | Configurazione per Render (web app + database Postgres) |

## Provare in locale

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Apri http://127.0.0.1:5000 . In locale i dati vanno in un file SQLite (`instance/radiografia.db`).

## Mettere online (GitHub + Render)

1. Crea un repository su GitHub e carica questi file:
   ```bash
   git init && git add . && git commit -m "Prototipo radiografia studio"
   git branch -M main
   git remote add origin https://github.com/TUO-UTENTE/radiografia-studio.git
   git push -u origin main
   ```
2. Su render.com → **New → Blueprint** → collega il repository.
   Render legge `render.yaml` e crea da solo la web app e il database Postgres.
   Durante la creazione ti chiede `ADMIN_EMAIL` e `ADMIN_PASSWORD`: sono le credenziali del tuo primo accesso.
3. A ogni `git push` Render ripubblica automaticamente.

> Nota: il database Postgres gratuito di Render scade dopo 30 giorni. Per conservare i dati in modo stabile passa al piano a pagamento del database (pochi euro al mese).

## Test automatici

A ogni `git push` GitHub esegue i test in `tests/` (scheda **Actions** del repository: spunta verde = tutto ok).
In locale: `python -m unittest discover -s tests -v`

## Inserire il tuo algoritmo

L'app chiama solo `calcola(risposte)` in `scoring.py`.
- **Input**: `{"cl1": "4", "cl2": "2", ...}` (id domanda → valore 1-5)
- **Output**: `{"clinica": 62, "marketing": 38, ...}` (id area → punteggio 0-100)

Finché rispetti questo formato puoi aggiungere pesi, correlazioni tra domande, penalità ecc. senza toccare il resto.
