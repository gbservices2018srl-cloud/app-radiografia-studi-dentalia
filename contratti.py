"""
Contratto di affiliazione.

  preventivo di affiliazione «Accettato»  ->  contratto «Da compilare» (dati del cliente)
  -> «Da firmare» (testo congelato, link di firma)  ->  firma col dito: sul dispositivo del commerciale
  o dal link inviato al cliente  ->  «Firmato»: il contatto diventa Affiliato e si aprono i preventivi dei servizi.

Il testo viene dal modello in Impostazioni.contratto_testo (con i {segnaposto} di SEGNAPOSTO); se è vuoto
si usa la BOZZA PROVVISORIA qui sotto, in attesa del modello dei legali.
La firma è una firma elettronica semplice: si salvano immagine, nome, data/ora, modalità, IP, browser e
l'impronta SHA-256 del testo firmato.
"""
import hashlib
import json
import re
import secrets
from datetime import datetime

from flask import abort, flash, g, redirect, render_template, request, url_for

from app import (Attivita, Contatto, Contratto, Preventivo, Utente, Valutazione, app, calcola_totali,
                 conf_affiliazione, db, euro, impostazioni, login_richiesto, ora_locale)

STATI_CONTRATTO = {"da_compilare": "Da compilare", "da_firmare": "Da firmare", "firmato": "Firmato",
                   "annullato": "Annullato"}

CAMPI_CLIENTE = [
    ("ragione_sociale", "Ragione sociale / denominazione", True),
    ("piva", "Partita IVA", True),
    ("cf", "Codice fiscale", False),
    ("indirizzo", "Indirizzo della sede", True),
    ("cap", "CAP", True),
    ("citta", "Comune", True),
    ("provincia", "Provincia (sigla)", True),
    ("pec", "PEC", False),
    ("sdi", "Codice SDI", False),
    ("email", "Email", False),
    ("telefono", "Telefono", False),
    ("legale_rappresentante", "Legale rappresentante (nome e cognome)", True),
    ("lr_cf", "Codice fiscale del legale rappresentante", False),
    ("lr_nascita", "Luogo e data di nascita del legale rappresentante", False),
]

SEGNAPOSTO = {
    "numero_contratto": "Numero del contratto (es. C-2026/001)",
    "data": "Data di oggi",
    "azienda_ragione_sociale": "Consulting Sardegna Srl",
    "azienda_indirizzo": "Sede di Consulting Sardegna",
    "azienda_piva": "P.IVA di Consulting Sardegna",
    "cliente_ragione_sociale": "Ragione sociale del cliente",
    "cliente_piva": "P.IVA del cliente", "cliente_cf": "Codice fiscale del cliente",
    "cliente_indirizzo": "Indirizzo", "cliente_cap": "CAP", "cliente_citta": "Comune", "cliente_provincia": "Provincia",
    "cliente_pec": "PEC", "cliente_sdi": "SDI",
    "legale_rappresentante": "Legale rappresentante", "lr_cf": "CF del legale rappresentante",
    "lr_nascita": "Luogo e data di nascita del legale rappresentante",
    "servizi_inclusi": "Elenco delle voci dell'affiliazione",
    "prezzo_imponibile": "Prezzo concordato IVA esclusa", "iva": "IVA", "totale": "Totale IVA inclusa",
    "consulente": "Nome del consulente Dentalia",
}

