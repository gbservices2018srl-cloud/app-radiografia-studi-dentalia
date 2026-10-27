"""
Funnel email automatico: a ogni iscritto alla newsletter (consenso esplicito) partono, una alla volta,
le email attive della sequenza, `giorno` giorni dopo il consenso.
La sequenza si ferma da sola se il contatto prende appuntamento, si presenta, diventa affiliato
o si disiscrive. Un controllo gira ogni 15 minuti (solo lun-ven, 9-18 ora italiana).
Spenta finché l'admin non la attiva da /newsletter/sequenza.
"""
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from app import (Attivita, Contatto, SequenzaEmail, SequenzaInvio, admin_richiesto, app, db, impostazioni)
from newsletter import Postino, componi, conf_smtp, smtp_pronto, app_url

ROMA = ZoneInfo("Europe/Rome")
STATI_STOP = ("appuntamento", "presentato", "cliente")
INTERVALLO_MINIMO = timedelta(hours=20)       # mai due email della sequenza allo stesso contatto nello stesso giorno
MAX_PER_GIRO = 40
_lock = threading.Lock()

SITO = "https://www.dentaliagroup.it"
SEQUENZA_BASE = [
    (0, "Promessa: niente spam, solo cose utili per il tuo studio",
     """grazie per averci dato il permesso di scriverti.

Ti dico subito cosa riceverai, così decidi tu se vale la pena aprire le prossime email.

Ogni pochi giorni ti mando **una sola idea pratica** per far rendere di più il tuo studio fuori dalla poltrona: pazienti, preventivi, personale, acquisti, numeri.

Niente teoria e niente promozioni travestite da consigli. Se una cosa non ti serve, la cestini in due secondi.

Partiamo da una domanda che facciamo a ogni titolare che incontriamo:

**sai dire, senza aprire nessun programma, quanti preventivi hai consegnato il mese scorso e quanti sono stati accettati?**

Se la risposta è «più o meno», non sei il solo. Ed è esattamente da lì che parte la prossima email.

A presto,
il team Dentalia""", "Scopri chi siamo", f"{SITO}/chi-siamo/"),
    (3, "Il denaro che il tuo studio ha già guadagnato (e non incassa)",
     """c'è un posto dove quasi ogni studio tiene soldi fermi: il cassetto dei preventivi.

Pazienti che hanno fatto la prima visita, hanno ricevuto un piano di cura, hanno detto «ci penso» e non sono più tornati.

Fai questo conto, ti servono due minuti:

- prendi i preventivi non accettati degli ultimi sei mesi
- somma il loro valore
- chiediti: se ne recuperassi anche solo uno su quattro, quanto sarebbe?

Quella cifra la puoi recuperare **senza un solo paziente nuovo**: solo richiamando bene chi ti ha già scelto una volta.

Il problema quasi mai è il paziente. È che nessuno nello studio ha il compito preciso di richiamarlo, con un metodo e con le parole giuste.

Nella prossima email ti lascio le tre domande che usiamo per capire dove uno studio perde pazienti.

Il team Dentalia""", "Come lavoriamo sullo sviluppo commerciale", f"{SITO}/aree/sviluppo-commerciale/"),
    (7, "3 domande per capire dove perdi pazienti (e soldi)",
     """ecco le tre domande che facciamo in ogni studio all'inizio del lavoro insieme. Rispondi con sincerità, anche solo nella tua testa.

**1. Chi richiama i pazienti che non hanno accettato il preventivo, e quando?**
Se la risposta è «chi ha tempo», in pratica non lo fa nessuno.

**2. Sai quanto ti costa, davvero, un'ora di poltrona?**
Senza questo numero ogni sconto è una scommessa e ogni prezzo è un'impressione.

**3. Quanto paghi i materiali che usi tutti i giorni rispetto a chi compra in rete?**
Spesso la differenza non sta nella qualità, ma nel potere d'acquisto.

Se almeno una risposta ti ha messo a disagio, non è un problema: è il punto da cui partire.

È, in piccolo, quello che facciamo nella **radiografia iniziale dello studio**: guardiamo sei aree (commerciale, organizzazione, numeri, personale, acquisti, formazione) e ti diciamo con chiarezza da quale conviene cominciare.

Il team Dentalia""", "Guarda le 6 aree", f"{SITO}/"),
    (12, "Indipendente non vuol dire da solo",
     """molti titolari che incontriamo ci dicono la stessa cosa: «Non voglio entrare in una catena. Lo studio è mio e deve restare mio.»

Hanno ragione. Ed è proprio per questo che esiste Dentalia.

Dentalia è una rete di **studi indipendenti** che mettono insieme quello che da soli costa troppo:

- fornitori a condizioni di rete
- un project manager dedicato che ti segue
- corsi di vendita, gestione del personale e gestione finanziaria
- app per il controllo di gestione e per il magazzino
- un metodo per selezionare le persone giuste
- contratti, consensi e modulistica già pronti

Tu resti il titolare, con le tue scelte cliniche e il tuo stile. La comunicazione resta quella del tuo studio, con il tuo nome. Smetti solo di dover fare tutto il resto da solo.

**Studi indipendenti. Più forti. Insieme.**

Il team Dentalia""", "Scopri il network Dentalia", f"{SITO}/chi-siamo/"),
    (18, "Se non vediamo un vantaggio per te, te lo diciamo",
     """in queste settimane ti ho scritto di preventivi fermi, numeri che mancano e acquisti pagati troppo.

Ora ti propongo il passo concreto: **un colloquio di valutazione** in cui facciamo insieme la radiografia iniziale del tuo studio.

Come funziona:

- veniamo noi nel tuo studio
- analizziamo le sei aree e ti diamo un quadro chiaro di dove sei forte e dove perdi
- ti diciamo da quale area conviene partire

E una promessa: **se non vediamo un vantaggio concreto per te, te lo diciamo**. Nessuna proposta da firmare, nessun impegno.

Lavoriamo con un numero limitato di studi per zona. Per questo conviene verificare adesso se la tua zona è libera.

Rispondi a questa email oppure richiedi il colloquio dal sito.

Il team Dentalia""", "Richiedi il colloquio di valutazione", f"{SITO}/contatti/"),
    (25, "Chiudo il tuo fascicolo?",
     """non ho ricevuto risposta alla mia ultima email e va benissimo così: magari non è il momento.

Ti faccio solo una domanda, poi non ti scrivo più di questo argomento:

**vuoi che teniamo un posto per il tuo studio nella tua zona?**

- Se sì, rispondi a questa email anche solo con «sì» e ti richiamiamo per fissare il colloquio.
- Se no, non devi fare nulla: riceverai solo qualche consiglio pratico ogni tanto, e puoi sempre disiscriverti con il link qui sotto.

In ogni caso, grazie per averci letto fin qui.

Il team Dentalia""", "Fissa il colloquio", f"{SITO}/contatti/"),
]


