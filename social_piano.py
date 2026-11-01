"""
Piano editoriale iniziale dei social Dentalia: da qui l'agente prende i post, a rotazione per tema.
Ogni idea: tema, scena della grafica (vedi grafica_social.py), titolo (le *parole* tra asterischi
diventano oro), testo o punti, foto (solo per la scena «foto») e didascalia del post.
Le idee usate restano registrate (SocialPost.idea) e non si ripetono finché non sono finite tutte.
Le idee aggiunte da /gestione/idee si sommano a queste.
"""

HASHTAG = "#Dentalia #StudioDentistico #Odontoiatria #GestioneStudio #Dentisti"

LINEA_BASE = """Chi siamo: Dentalia, un network di studi dentistici indipendenti che crescono insieme (Consulting Sardegna Srl).
A chi parliamo: titolari di studi dentistici, soprattutto in Sardegna.
Tono: diretto, concreto, da collega esperto. Niente promesse esagerate, niente numeri inventati.
Ogni post: una sola idea pratica + un invito leggero (colloquio di valutazione o sito).
Temi a rotazione: sviluppo commerciale, organizzazione, numeri, personale, acquisti, formazione, network, colloquio di valutazione.
Da evitare: prezzi, nomi di pazienti, foto di pazienti, confronti con altri studi, linguaggio medico sulle cure."""

TEMI = ["Sviluppo commerciale", "Organizzazione", "Numeri", "Personale", "Acquisti", "Formazione", "Il network",
        "Colloquio di valutazione"]