BOZZA_PROVVISORIA = """BOZZA PROVVISORIA – testo in attesa del modello definitivo dei legali. Non utilizzare come contratto definitivo.

CONTRATTO DI AFFILIAZIONE AL NETWORK DENTALIA n. {numero_contratto}

TRA
{azienda_ragione_sociale}, con sede in {azienda_indirizzo}, P.IVA {azienda_piva} (di seguito «Dentalia»)

E
{cliente_ragione_sociale}, con sede in {cliente_indirizzo}, {cliente_cap} {cliente_citta} ({cliente_provincia}), P.IVA {cliente_piva}, C.F. {cliente_cf}, PEC {cliente_pec}, in persona del legale rappresentante {legale_rappresentante}, nato/a a {lr_nascita}, C.F. {lr_cf} (di seguito «lo Studio»)

1. OGGETTO
Dentalia ammette lo Studio al network Dentalia e fornisce i seguenti servizi:
{servizi_inclusi}

2. CORRISPETTIVO
Lo Studio riconosce a Dentalia il corrispettivo di {prezzo_imponibile} oltre IVA ({iva}), per un totale di {totale}, secondo le modalità di pagamento concordate nel preventivo di affiliazione accettato.

3. DURATA E RECESSO
[DA COMPLETARE DAI LEGALI]

4. MARCHIO DENTALIA
Lo Studio è autorizzato a utilizzare il marchio Dentalia nei limiti indicati da Dentalia. [DA COMPLETARE DAI LEGALI]

5. RISERVATEZZA E TRATTAMENTO DEI DATI
[DA COMPLETARE DAI LEGALI]

6. FORO COMPETENTE
[DA COMPLETARE DAI LEGALI]

Consulente Dentalia di riferimento: {consulente}

Luogo e data: ______________, {data}"""


def testo_modello():
    t = (impostazioni().contratto_testo or "").strip()
    return t or BOZZA_PROVVISORIA


def compila_testo(k):
    imp = impostazioni()
    p = db.session.get(Preventivo, k.preventivo_id)
    tot = calcola_totali(json.loads(p.righe), p.sconto_globale) if p else {"imponibile": 0, "totale_iva": 0, "totale": 0}
    voci = conf_affiliazione()["voci"]
    if p:
        righe = json.loads(p.righe)
        if righe and righe[0].get("dettaglio"):
            voci = [v for v in righe[0]["dettaglio"].split("\n") if v.strip()]
    consulente = db.session.get(Utente, k.utente_id)
    valori = {
        "numero_contratto": k.codice, "data": datetime.now().strftime("%d/%m/%Y"),
        "azienda_ragione_sociale": imp.ragione_sociale or "", "azienda_indirizzo": imp.indirizzo or "",
        "azienda_piva": imp.piva or "",
        "cliente_ragione_sociale": k.ragione_sociale or "", "cliente_piva": k.piva or "", "cliente_cf": k.cf or "—",
        "cliente_indirizzo": k.indirizzo or "", "cliente_cap": k.cap or "", "cliente_citta": k.citta or "",
        "cliente_provincia": (k.provincia or "").upper(), "cliente_pec": k.pec or "—", "cliente_sdi": k.sdi or "—",
        "legale_rappresentante": k.legale_rappresentante or "", "lr_cf": k.lr_cf or "—",
        "lr_nascita": k.lr_nascita or "—",
        "servizi_inclusi": "\n".join(f"- {v}" for v in voci),
        "prezzo_imponibile": euro(tot["imponibile"]), "iva": euro(tot["totale_iva"]), "totale": euro(tot["totale"]),
        "consulente": consulente.nome if consulente else "",
    }
    return re.sub(r"\{(\w+)\}", lambda m: valori.get(m.group(1), m.group(0)), testo_modello())


def link_firma(k):
    from newsletter import app_url
    return app_url() + url_for("firma_cliente", token=k.token)


def contratto_visibile(kid):
    k = db.session.get(Contratto, kid) or abort(404)
    if not g.utente.is_admin and k.utente_id != g.utente.id:
        abort(403)
    return k


def contatto_del(k):
    v = db.session.get(Valutazione, k.valutazione_id) if k.valutazione_id else None
    return db.session.get(Contatto, v.contatto_id) if v and v.contatto_id else None


def mancanti(k):
    return [et for campo, et, obbl in CAMPI_CLIENTE if obbl and not (getattr(k, campo) or "").strip()]


