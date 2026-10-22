# Radiografia Studio · Dentalia — istruzioni per chi lavora su questo repository

App web (Flask + SQLAlchemy + Postgres) per i commerciali Dentalia / Consulting Sardegna Srl:
radiografia (check-up) di uno studio dentistico → grafico a ragno → report di azione → preventivo → (in arrivo) contratto.
L'utente (Giancarlo, bogogiancarlo@gmail.com) non è uno sviluppatore: rispondere in italiano, spiegare i passaggi in modo semplice.

## Dove gira
- Repository: github.com/gbservices2018srl-cloud/app-radiografia-studi-dentalia (branch `main`)
- Render, workspace "Giancarlo's workspace" (`tea-d9tjmovqj5pc73fqaevg`)
  - web service `radiografia-studio` (`srv-dau0qkrncjis73aaqrfg`), piano free, region oregon, autodeploy a ogni push su main
  - database `radiografia-db` (`dpg-dau0qabncjis73aapn8g-a`), Postgres 18, **piano free: scade il 29/10/2026 alle 21:10 (ora italiana)** → va fatto l'upgrade (Basic-256mb) entro il 28/10 dal dashboard Render (i tool MCP Render non cambiano il piano)
- URL: https://radiografia-studio.onrender.com — ingresso dal sito: `/area-privata` (porta al login o al pannello)
- Dominio previsto: `area.dentaliagroup.it` (CNAME su Aruba → radiografia-studio.onrender.com + Custom Domain su Render)
- Sito pubblico: www.dentaliagroup.it, sito statico su misura ospitato su Aruba (non su GitHub)

## Struttura
- `app.py` — modelli (Utente, Valutazione, Servizio, Preventivo, Impostazioni), login/ruoli, /admin, radiografie, preventivi, listino, dati aziendali
- `questions.py` — aree/domande/azioni (8 aree × 4 domande, testi DI ESEMPIO, da sostituire con quelli dell'utente); `breve` = etichetta del radar
- `scoring.py` — `calcola(risposte) -> {area_id: 0-100}` (ora media semplice: l'algoritmo vero lo fornirà l'utente) e `livello()` (<50 critico, <75 da migliorare)
- `templates/`, `static/style.css` (variabili colore in testa), `static/brand/` (loghi Dentalia, favicon)
- `demo/index.html` — demo offline per smartphone, file unico con domande incorporate (va riallineata se cambiano le domande)
- `tests/test_app.py` — unittest; GitHub Actions li esegue con SQLite e con Postgres reale

## Regole importanti
- **Schema DB**: `db.create_all()` + `aggiorna_schema()` aggiunge da solo le colonne nuove (ALTER TABLE ADD COLUMN, nullable, senza default). Non rinominare/eliminare colonne senza una migrazione esplicita. I default dei modelli valgono solo per le righe nuove.
- **Driver**: l'URL Postgres va forzato a `postgresql+psycopg2://` (SQLAlchemy 2.1 altrimenti cerca psycopg v3).
- Ruoli: `admin` vede tutto; `commerciale` vede solo i propri dati (`valutazione_visibile`, `preventivo_visibile`). Utenti `approvato=False` = richiesta di accesso in attesa (da /registrati).
- Stato preventivo: chiave interna `inviato` = etichetta "Consegnato" (non cambiare la chiave: ci sono dati salvati).
- Orari salvati in UTC, mostrati con il filtro `ora_locale` (Europe/Rome).
- Brand: blu notte `#062039`, oro `#cca165`, titoli Josefin Sans, testo Inter. Pagine con `noindex`.
- Dati aziendali (Impostazioni id=1): CONSULTING SARDEGNA SRL, Via delle Orchidee 33, 09067 Elmas (CA), P.IVA 04149000921, SDI M5UXCR1, IBAN IT63G0101517400000070889973.
- Prima di ogni push: `python -m unittest discover -s tests -v`; dopo il push controllare GitHub Actions (verde) e il deploy Render (live).

## Lavori in sospeso (in ordine)
1. **Sezione Contratti** (richiesta 22/10): da preventivo "Accettato" → pulsante "Genera contratto"; compilazione automatica con dati azienda + cliente + voci/totali del preventivo + consulente; campi aggiuntivi da compilare = quelli evidenziati in giallo nel modello dell'utente (atteso un .docx con evidenziazioni gialle); firma col dito su smartphone/tablet (canvas) per cliente (ed eventualmente azienda), con data/ora; PDF scaricabile/inviabile; archivio contratti con stato. Ampliare i dati cliente: ragione sociale, P.IVA, CF, indirizzo, CAP, provincia, PEC, SDI, legale rappresentante (+ CF, luogo/data di nascita se servono al modello). Domande aperte all'utente: chi firma (solo cliente o entrambi) e se il cliente firma di persona o tramite link inviato.
2. Algoritmo di analisi reale (`scoring.py`), domande definitive (`questions.py`), listino reale (ora 11 voci di esempio).
3. Collegamento dominio `area.dentaliagroup.it` e voce "Area privata" sul sito Aruba (snippet già fornito all'utente).
4. Valutare piano Starter per il web service (il free si addormenta dopo 15 minuti: primo accesso lento).