def crea_sequenza_iniziale():
    if SequenzaEmail.query.count():
        return
    for giorno, oggetto, corpo, cta, link in SEQUENZA_BASE:
        db.session.add(SequenzaEmail(giorno=giorno, oggetto=oggetto, corpo=corpo, cta_testo=cta, cta_link=link))
    db.session.commit()


with app.app_context():
    try:
        crea_sequenza_iniziale()
    except Exception as e:
        db.session.rollback()
        print(f"ATTENZIONE: sequenza iniziale non creata: {e}", flush=True)


def sequenza_attiva():
    return bool(impostazioni().seq_attiva)


def in_orario(adesso=None):
    t = (adesso or datetime.now(ROMA))
    return t.weekday() < 5 and 9 <= t.hour < 18


def prossima_per(c, emails, inviati, adesso):
    """La prossima email della sequenza da mandare a c adesso (o None)."""
    if not c.newsletter or c.disiscritto or not c.email or not c.consenso_il or c.stato in STATI_STOP:
        return None
    gia = {i.email_id for i in inviati}
    if inviati and adesso - max(i.inviata_il for i in inviati) < INTERVALLO_MINIMO:
        return None
    for e in emails:
        if e.id in gia:
            continue
        return e if adesso >= c.consenso_il + timedelta(days=e.giorno or 0) else None
    return None