def registra_firma(k, firma, nome, modo, utente_id=None):
    k.firma, k.firmatario, k.firmato_il, k.firma_modo = firma, nome[:200], datetime.utcnow(), modo
    k.firma_ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip())[:60]
    k.firma_agent = (request.headers.get("User-Agent") or "")[:300]
    k.stato = "firmato"
    k.modificato_il = datetime.utcnow()
    c = contatto_del(k)
    if c:
        c.stato = "cliente"
        c.modificato_il = datetime.utcnow()
        db.session.add(Attivita(contatto_id=c.id, utente_id=utente_id, tipo="contratto", esito="firmato",
                                testo=f"Contratto {k.codice} firmato da {nome} ({'sul dispositivo' if modo == 'dispositivo' else 'dal link'}): studio affiliato"))


def firma_valida(dato):
    return bool(dato) and dato.startswith("data:image/png;base64,") and 2000 < len(dato) < 800_000


@app.template_filter("paragrafi_contratto")
def paragrafi_contratto(testo):
    """Testo del contratto -> blocchi per la pagina (titoli in maiuscolo, elenchi con «- »)."""
    out = []
    for b in re.split(r"\n\s*\n", testo or ""):
        righe = [r for r in b.strip().splitlines() if r.strip()]
        if not righe:
            continue
        if all(r.strip().startswith("- ") for r in righe):
            out.append({"tipo": "elenco", "righe": [r.strip()[2:] for r in righe]})
        elif len(righe) == 1 and righe[0].strip().isupper() and len(righe[0]) < 90:
            out.append({"tipo": "titolo", "testo": righe[0].strip()})
        else:
            out.append({"tipo": "testo", "righe": righe})
    return out


# ------------------------------------------------------------------ pagine (team)
@app.route("/contratti")
@login_richiesto
def contratti():
    q = Contratto.query
    if not g.utente.is_admin:
        q = q.filter_by(utente_id=g.utente.id)
    stato = request.args.get("stato")
    if stato in STATI_CONTRATTO:
        q = q.filter_by(stato=stato)
    elenco = q.order_by(Contratto.creato_il.desc()).all()
    tutti = Contratto.query if g.utente.is_admin else Contratto.query.filter_by(utente_id=g.utente.id)
    conteggi = dict(db.session.query(Contratto.stato, db.func.count()).filter(
        Contratto.id.in_(tutti.with_entities(Contratto.id))).group_by(Contratto.stato).all())
    utenti = {u.id: u for u in Utente.query.all()}
    return render_template("contratti.html", elenco=elenco, stato=stato, stati=STATI_CONTRATTO, conteggi=conteggi,
                           utenti=utenti)


@app.route("/contratti/<int:kid>", methods=["GET", "POST"])
@login_richiesto
def contratto_scheda(kid):
    k = contratto_visibile(kid)
    if request.method == "POST" and k.stato in ("da_compilare", "da_firmare"):
        for campo, _, _ in CAMPI_CLIENTE:
            setattr(k, campo, request.form.get(campo, "").strip()[:300] or None)
        k.provincia = (k.provincia or "").upper()[:4] or None
        k.note = request.form.get("note", "").strip() or None
        ct = contatto_del(k)
        if ct:   # l'anagrafica resta una sola: quella della scheda cliente
            for campo in ("ragione_sociale", "piva", "cf", "cap", "provincia", "pec", "sdi", "legale_rappresentante",
                          "lr_cf", "lr_nascita", "indirizzo", "citta", "email"):
                valore = getattr(k, campo)
                if valore:
                    setattr(ct, campo, valore)
        k.modificato_il = datetime.utcnow()
        mancano = mancanti(k)
        if request.form.get("azione") == "pronto":
            if mancano:
                flash("Per preparare il contratto mancano: " + ", ".join(mancano) + ".")
            else:
                k.testo = compila_testo(k)
                k.hash_testo = hashlib.sha256(k.testo.encode("utf-8")).hexdigest()
                k.token = k.token or secrets.token_urlsafe(32)
                k.stato = "da_firmare"
                flash("Contratto pronto: fallo firmare sul dispositivo o manda il link al cliente.")
        else:
            if k.stato == "da_firmare":   # dati cambiati: il testo va rigenerato prima della firma
                k.stato, k.testo, k.hash_testo = "da_compilare", None, None
            flash("Dati salvati.")
        db.session.commit()
        return redirect(url_for("contratto_scheda", kid=k.id))
    p = db.session.get(Preventivo, k.preventivo_id)
    anteprima = k.testo or compila_testo(k)
    link = link_firma(k) if k.token else None
    return render_template("contratto.html", k=k, p=p, campi=CAMPI_CLIENTE, stati=STATI_CONTRATTO,
                           anteprima=anteprima, mancano=mancanti(k), link=link,
                           provvisorio=not (impostazioni().contratto_testo or "").strip(),
                           consulente=db.session.get(Utente, k.utente_id))


