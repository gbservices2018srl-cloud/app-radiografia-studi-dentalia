"""
Newsletter Dentalia: solo contatti con consenso esplicito (Contatto.newsletter = True), invio con la casella SMTP
configurata su Render, link di disiscrizione in ogni email.

Variabili d'ambiente su Render:
  SMTP_HOST (default smtps.aruba.it), SMTP_PORT (default 465, SSL), SMTP_USER (es. info@dentaliagroup.it),
  SMTP_PASSWORD (password della casella), SMTP_MITTENTE_NOME (default "Dentalia"),
  NEWSLETTER_PAUSA (secondi tra un'email e l'altra, default 3: Aruba limita gli invii all'ora),
  APP_URL (default https://area.dentaliagroup.it, per i link nelle email).
In TESTING le email non partono: finiscono in app.config["EMAIL_INVIATE"].
"""
import html
import os
import re
import secrets
import smtplib
import ssl
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from flask import abort, flash, g, redirect, render_template, request, url_for

from app import (Attivita, Contatto, Newsletter, NewsletterInvio, admin_richiesto, app, db, impostazioni)

_lock = threading.Lock()


def conf_smtp():
    return {
        "host": os.environ.get("SMTP_HOST", "smtps.aruba.it"),
        "porta": int(os.environ.get("SMTP_PORT", "465")),
        "utente": os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "nome": os.environ.get("SMTP_MITTENTE_NOME", "Dentalia"),
        "pausa": float(os.environ.get("NEWSLETTER_PAUSA", "3")),
    }


def smtp_pronto():
    c = conf_smtp()
    return bool(app.config.get("TESTING") or (c["utente"] and c["password"]))


def app_url():
    return os.environ.get("APP_URL", "https://area.dentaliagroup.it").rstrip("/")


def iscritti():
    return Contatto.query.filter(Contatto.newsletter.is_(True), Contatto.disiscritto.isnot(True),
                                 Contatto.email.isnot(None), Contatto.email != "").order_by(Contatto.studio).all()


# ------------------------------------------------------------------ composizione
def corpo_html(testo):
    """Testo semplice -> HTML: righe vuote = paragrafi, **grassetto**, link cliccabili, '- ' = elenco."""
    blocchi = [b.strip() for b in re.split(r"\n\s*\n", (testo or "").strip()) if b.strip()]
    out = []

    def inline(t):
        t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        return re.sub(r"(https?://[^\s<]+)", r'<a href="\1" style="color:#8f6a33">\1</a>', t)

    for b in blocchi:
        righe = b.splitlines()
        if all(r.strip().startswith(("- ", "• ")) for r in righe):
            voci = "".join(f"<li style=\"margin:0 0 6px\">{inline(r.strip()[2:])}</li>" for r in righe)
            out.append(f'<ul style="margin:0 0 16px;padding-left:20px">{voci}</ul>')
        else:
            out.append(f'<p style="margin:0 0 16px">{"<br>".join(inline(r) for r in righe)}</p>')
    return "".join(out)