IDEE = [
    # ---- Sviluppo commerciale
    {"id": "comm-cassetto", "tema": "Sviluppo commerciale", "scena": "titolo",
     "titolo": "Il denaro che il tuo studio ha *già guadagnato* e non incassa",
     "testo": "Sta nel cassetto dei preventivi non accettati.",
     "didascalia": """Ogni studio ha un cassetto pieno di preventivi «ci penso».

Pazienti che hanno già scelto te una volta, hanno ricevuto un piano di cura e non sono più tornati.

Prova questo conto: somma il valore dei preventivi non accettati degli ultimi sei mesi. Poi chiediti quanto varrebbe recuperarne uno su quattro.

Quasi sempre il problema non è il paziente: è che nessuno nello studio ha il compito preciso di richiamarlo, con un metodo.

👉 È una delle prime cose che guardiamo nella radiografia dello studio.

""" + HASHTAG + " #Preventivi"},
    {"id": "comm-chi-richiama", "tema": "Domanda della settimana", "scena": "domanda",
     "titolo": "Chi richiama i pazienti che hanno detto *«ci penso»*?",
     "testo": "Se la risposta è «chi ha tempo», non lo fa nessuno.",
     "didascalia": """Domanda secca, risposta sincera: nel tuo studio chi richiama i pazienti che non hanno accettato il preventivo? E quando?

Se la risposta è «chi ha tempo», in pratica non lo fa nessuno. E ogni settimana un pezzo di lavoro già fatto (visita, piano di cura, spiegazione) va perso.

Bastano tre cose: una persona incaricata, un giorno fisso, poche frasi preparate.

Scrivici nei commenti come lo gestite voi 👇

""" + HASHTAG},
    {"id": "comm-3-passi", "tema": "Sviluppo commerciale", "scena": "lista",
     "titolo": "Un preventivo accettato *in 3 passi*",
     "punti": ["Spiegalo seduto, non in piedi alla reception", "Dai un'opzione di pagamento chiara",
               "Fissa subito il richiamo se il paziente vuole pensarci"],
     "didascalia": """Tre abitudini semplici che cambiano il tasso di accettazione dei preventivi:

1️⃣ Il piano di cura si spiega seduti, con calma, non al banco mentre arriva il paziente dopo.
2️⃣ Il paziente deve uscire sapendo come può pagare, non solo quanto.
3️⃣ Se dice «ci penso», si fissa già la data in cui lo richiamerete.

Niente tecniche di vendita: solo rispetto per il tempo del paziente e per il lavoro del dentista.

""" + HASHTAG + " #Preventivi"},
    # ---- Organizzazione
    {"id": "org-agenda", "tema": "Organizzazione", "scena": "titolo",
     "titolo": "Un'agenda piena *non è* un'agenda che rende",
     "testo": "Conta come sono distribuite le ore, non solo quante sono occupate.",
     "didascalia": """«Siamo pieni per tre settimane» sembra una buona notizia. Non sempre lo è.

Un'agenda può essere piena di appuntamenti brevi, controlli e buchi da 20 minuti, e lasciare poco spazio alle cure che sostengono davvero lo studio.

Prova a guardare l'ultima settimana e a dividere le ore in: prime visite, cure, controlli, tempi morti. Il quadro che esce è spesso sorprendente.

👉 L'organizzazione è una delle 6 aree della radiografia Dentalia.

""" + HASHTAG + " #Organizzazione"},
    {"id": "org-mattina", "tema": "Organizzazione", "scena": "lista",
     "titolo": "La riunione di 10 minuti *che salva la giornata*",
     "punti": ["Chi arriva oggi e per cosa", "Cosa serve pronto in ogni studio",
               "Quali pazienti richiamare", "Chi fa cosa in caso di ritardi"],
     "didascalia": """Dieci minuti prima di aprire, tutto il team in piedi, sempre alla stessa ora.

Si guarda l'agenda del giorno, si prepara quello che serve, si decide chi richiama chi e come si gestisce un ritardo.

Sembra poco. È la differenza tra rincorrere la giornata e guidarla.

""" + HASHTAG + " #TeamWork"},
    {"id": "org-domanda-tempo", "tema": "Domanda della settimana", "scena": "domanda",
     "titolo": "Quante ore a settimana passi su cose *che non sono la poltrona*?",
     "didascalia": """Fornitori, turni, fatture, telefonate, problemi del computer...

Molti titolari ci raccontano che metà della loro energia va in cose che non sono il loro lavoro di dentista.

Non si elimina tutto, ma quasi tutto si può organizzare o delegare.

Tu quante ore ci passi? 👇

""" + HASHTAG},
    # ---- Numeri
    {"id": "num-3", "tema": "Numeri", "scena": "lista",
     "titolo": "3 numeri che ogni titolare *deve sapere*",
     "punti": ["Quanto costa un'ora di poltrona", "Quanti preventivi vengono accettati",
               "Quanto pesano i materiali sul fatturato"],
     "didascalia": """Se dovessi rispondere adesso, senza aprire nessun programma, sapresti dire questi tre numeri?

📌 quanto ti costa davvero un'ora di poltrona
📌 quanti preventivi su dieci vengono accettati
📌 quanto spendi in materiali rispetto a quanto fatturi

Non serve un gestionale complicato. Serve guardarli una volta al mese, sempre gli stessi.

""" + HASHTAG + " #Numeri"},
    {"id": "num-ora-poltrona", "tema": "Numeri", "scena": "titolo",
     "titolo": "Senza il costo dell'ora di poltrona *ogni sconto è una scommessa*",
     "didascalia": """Affitto, personale, macchinari, materiali, consulenti: dividi tutto per le ore in cui lo studio lavora davvero.

Quel numero è il punto di partenza di ogni scelta: i prezzi, gli sconti, quanto tempo dare a un appuntamento, se conviene un nuovo collaboratore.

Senza, si decide a sensazione.

👉 Nella radiografia dello studio è uno dei primi numeri che calcoliamo insieme.

""" + HASHTAG + " #Numeri"},
    {"id": "num-domanda", "tema": "Domanda della settimana", "scena": "domanda",
     "titolo": "Il mese scorso il tuo studio *ha guadagnato* o ha solo fatturato?",
     "didascalia": """Fatturato e guadagno non sono la stessa cosa. Sembra ovvio, eppure molti studi guardano solo il primo.

Una volta al mese bastano 30 minuti per mettere a confronto entrate e uscite vere.

Tu lo fai? 👇

""" + HASHTAG + " #Numeri"},
    # ---- Personale
    {"id": "pers-ruoli", "tema": "Personale", "scena": "titolo",
     "titolo": "Quando tutti fanno tutto, *nessuno è responsabile* di niente",
     "testo": "Ruoli chiari = meno errori, meno tensioni, più tempo per i pazienti.",
     "didascalia": """In molti studi la segreteria risponde al telefono, ordina i materiali, richiama i pazienti, fa le fatture... quando c'è tempo.

Il risultato? Le cose urgenti vengono fatte, quelle importanti no.

Scrivere su un foglio chi è responsabile di cosa è un esercizio di un'ora che cambia il clima dello studio.

""" + HASHTAG + " #Personale #TeamWork"},
    {"id": "pers-foto-team", "tema": "Personale", "scena": "foto", "foto": "foto-camice-member.jpg",
     "titolo": "Il team è il primo *biglietto da visita* dello studio",
     "didascalia": """Prima del dentista, il paziente incontra la voce al telefono e il sorriso alla reception.

Investire sul personale (formazione, ruoli chiari, riconoscimento) è uno dei modi più concreti per far crescere lo studio.

👉 Il personale è una delle 6 aree che analizziamo nella radiografia Dentalia.

""" + HASHTAG + " #Personale"},
    {"id": "pers-lista", "tema": "Personale", "scena": "lista",
     "titolo": "3 segnali che il team *ha bisogno di te*",
     "punti": ["Le stesse domande ti arrivano ogni giorno", "Gli errori si ripetono uguali",
               "Nessuno propone più miglioramenti"],
     "didascalia": """Non sono problemi di persone: quasi sempre sono problemi di organizzazione e di comunicazione.

Una procedura scritta, una riunione breve fissa e un momento per ascoltare le proposte del team risolvono più di quanto si pensi.

""" + HASHTAG + " #Personale"},
    # ---- Acquisti
    {"id": "acq-potere", "tema": "Acquisti", "scena": "titolo",
     "titolo": "Da solo compri *come uno studio*. Insieme compri come un gruppo",
     "testo": "La differenza spesso non sta nella qualità, ma nel potere d'acquisto.",
     "didascalia": """Gli stessi materiali, gli stessi fornitori, prezzi diversi. Perché?

Perché chi compra per tanti studi tratta in un altro modo. È uno dei vantaggi concreti di un network: restare indipendenti, ma acquistare insieme.

👉 Gli acquisti sono una delle 6 aree della radiografia Dentalia.

""" + HASHTAG + " #Acquisti"},
    {"id": "acq-domanda", "tema": "Domanda della settimana", "scena": "domanda",
     "titolo": "Quando hai *confrontato i prezzi* dei tuoi fornitori l'ultima volta?",
     "didascalia": """Molti studi lavorano con gli stessi fornitori da anni, per fiducia e per comodità. Va benissimo.

Ma una volta all'anno vale la pena fare un confronto serio, voce per voce, sui 20 prodotti che usi di più.

Tu quando l'hai fatto l'ultima volta? 👇

""" + HASHTAG + " #Acquisti"},
    {"id": "acq-lista", "tema": "Acquisti", "scena": "lista",
     "titolo": "Magazzino in ordine *in 3 mosse*",
     "punti": ["Una persona sola responsabile degli ordini", "Scorte minime scritte per ogni prodotto",
               "Ordini in giorni fissi, non all'ultimo"],
     "didascalia": """Ordini urgenti, prodotti scaduti, doppioni nell'armadio: il disordine in magazzino costa più di quanto sembri.

Tre regole semplici bastano a cambiare le cose. Le avete già nel vostro studio?

""" + HASHTAG + " #Acquisti #Organizzazione"},
    # ---- Formazione
    {"id": "form-titolo", "tema": "Formazione", "scena": "titolo",
     "titolo": "Ti sei formato per curare. *Nessuno* ti ha insegnato a gestire",
     "testo": "Gestire uno studio è un mestiere a parte. Si può imparare.",
     "didascalia": """L'università prepara ottimi clinici. Ma il giorno in cui apri uno studio diventi anche imprenditore, responsabile del personale, ufficio acquisti e commerciale.

Nessuno nasce sapendolo fare, e non c'è niente di male a farsi aiutare.

👉 La formazione (tua e del team) è una delle 6 aree della radiografia Dentalia.

""" + HASHTAG + " #Formazione"},
    {"id": "form-segreteria", "tema": "Formazione", "scena": "lista",
     "titolo": "Cosa insegnare *per prima cosa* alla segreteria",
     "punti": ["Come rispondere a chi chiede solo il prezzo", "Come fissare il richiamo dei preventivi",
               "Come gestire un paziente arrabbiato"],
     "didascalia": """La segreteria è la prima e l'ultima persona che il paziente incontra. Tre situazioni che vale la pena preparare insieme, con frasi semplici e condivise da tutto il team.

""" + HASHTAG + " #Formazione #Personale"},
    # ---- Il network
    {"id": "net-reception", "tema": "Il network", "scena": "foto", "foto": "foto-reception.jpg",
     "titolo": "Studi indipendenti, *più forti insieme*",
     "didascalia": """Dentalia è un network di studi dentistici che restano indipendenti: il tuo nome, i tuoi pazienti, le tue scelte cliniche.

Insieme condividiamo quello che da soli costa troppo: metodo, numeri, formazione, acquisti, sviluppo commerciale.

Più studi, più sorrisi, più futuro.

""" + HASHTAG + " #Network"},
    {"id": "net-indipendente", "tema": "Il network", "scena": "titolo",
     "titolo": "Restare *indipendenti* non vuol dire restare soli",
     "didascalia": """Molti titolari temono che entrare in un gruppo voglia dire perdere il proprio studio.

Nel network Dentalia succede il contrario: lo studio resta tuo, con il tuo nome e le tue scelte. In più hai un metodo, dei numeri chiari e dei colleghi con cui confrontarti.

""" + HASHTAG + " #Network"},
    {"id": "net-porta", "tema": "Il network", "scena": "foto", "foto": "foto-porta-member.jpg",
     "titolo": "Un marchio che *si riconosce*, uno studio che resta tuo",
     "didascalia": """Il riconoscimento di un network e l'identità del tuo studio possono stare insieme.

È l'equilibrio su cui è costruita Dentalia.

""" + HASHTAG + " #Network"},
    {"id": "net-sardegna", "tema": "Il network", "scena": "foto", "foto": "foto-montagne.jpg",
     "titolo": "Nati in *Sardegna*, per gli studi che vogliono crescere",
     "didascalia": """Conosciamo il territorio, le distanze, le stagioni e i pazienti. Lavoriamo con gli studi sardi, di persona.

""" + HASHTAG + " #Sardegna #Network"},
    # ---- Colloquio di valutazione
    {"id": "coll-cta", "tema": "Colloquio di valutazione", "scena": "cta",
     "titolo": "Vuoi sapere *da dove partire*?",
     "testo": "Un colloquio di valutazione sulle 6 aree del tuo studio.",
     "punti": ["Prenota il colloquio"],
     "didascalia": """In un incontro analizziamo insieme sei aree del tuo studio: sviluppo commerciale, organizzazione, numeri, personale, acquisti e formazione.

Alla fine hai una fotografia chiara (la nostra «radiografia») e sai da quale area conviene cominciare.

👉 Scrivici in privato o visita dentaliagroup.it

""" + HASHTAG + " #Consulenza"},
    {"id": "coll-6-aree", "tema": "Colloquio di valutazione", "scena": "lista",
     "titolo": "La radiografia del tuo studio *in 6 aree*",
     "punti": ["Sviluppo commerciale e organizzazione", "Numeri e personale", "Acquisti e formazione"],
     "didascalia": """Come una radiografia mostra ciò che a occhio nudo non si vede, il nostro check-up mostra dove lo studio rende e dove perde.

Sei aree, domande concrete, un grafico chiaro e una priorità da cui partire.

👉 Il colloquio di valutazione si prenota da dentaliagroup.it

""" + HASHTAG + " #Consulenza"},
    {"id": "coll-biglietto", "tema": "Colloquio di valutazione", "scena": "foto", "foto": "foto-biglietto.jpg",
     "titolo": "Il primo passo è *una conversazione*",
     "didascalia": """Niente impegni e niente moduli lunghi: un incontro in cui ascoltiamo come funziona il tuo studio oggi e ti diciamo con sincerità cosa vediamo.

👉 Scrivici in privato o visita dentaliagroup.it

""" + HASHTAG},
    {"id": "coll-domanda", "tema": "Domanda della settimana", "scena": "domanda",
     "titolo": "Se potessi migliorare *una sola cosa* nel tuo studio, quale sceglieresti?",
     "didascalia": """Pazienti, team, numeri, acquisti, organizzazione, tempo per te...

Scrivilo nei commenti 👇 Spesso la risposta dice già molto su da dove partire.

""" + HASHTAG},
]