@app.route("/contratti/<int:kid>/firma", methods=["GET", "POST"])
@login_richiesto
def contratto_firma_dispositivo(kid):
    """Il cliente firma sul telefono/tablet del commerciale."""
    k = contratto_visibile(kid)
    if k.stato != "da_firmare":
        flash("Il contratto non è pronto per la firma." if k.stato == "da_compilare" else "Il contratto è già firmato.")
        return redirect(url_for("contratto_scheda", kid=k.id))
    if request.method == "POST":
        f = request.form
        if not (f.get("letto") and f.get("clausole")):
            flash("Il cliente deve spuntare le due conferme prima di firmare.")
        elif not f.get("firmatario", "").strip():
            flash("Scrivi il nome di chi firma.")
        elif not firma_valida(f.get("firma", "")):
            flash("Manca la firma: fai firmare col dito nel riquadro.")
        else:
            registra_firma(k, f["firma"], f["firmatario"].strip(), "dispositivo", g.utente.id)
            if f.get("firma_azienda") and firma_valida(f["firma_azienda"]):
                k.firma_azienda, k.firmato_azienda_il = f["firma_azienda"], datetime.utcnow()
                k.firmatario_azienda = (f.get("firmatario_azienda") or g.utente.nome).strip()[:200]
            db.session.commit()
            flash(f"Contratto {k.codice} firmato: lo studio è affiliato e si possono fare i preventivi dei servizi.")
            return redirect(url_for("contratto_scheda", kid=k.id))
    return render_template("contratto_firma.html", k=k, pubblica=False, azione=url_for("contratto_firma_dispositivo", kid=k.id),
                           imp=impostazioni())


@app.post("/contratti/<int:kid>/firma-azienda")
@login_richiesto
def contratto_firma_azienda(kid):
    """Controfirma (facoltativa) per Consulting Sardegna, anche dopo la firma del cliente."""
    k = contratto_visibile(kid)
    f = request.form
    if k.stato != "firmato" or not firma_valida(f.get("firma_azienda", "")):
        flash("Firma non valida.")
    else:
        k.firma_azienda, k.firmato_azienda_il = f["firma_azienda"], datetime.utcnow()
        k.firmatario_azienda = (f.get("firmatario_azienda") or g.utente.nome).strip()[:200]
        db.session.commit()
        flash("Controfirma aggiunta.")
    return redirect(url_for("contratto_scheda", kid=k.id))


