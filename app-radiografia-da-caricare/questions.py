"""
Struttura del questionario.
Ogni area ha: id, nome, breve (etichetta del grafico), domande (scala 1-5) e azioni suggerite per il report.
Modifica liberamente testi, aree e azioni: il resto dell'app si adatta da solo.
"""

SCALE = [
    (1, "Per nulla / Assente"),
    (2, "Poco"),
    (3, "In parte"),
    (4, "Abbastanza"),
    (5, "Completamente / Ottimo"),
]

AREAS = [
    {
        "id": "clinica",
        "breve": "Clinica",   # etichetta corta per il grafico a ragno
        "nome": "Qualità clinica",
        "domande": [
            {"id": "cl1", "testo": "Esistono protocolli clinici scritti e condivisi per i trattamenti principali?"},
            {"id": "cl2", "testo": "I piani di trattamento sono documentati e spiegati al paziente in modo standard?"},
            {"id": "cl3", "testo": "Vengono monitorati esiti, complicanze e rifacimenti?"},
            {"id": "cl4", "testo": "Il team clinico segue formazione continua pianificata?"},
        ],
        "azioni": [
            "Redigere protocolli scritti per le 5 prestazioni più frequenti.",
            "Introdurre un registro esiti/rifacimenti con revisione mensile.",
            "Pianificare un calendario annuale di formazione ECM per il team.",
        ],
    },
    {
        "id": "marketing",
        "breve": "Marketing",   # etichetta corta per il grafico a ragno
        "nome": "Marketing e acquisizione",
        "domande": [
            {"id": "mk1", "testo": "Lo studio sa da quali canali arrivano i nuovi pazienti?"},
            {"id": "mk2", "testo": "Il sito web e la scheda Google sono aggiornati e curati?"},
            {"id": "mk3", "testo": "Esiste un budget e un piano marketing annuale?"},
            {"id": "mk4", "testo": "Vengono raccolte attivamente recensioni dei pazienti?"},
        ],
        "azioni": [
            "Tracciare la fonte di ogni nuovo paziente già dalla prima telefonata.",
            "Ottimizzare la scheda Google Business e avviare la richiesta sistematica di recensioni.",
            "Definire un piano marketing annuale con budget e obiettivi misurabili.",
        ],
    },
    {
        "id": "esperienza",
        "breve": "Paziente",   # etichetta corta per il grafico a ragno
        "nome": "Esperienza paziente",
        "domande": [
            {"id": "ep1", "testo": "I tempi di attesa in sala sono generalmente sotto i 10 minuti?"},
            {"id": "ep2", "testo": "Viene misurata la soddisfazione del paziente (questionari, NPS)?"},
            {"id": "ep3", "testo": "Il primo contatto telefonico segue uno script / standard?"},
            {"id": "ep4", "testo": "Esiste un sistema di richiamo e follow-up post trattamento?"},
        ],
        "azioni": [
            "Introdurre una survey NPS automatica dopo ogni prestazione.",
            "Scrivere uno script di accoglienza telefonica e formare la segreteria.",
            "Attivare richiami automatici (igiene, controlli) via SMS/WhatsApp.",
        ],
    },
    {
        "id": "economico",
        "breve": "Economia",   # etichetta corta per il grafico a ragno
        "nome": "Gestione economica",
        "domande": [
            {"id": "ec1", "testo": "Lo studio conosce il costo orario della poltrona?"},
            {"id": "ec2", "testo": "Esiste un controllo di gestione mensile (ricavi, costi, margini)?"},
            {"id": "ec3", "testo": "Il tasso di accettazione dei preventivi è misurato?"},
            {"id": "ec4", "testo": "Sono disponibili soluzioni di finanziamento per il paziente?"},
        ],
        "azioni": [
            "Calcolare il costo orario poltrona e rivedere il listino di conseguenza.",
            "Impostare un cruscotto mensile con 5-6 KPI economici.",
            "Monitorare il tasso di accettazione preventivi e formare chi li presenta.",
        ],
    },
    {
        "id": "team",
        "breve": "Team",   # etichetta corta per il grafico a ragno
        "nome": "Team e risorse umane",
        "domande": [
            {"id": "tm1", "testo": "Ruoli e mansioni di ciascuno sono chiari e scritti?"},
            {"id": "tm2", "testo": "Si tengono riunioni di team regolari?"},
            {"id": "tm3", "testo": "Il turnover del personale è basso?"},
            {"id": "tm4", "testo": "Esistono obiettivi individuali o sistemi incentivanti?"},
        ],
        "azioni": [
            "Formalizzare un mansionario per ogni ruolo.",
            "Introdurre una riunione di team settimanale di 30 minuti con ordine del giorno.",
            "Definire obiettivi individuali e colloqui di valutazione semestrali.",
        ],
    },
    {
        "id": "organizzazione",
        "breve": "Agenda",   # etichetta corta per il grafico a ragno
        "nome": "Organizzazione e agenda",
        "domande": [
            {"id": "or1", "testo": "Il tasso di saturazione delle poltrone è misurato?"},
            {"id": "or2", "testo": "Gli appuntamenti mancati (no-show) sono sotto controllo?"},
            {"id": "or3", "testo": "L'agenda è pianificata per tipologia di prestazione?"},
            {"id": "or4", "testo": "Magazzino e ordini dei materiali seguono una procedura?"},
        ],
        "azioni": [
            "Misurare saturazione poltrone e no-show ogni settimana.",
            "Introdurre promemoria automatici 48h e 24h prima dell'appuntamento.",
            "Riorganizzare l'agenda a blocchi per tipologia di prestazione.",
        ],
    },
    {
        "id": "digitale",
        "breve": "Digitale",   # etichetta corta per il grafico a ragno
        "nome": "Tecnologia e digitale",
        "domande": [
            {"id": "dg1", "testo": "Lo studio usa un gestionale integrato (agenda, cartella, fatturazione)?"},
            {"id": "dg2", "testo": "La cartella clinica è completamente digitale?"},
            {"id": "dg3", "testo": "Il paziente può prenotare o comunicare online?"},
            {"id": "dg4", "testo": "Vengono usate tecnologie diagnostiche digitali (scanner, CBCT)?"},
        ],
        "azioni": [
            "Valutare un gestionale unico che integri agenda, cartella e fatturazione.",
            "Attivare prenotazione online e canale di messaggistica con i pazienti.",
            "Pianificare investimenti in diagnostica digitale con analisi di ritorno.",
        ],
    },
    {
        "id": "compliance",
        "breve": "Compliance",   # etichetta corta per il grafico a ragno
        "nome": "Compliance e sicurezza",
        "domande": [
            {"id": "co1", "testo": "Privacy (GDPR) e consensi informati sono gestiti correttamente?"},
            {"id": "co2", "testo": "Le procedure di sterilizzazione sono tracciate?"},
            {"id": "co3", "testo": "Gli adempimenti su sicurezza e radioprotezione sono aggiornati?"},
            {"id": "co4", "testo": "Esiste un calendario delle scadenze normative?"},
        ],
        "azioni": [
            "Eseguire un audit GDPR e aggiornare i moduli di consenso.",
            "Introdurre la tracciabilità completa dei cicli di sterilizzazione.",
            "Creare uno scadenzario normativo con responsabile designato.",
        ],
    },
]