def esegui_giro(forza_orario=False):
    """Manda le email della sequenza dovute. Restituisce quante ne ha spedite."""
    if not _lock.acquire(blocking=False):
        return 0
    spedite = 0
    try:
        if not sequenza_attiva() or not smtp_pronto():
            return 0
        if not forza_orario and not app.config.get("TESTING") and not in_orario():
            return 0
        emails = SequenzaEmail.query.filter(SequenzaEmail.attiva.isnot(False)) \
            .order_by(SequenzaEmail.giorno, SequenzaEmail.id).all()
        if not emails:
            return 0
        adesso = datetime.utcnow()
        candidati = Contatto.query.filter(Contatto.newsletter.is_(True), Contatto.disiscritto.isnot(True),
                                          Contatto.consenso_il.isnot(None)).all()
        da_mandare = []
        for c in candidati:
            e = prossima_per(c, emails, SequenzaInvio.query.filter_by(contatto_id=c.id).all(), adesso)
            if e:
                da_mandare.append((c, e))
            if len(da_mandare) >= MAX_PER_GIRO:
                break
        if not da_mandare:
            return 0
        pausa = 0 if app.config.get("TESTING") else conf_smtp()["pausa"]
        with Postino() as p:
            for c, e in da_mandare:
                inv = SequenzaInvio(contatto_id=c.id, email_id=e.id, stato="in_invio")
                db.session.add(inv)
                try:
                    db.session.commit()        # il vincolo unico impedisce doppioni anche con più processi
                except IntegrityError:
                    db.session.rollback()
                    continue
                try:
                    with app.test_request_context(base_url=app_url()):
                        p.manda(componi(e, c))
                    inv.stato, inv.inviata_il = "inviata", datetime.utcnow()
                    db.session.add(Attivita(contatto_id=c.id, tipo="newsletter", esito="sequenza",
                                            testo=f"Sequenza automatica, email del giorno {e.giorno}: {e.oggetto}"))
                    spedite += 1
                except Exception as err:
                    inv.stato, inv.errore = "errore", str(err)[:300]
                db.session.commit()
                if pausa:
                    time.sleep(pausa)
        return spedite
    except Exception as err:
        db.session.rollback()
        print(f"SEQUENZA: giro interrotto: {err}", flush=True)
        return spedite
    finally:
        _lock.release()


def _giro_subito():
    with app.app_context():
        esegui_giro(forza_orario=True)


def _ciclo():
    time.sleep(60)
    while True:
        try:
            with app.app_context():
                esegui_giro()
        except Exception as err:
            print(f"SEQUENZA: errore nel ciclo: {err}", flush=True)
        time.sleep(15 * 60)


if not app.config.get("TESTING") and os.environ.get("SEQUENZA_AUTO", "1") != "0" and "unittest" not in sys.modules:
    threading.Thread(target=_ciclo, daemon=True, name="sequenza-email").start()