def componi(n, contatto=None, email=None):
    imp = impostazioni()
    token = contatto.token_nl if contatto else "prova"
    link = f"{app_url()}{url_for('newsletter_disiscrivi', token=token)}"
    saluto = ""
    if contatto and contatto.titolare:
        saluto = f"Gentile {contatto.titolare},\n\n"
    testo = saluto + n.corpo
    html_mail = render_template("newsletter_email.html", n=n, corpo=corpo_html(testo), imp=imp, link=link,
                                logo=f"{app_url()}{url_for('static', filename='brand/logo-completo.png')}")
    piano = (f"{testo}\n\n—\n{imp.ragione_sociale} · {imp.indirizzo or ''}\n"
             f"Ricevi questa email perché hai acconsentito alla newsletter Dentalia.\n"
             f"Per non riceverla più: {link}\n")
    c = conf_smtp()
    m = EmailMessage()
    m["Subject"] = n.oggetto
    m["From"] = formataddr((c["nome"], c["utente"] or "info@dentaliagroup.it"))
    m["To"] = email or contatto.email
    m["Message-ID"] = make_msgid(domain=(c["utente"].split("@")[-1] if "@" in c["utente"] else "dentaliagroup.it"))
    m["List-Unsubscribe"] = f"<{link}>"
    m["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    m.set_content(piano)
    m.add_alternative(html_mail, subtype="html")
    return m


class Postino:
    """Una connessione SMTP riutilizzata per più email (in test: le raccoglie e basta)."""

    def __init__(self):
        self.s = None

    def __enter__(self):
        if not app.config.get("TESTING"):
            c = conf_smtp()
            if c["porta"] == 465:
                self.s = smtplib.SMTP_SSL(c["host"], c["porta"], context=ssl.create_default_context(), timeout=30)
            else:
                self.s = smtplib.SMTP(c["host"], c["porta"], timeout=30)
                self.s.starttls(context=ssl.create_default_context())
            self.s.login(c["utente"], c["password"])
        return self

    def manda(self, msg):
        if app.config.get("TESTING"):
            app.config.setdefault("EMAIL_INVIATE", []).append(msg)
        else:
            self.s.send_message(msg)

    def __exit__(self, *a):
        if self.s:
            try:
                self.s.quit()
            except Exception:
                pass


def esegui_invio(nid, utente_id):
    """Manda le email in coda di una campagna (in un thread in produzione, subito nei test)."""
    with app.app_context():
        if not _lock.acquire(blocking=False):
            return
        try:
            n = db.session.get(Newsletter, nid)
            pausa = 0 if app.config.get("TESTING") else conf_smtp()["pausa"]
            coda = NewsletterInvio.query.filter_by(newsletter_id=nid, stato="in_coda").all()
            try:
                with Postino() as p:
                    for inv in coda:
                        c = db.session.get(Contatto, inv.contatto_id) if inv.contatto_id else None
                        if not c or not c.newsletter or c.disiscritto:
                            inv.stato = "saltata"
                            db.session.commit()
                            continue
                        try:
                            with app.test_request_context(base_url=app_url()):
                                msg = componi(n, c)
                            p.manda(msg)
                            inv.stato, inv.inviata_il = "inviata", datetime.utcnow()
                            db.session.add(Attivita(contatto_id=c.id, utente_id=utente_id, tipo="newsletter",
                                                    esito="inviata", testo=f"Newsletter: {n.oggetto}"))
                        except smtplib.SMTPServerDisconnected:
                            raise
                        except Exception as e:  # indirizzo rifiutato ecc.: si segna e si va avanti
                            inv.stato, inv.errore = "errore", str(e)[:300]
                        db.session.commit()
                        if pausa:
                            time.sleep(pausa)
            except Exception as e:  # login fallito o connessione persa: le email restano in coda
                db.session.rollback()
                print(f"NEWSLETTER {nid}: invio interrotto: {e}", flush=True)
            restanti = NewsletterInvio.query.filter_by(newsletter_id=nid, stato="in_coda").count()
            n.stato = "in_invio" if restanti else "inviata"
            if not restanti:
                n.inviata_il = datetime.utcnow()
            db.session.commit()
        finally:
            _lock.release()


def avvia_invio(nid):
    if app.config.get("TESTING"):
        esegui_invio(nid, g.utente.id)
    else:
        threading.Thread(target=esegui_invio, args=(nid, g.utente.id), daemon=True).start()


# ------------------------------------------------------------------ pagine
@app.route("/newsletter")
@admin_richiesto
def newsletter():
    campagne = Newsletter.query.order_by(Newsletter.creata_il.desc()).all()
    conteggi = {}
    for n in campagne:
        righe = db.session.query(NewsletterInvio.stato, db.func.count()).filter_by(newsletter_id=n.id) \
            .group_by(NewsletterInvio.stato).all()
        conteggi[n.id] = dict(righe)
    disiscritti = Contatto.query.filter(Contatto.disiscritto.is_(True)).count()
    return render_template("newsletter.html", iscritti=iscritti(), campagne=campagne, conteggi=conteggi,
                           disiscritti=disiscritti, smtp_ok=smtp_pronto(), smtp=conf_smtp())


@app.route("/newsletter/nuova", methods=["GET", "POST"])
@app.route("/newsletter/<int:nid>", methods=["GET", "POST"])
@admin_richiesto
def newsletter_modifica(nid=None):
    n = db.session.get(Newsletter, nid) if nid else Newsletter(oggetto="", corpo="", stato="bozza")
    if nid and not n:
        abort(404)
    if request.method == "POST":
        if n.stato != "bozza":
            flash("Questa newsletter è già stata inviata: duplicala per mandarne una nuova.")
            return redirect(url_for("newsletter_modifica", nid=n.id))
        n.oggetto = request.form.get("oggetto", "").strip()[:200]
        n.corpo = request.form.get("corpo", "").strip()
        if not n.oggetto or not n.corpo:
            flash("Scrivi oggetto e testo.")
            return render_template("newsletter_form.html", n=n, iscritti=iscritti(), smtp_ok=smtp_pronto(),
                                   anteprima=None)
        if not n.id:
            n.creata_da = g.utente.id
            db.session.add(n)
        db.session.commit()
        azione = request.form.get("azione")
        if azione == "prova":
            return newsletter_prova(n.id)
        flash("Bozza salvata.")
        return redirect(url_for("newsletter_modifica", nid=n.id))
    anteprima = corpo_html(n.corpo) if n.corpo else None
    return render_template("newsletter_form.html", n=n, iscritti=iscritti(), smtp_ok=smtp_pronto(),
                           anteprima=anteprima)


@app.post("/newsletter/<int:nid>/prova")
@admin_richiesto
def newsletter_prova(nid):
    n = db.session.get(Newsletter, nid) or abort(404)
    if not smtp_pronto():
        flash("La casella per l'invio non è ancora configurata su Render (SMTP_USER e SMTP_PASSWORD).")
        return redirect(url_for("newsletter_modifica", nid=n.id))
    try:
        with Postino() as p:
            p.manda(componi(n, email=g.utente.email))
        flash(f"Email di prova inviata a {g.utente.email}.")
    except Exception as e:
        flash(f"Invio di prova non riuscito: {e}")
    return redirect(url_for("newsletter_modifica", nid=n.id))


@app.post("/newsletter/<int:nid>/invia")
@admin_richiesto
def newsletter_invia(nid):
    n = db.session.get(Newsletter, nid) or abort(404)
    if not smtp_pronto():
        flash("La casella per l'invio non è ancora configurata su Render (SMTP_USER e SMTP_PASSWORD).")
        return redirect(url_for("newsletter_modifica", nid=n.id))
    if n.stato == "bozza":
        destinatari = iscritti()
        if not destinatari:
            flash("Nessun iscritto con consenso: la newsletter non è partita.")
            return redirect(url_for("newsletter_modifica", nid=n.id))
        for c in destinatari:
            if not c.token_nl:
                c.token_nl = secrets.token_urlsafe(24)
            db.session.add(NewsletterInvio(newsletter_id=n.id, contatto_id=c.id, email=c.email))
        n.stato = "in_invio"
        db.session.commit()
        flash(f"Invio avviato a {len(destinatari)} iscritti: procede da solo, un'email ogni pochi secondi.")
    elif n.stato == "in_invio":
        flash("Invio ripreso.")
    avvia_invio(n.id)
    return redirect(url_for("newsletter"))


@app.post("/newsletter/<int:nid>/duplica")
@admin_richiesto
def newsletter_duplica(nid):
    o = db.session.get(Newsletter, nid) or abort(404)
    n = Newsletter(oggetto=o.oggetto, corpo=o.corpo, creata_da=g.utente.id, stato="bozza")
    db.session.add(n)
    db.session.commit()
    return redirect(url_for("newsletter_modifica", nid=n.id))


@app.post("/newsletter/<int:nid>/elimina")
@admin_richiesto
def newsletter_elimina(nid):
    n = db.session.get(Newsletter, nid) or abort(404)
    if n.stato != "bozza":
        abort(400)
    db.session.delete(n)
    db.session.commit()
    return redirect(url_for("newsletter"))


@app.route("/newsletter/esporta.csv")
@admin_richiesto
def newsletter_esporta():
    righe = ["Studio;Titolare;Email;Citta;Consenso il"]
    for c in iscritti():
        quando = c.consenso_il.strftime("%d/%m/%Y") if c.consenso_il else ""
        righe.append(";".join(x.replace(";", ",") for x in (c.studio or "", c.titolare or "", c.email or "",
                                                             c.citta or "", quando)))
    return app.response_class("﻿" + "\r\n".join(righe) + "\r\n", mimetype="text/csv",
                              headers={"Content-Disposition": "attachment; filename=iscritti-newsletter.csv"})


@app.route("/newsletter/disiscrivi/<token>", methods=["GET", "POST"])
def newsletter_disiscrivi(token):
    """Pagina pubblica (senza login) raggiunta dal link nell'email."""
    c = Contatto.query.filter_by(token_nl=token).first() if token and token != "prova" else None
    fatto = False
    if request.method == "POST" and c:
        if c.newsletter or not c.disiscritto:
            c.newsletter, c.disiscritto = False, True
            db.session.add(Attivita(contatto_id=c.id, tipo="newsletter", esito="disiscritto",
                                    testo="Si è disiscritto dalla newsletter col link nell'email"))
            db.session.commit()
        fatto = True
    return render_template("newsletter_disiscrivi.html", c=c, fatto=fatto or (c is not None and c.disiscritto),
                           prova=token == "prova")