@app.post("/contratti/<int:kid>/invia-link")
@login_richiesto
def contratto_invia_link(kid):
    """Manda al cliente, via email, il link per firmare dal suo telefono."""
    from email.message import EmailMessage
    from email.utils import formataddr
    from newsletter import Postino, conf_smtp, smtp_pronto
    k = contratto_visibile(kid)
    dest = (request.form.get("email") or k.email or "").strip()
    if k.stato != "da_firmare" or not dest:
        flash("Serve un contratto pronto per la firma e l'email del cliente.")
        return redirect(url_for("contratto_scheda", kid=k.id))
    if not smtp_pronto():
        flash("La casella per l'invio non è configurata: copia il link e mandalo tu (WhatsApp o email).")
        return redirect(url_for("contratto_scheda", kid=k.id))
    c = conf_smtp()
    link = link_firma(k)
    m = EmailMessage()
    m["Subject"] = f"Contratto di affiliazione Dentalia {k.codice} da firmare"
    m["From"] = formataddr((c["nome"], c["utente"] or "info@dentaliagroup.it"))
    m["To"] = dest
    m["Reply-To"] = g.utente.email
    m.set_content(f"Gentile {k.legale_rappresentante or ''},\n\n"
                  f"come concordato, ecco il contratto di affiliazione al network Dentalia.\n"
                  f"Può leggerlo e firmarlo dal telefono o dal computer a questo indirizzo:\n\n{link}\n\n"
                  f"Per qualsiasi domanda risponda pure a questa email.\n\n{g.utente.nome}\nDentalia")
    try:
        with Postino() as p:
            p.manda(m)
        k.email = k.email or dest
        c_ = contatto_del(k)
        if c_:
            db.session.add(Attivita(contatto_id=c_.id, utente_id=g.utente.id, tipo="contratto", esito="link",
                                    testo=f"Link di firma del contratto {k.codice} inviato a {dest}"))
        db.session.commit()
        flash(f"Link di firma inviato a {dest}.")
    except Exception as e:
        flash(f"Invio non riuscito: {e}. Copia il link e mandalo tu.")
    return redirect(url_for("contratto_scheda", kid=k.id))


@app.post("/contratti/<int:kid>/annulla")
@login_richiesto
def contratto_annulla(kid):
    k = contratto_visibile(kid)
    if k.stato == "firmato" and not g.utente.is_admin:
        abort(403)
    k.stato = "annullato"
    k.modificato_il = datetime.utcnow()
    db.session.commit()
    flash(f"Contratto {k.codice} annullato.")
    return redirect(url_for("contratti"))


@app.route("/contratti/<int:kid>/stampa")
@login_richiesto
def contratto_stampa(kid):
    k = contratto_visibile(kid)
    return render_template("contratto_stampa.html", k=k, testo=k.testo or compila_testo(k), imp=impostazioni())


# ------------------------------------------------------------------ pagina pubblica di firma (link al cliente)
@app.route("/firma/<token>", methods=["GET", "POST"])
def firma_cliente(token):
    k = Contratto.query.filter_by(token=token).first() if token else None
    if not k or k.stato == "annullato":
        return render_template("contratto_firma.html", k=None, pubblica=True, imp=impostazioni()), 404
    if request.method == "POST" and k.stato == "da_firmare":
        f = request.form
        if not (f.get("letto") and f.get("clausole")):
            flash("Spunti le due conferme prima di firmare.")
        elif not f.get("firmatario", "").strip():
            flash("Scriva il suo nome e cognome.")
        elif not firma_valida(f.get("firma", "")):
            flash("Manca la firma: firmi col dito (o col mouse) nel riquadro.")
        else:
            registra_firma(k, f["firma"], f["firmatario"].strip(), "link")
            db.session.commit()
            return redirect(url_for("firma_cliente", token=token))
    return render_template("contratto_firma.html", k=k, pubblica=True, azione=url_for("firma_cliente", token=token),
                           imp=impostazioni())


@app.route("/firma/<token>/copia")
def firma_copia(token):
    """Copia del contratto firmato, per il cliente."""
    k = Contratto.query.filter_by(token=token).first()
    if not k or k.stato != "firmato":
        abort(404)
    return render_template("contratto_stampa.html", k=k, testo=k.testo, imp=impostazioni())
