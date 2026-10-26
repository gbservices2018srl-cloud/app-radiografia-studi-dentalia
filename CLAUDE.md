# Radiografia Studio · Dentalia — istruzioni per chi lavora su questo repository

App web (Flask + SQLAlchemy + Postgres) per i commerciali Dentalia / Consulting Sardegna Srl:
radiografia (check-up) di uno studio dentistico → grafico a ragno → report di azione → preventivo → (in arrivo) contratto.
L'utente (Giancarlo, bogogiancarlo@gmail.com) non è uno sviluppatore: rispondere in italiano, spiegare i passaggi in modo semplice.

## Dove gira
- Repository: github.com/gbservices2018srl-cloud/app-radiografia-studi-dentalia (branch `main`)
- Render, workspace "Giancarlo's workspace" (`tea-d9tjmovqj5pc73fqaevg`)
  - web service `radiografia-studio-eu` (`srv-dbfja6o473hc73ddc85g`), **Francoforte**, piano 0.5c-512mb (sempre attivo), autodeploy a ogni push su main
  - database `radiografia-db-eu` (`dpg-dbfj82tg1s2s7381c900-a`), **Francoforte**, Postgres 18, piano 0.1c-256mb. IP allowlist vuota (solo rete interna Render): il tool MCP query_render_postgres non lo raggiunge
  - Trasloco da Oregon il 26/10/2026 con `migrazione.py` (variabile MIGRA_DA, già rimossa). Vecchi servizi in Oregon eliminati; Blueprint "App radiografia iniziale studi" scollegato (render.yaml = solo documentazione). `migrazione.py` resta per traslochi futuri
- URL: **https://area.dentaliagroup.it** (Custom Domain su radiografia-studio-eu; CNAME `area` su Aruba → radiografia-studio-eu.onrender.com). Resta valido anche https://radiografia-studio-eu.onrender.com
- Ingresso dal sito: pagina www.dentaliagroup.it/accesso-privato/ (voce "Accesso" col lucchetto nel menu) → `/area-privata` (login o pannello) e `/registrati`
- Sito pubblico: www.dentaliagroup.it, sito statico su misura ospitato su Aruba (non su GitHub)

## Struttura
- `app.py` — modelli (Utente, Valutazione, Servizio, Preventivo, Impostazioni), login/ruoli, /admin, radiografie, preventivi, listino, dati aziendali
- `questions.py` — **domande iniziali** (8 aree × 4 domande di esempio). Le domande in uso stanno nel DB, modello `Questionario` (riga id=1, JSON), modificabili dall'admin in **/admin/domande** (`templates/domande.html`); senza riga valgono quelle di questions.py. Usare sempre `aree_correnti()` (domande attuali) o `aree_di(v)` (domande con cui è stata fatta la radiografia v), mai `AREAS` direttamente
- `Valutazione.questionario` = copia JSON delle aree usate per quella radiografia: i report vecchi non cambiano se le domande cambiano (le radiografie precedenti al 23/10 ricevono all'avvio la copia delle domande iniziali, `fissa_questionario_radiografie()`)
- `Valutazione.note_domande` = JSON {domanda_id: nota}: note interne per domanda (form /nuova, campo `nota_<id>`), mostrate in risultato.html solo nella sezione `.note-interne.no-print` → mai nella stampa/PDF consegnato; visibili solo ad admin e autore (`valutazione_visibile`)
- `scoring.py` — `calcola(risposte, aree) -> {area_id: 0-100}` (ora media semplice: l'algoritmo vero lo fornirà l'utente) e `livello()` (<50 critico, <75 da migliorare)
- `templates/`, `static/style.css` (variabili colore in testa), `static/brand/` (loghi Dentalia, favicon)
- `demo/index.html` — demo offline per smartphone, file unico con domande incorporate (NON segue /admin/domande: va riallineata a mano se serve)
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
2. Algoritmo di analisi reale (`scoring.py`, deve accettare il parametro `aree`), listino reale (ora 11 voci di esempio). Le domande definitive l'utente le inserisce da /admin/domande.
3. ~~Dominio area.dentaliagroup.it e voce sul sito~~ fatto il 23/10/2026.
4. ~~Piani a pagamento e trasloco a Francoforte~~ fatto il 26/10/2026: database 0.1c-256mb (~6 $/mese) e web service 0.5c-512mb (~7 $/mese, non si addormenta).