# ------------------------------------------------------------------ pagine
@app.route("/newsletter/sequenza", methods=["GET", "POST"])
@admin_richiesto
def sequenza_pagina():
    imp = impostazioni()
    if request.method == "POST":
        imp.seq_attiva = request.form.get("attiva") == "1"
        db.session.commit()
        flash("Sequenza automatica attivata: partirà dal prossimo controllo (lun-ven, 9-18)." if imp.seq_attiva
              else "Sequenza automatica spenta: nessuna email partirà finché non la riattivi.")
        return redirect(url_for("sequenza_pagina"))
    emails = SequenzaEmail.query.order_by(SequenzaEmail.giorno, SequenzaEmail.id).all()
    inviate = dict(db.session.query(SequenzaInvio.email_id, db.func.count()).filter_by(stato="inviata")
                   .group_by(SequenzaInvio.email_id).all())
    errori = dict(db.session.query(SequenzaInvio.email_id, db.func.count()).filter_by(stato="errore")
                  .group_by(SequenzaInvio.email_id).all())
    iscritti = Contatto.query.filter(Contatto.newsletter.is_(True), Contatto.disiscritto.isnot(True)).all()
    in_corso = [c for c in iscritti if c.stato not in STATI_STOP]
    fermati = [c for c in iscritti if c.stato in STATI_STOP]
    return render_template("sequenza.html", emails=emails, inviate=inviate, errori=errori, attiva=bool(imp.seq_attiva),
                           smtp_ok=smtp_pronto(), in_corso=len(in_corso), fermati=len(fermati), orario=in_orario())


@app.route("/newsletter/sequenza/nuova", methods=["GET", "POST"])
@app.route("/newsletter/sequenza/<int:eid>", methods=["GET", "POST"])
@admin_richiesto
def sequenza_email(eid=None):
    e = db.session.get(SequenzaEmail, eid) if eid else SequenzaEmail(giorno=30, oggetto="", corpo="", attiva=True)
    if eid and not e:
        abort(404)
    if request.method == "POST":
        e.oggetto = request.form.get("oggetto", "").strip()[:200]
        e.corpo = request.form.get("corpo", "").strip()
        try:
            e.giorno = max(0, int(request.form.get("giorno", "0")))
        except ValueError:
            e.giorno = 0
        e.cta_testo = request.form.get("cta_testo", "").strip()[:80] or None
        e.cta_link = request.form.get("cta_link", "").strip()[:300] or None
        e.attiva = request.form.get("attiva") == "1"
        e.modificata_il = datetime.utcnow()
        if not e.oggetto or not e.corpo:
            flash("Scrivi oggetto e testo.")
            return render_template("sequenza_email.html", e=e, smtp_ok=smtp_pronto())
        if not e.id:
            db.session.add(e)
        db.session.commit()
        if request.form.get("azione") == "prova":
            try:
                with Postino() as p:
                    p.manda(componi(e, email=g.utente.email))
                flash(f"Prova inviata a {g.utente.email}.")
            except Exception as err:
                flash(f"Invio di prova non riuscito: {err}")
        else:
            flash("Email della sequenza salvata.")
        return redirect(url_for("sequenza_email", eid=e.id))
    return render_template("sequenza_email.html", e=e, smtp_ok=smtp_pronto())


@app.post("/newsletter/sequenza/<int:eid>/elimina")
@admin_richiesto
def sequenza_elimina(eid):
    e = db.session.get(SequenzaEmail, eid) or abort(404)
    SequenzaInvio.query.filter_by(email_id=e.id).delete()
    db.session.delete(e)
    db.session.commit()
    flash("Email tolta dalla sequenza.")
    return redirect(url_for("sequenza_pagina"))


@app.post("/newsletter/sequenza/esegui")
@admin_richiesto
def sequenza_esegui():
    if not sequenza_attiva():
        flash("Prima attiva la sequenza.")
    elif not smtp_pronto():
        flash("Manca la casella per l'invio (SMTP_PASSWORD su Render).")
    elif app.config.get("TESTING"):
        flash(f"Controllo fatto: {esegui_giro(forza_orario=True)} email inviate.")
    else:
        threading.Thread(target=_giro_subito, daemon=True).start()
        flash("Controllo avviato adesso: le email dovute partono una ogni pochi secondi.")
    return redirect(url_for("sequenza_pagina"))
