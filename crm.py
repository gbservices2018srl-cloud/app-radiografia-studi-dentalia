"""
CRM Dentalia: contatti da chiamare, esiti delle chiamate, pipeline, note, richiami.
Le pagine vengono registrate direttamente su `app` (importato in fondo ad app.py).

Flusso:
  nuovo (Da chiamare) --chiamata--> non risponde / risponde senza appuntamento -> richiamare
                                    non interessato -> non_interessato (newsletter solo con consenso)
                                    appuntamento -> appuntamento
  appuntamento --> presentato (si è presentato: si fa la radiografia) / non presentato -> richiamare
  presentato --> cliente (preventivo di affiliazione accettato)
"""
import csv
import io
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import or_

from app import (Attivita, Contatto, Utente, Valutazione, admin_richiesto, app, contatto_visibile_o_none, db,
                 login_richiesto)

ROMA = ZoneInfo("Europe/Rome")

STATI_CONTATTO = {
    "nuovo": "Da chiamare",
    "richiamare": "Da richiamare",
    "appuntamento": "Appuntamento",
    "presentato": "Incontrato",
    "contratto": "Da firmare",
    "cliente": "Affiliato",
    "non_interessato": "Non interessato",
}

ESITI_CHIAMATA = {
    "non_risponde": ("Non risponde", "richiamare"),
    "no_appuntamento": ("Risponde, nessun appuntamento", "richiamare"),
    "appuntamento": ("Appuntamento preso", "appuntamento"),
    "non_interessato": ("Non interessato", "non_interessato"),
}

ESITI_APPUNTAMENTO = {
    "presentato": ("Si è presentato", "presentato"),
    "non_presentato": ("Non si è presentato", "richiamare"),
}

ETICHETTE_ESITO = {k: v[0] for k, v in {**ESITI_CHIAMATA, **ESITI_APPUNTAMENTO}.items()}

# una nuova apertura della stessa scheda dallo stesso utente entro questo tempo non viene ricontata
FINESTRA_APERTURA = timedelta(minutes=10)


@app.context_processor
def iniezioni_crm():
    return {"STATI_CONTATTO": STATI_CONTATTO, "ETICHETTE_ESITO": ETICHETTE_ESITO}


# ------------------------------------------------------------------ utilità
def norm_telefono(t):
    cifre = re.sub(r"\D", "", t or "")
    if cifre.startswith("0039"):
        cifre = cifre[4:]
    elif cifre.startswith("39") and len(cifre) > 10:
        cifre = cifre[2:]
    return cifre


def da_locale(testo):
    """'2026-10-27T15:30' (ora italiana, da <input type=datetime-local>) -> datetime UTC naive."""
    if not testo:
        return None
    try:
        dt = datetime.strptime(testo[:16], "%Y-%m-%dT%H:%M")
    except ValueError:
        try:
            dt = datetime.strptime(testo[:10], "%Y-%m-%d").replace(hour=9)
        except ValueError:
            return None
    return dt.replace(tzinfo=ROMA).astimezone(timezone.utc).replace(tzinfo=None)


@app.template_filter("per_input")
def per_input(dt):
    """datetime UTC -> valore per <input type=datetime-local> in ora italiana."""
    if not dt:
        return ""
    return dt.replace(tzinfo=timezone.utc).astimezone(ROMA).strftime("%Y-%m-%dT%H:%M")


def contatto_visibile(cid):
    c = db.session.get(Contatto, cid) or abort(404)
    if not g.utente.is_admin and c.utente_id != g.utente.id:
        abort(403)
    return c


def registra(c, tipo, esito=None, testo=None):
    db.session.add(Attivita(contatto_id=c.id, utente_id=g.utente.id, tipo=tipo, esito=esito,
                            testo=(testo or None)))


def query_visibili():
    q = Contatto.query
    if not g.utente.is_admin:
        q = q.filter(Contatto.utente_id == g.utente.id)
    return q


def commerciali_attivi():
    return Utente.query.filter(Utente.attivo.is_(True), Utente.approvato.isnot(False)).order_by(Utente.nome).all()


# ------------------------------------------------------------------ pipeline
@app.route("/contatti")
@login_richiesto
def contatti():
    args = request.args
    stato = args.get("stato") if args.get("stato") in STATI_CONTATTO else None
    q = query_visibili()
    filtro_comm = args.get("commerciale", type=int) if g.utente.is_admin else None
    kpi_attivo = None
    if args.get("kpi"):
        from kpi import FILTRI_KPI, ids_kpi, intervallo
        if args["kpi"] in FILTRI_KPI:
            da, a, _ = intervallo(args)
            uid = filtro_comm if g.utente.is_admin else g.utente.id
            q = q.filter(Contatto.id.in_(ids_kpi(args["kpi"], da, a, uid)))
            kpi_attivo = {"nome": FILTRI_KPI[args["kpi"]][0], "da": da, "a": a}
    if filtro_comm and not kpi_attivo:
        q = q.filter(Contatto.utente_id == filtro_comm)
    cerca = args.get("q", "").strip()
    if cerca:
        like = f"%{cerca}%"
        q = q.filter(or_(Contatto.studio.ilike(like), Contatto.titolare.ilike(like), Contatto.citta.ilike(like),
                         Contatto.telefono.ilike(like), Contatto.telefono_norm.like(f"%{norm_telefono(cerca) or cerca}%")))
    conteggi = {k: 0 for k in STATI_CONTATTO}
    for st, n in db.session.query(Contatto.stato, db.func.count()).filter(
            Contatto.id.in_(q.with_entities(Contatto.id))).group_by(Contatto.stato):
        conteggi[st] = n
    adesso = datetime.utcnow()
    scaduti = q.filter(Contatto.stato.in_(("nuovo", "richiamare")),
                       or_(Contatto.richiamare_il.is_(None), Contatto.richiamare_il <= adesso)).count()
    oggi = args.get("oggi") == "1"
    if oggi:
        q = q.filter(Contatto.stato.in_(("nuovo", "richiamare")),
                     or_(Contatto.richiamare_il.is_(None), Contatto.richiamare_il <= adesso))
    elif stato:
        q = q.filter(Contatto.stato == stato)
    if stato == "appuntamento":
        q = q.order_by(Contatto.appuntamento_il.asc().nullslast())
    elif stato in ("nuovo", "richiamare") or oggi:
        q = q.order_by(Contatto.richiamare_il.asc().nullsfirst(), Contatto.creato_il.asc())
    else:
        q = q.order_by(Contatto.modificato_il.desc())
    elenco = q.limit(500).all()
    utenti = {u.id: u for u in Utente.query.all()}
    return render_template("contatti.html", elenco=elenco, conteggi=conteggi, stato=stato, oggi=oggi,
                           scaduti=scaduti, totale=sum(conteggi.values()), args=args, utenti=utenti,
                           commerciali=commerciali_attivi(), adesso=adesso, kpi_attivo=kpi_attivo)


@app.route("/contatti/nuovo", methods=["GET", "POST"])
@login_richiesto
def contatto_nuovo():
    if request.method == "POST":
        f = request.form
        studio = f.get("studio", "").strip()
        telefono = f.get("telefono", "").strip()
        if not studio and not f.get("titolare", "").strip():
            flash("Scrivi almeno il nome dello studio o del titolare.")
            return render_template("contatto_form.html", c=None, form=f, commerciali=commerciali_attivi())
        doppione = Contatto.query.filter_by(telefono_norm=norm_telefono(telefono)).first() if norm_telefono(telefono) else None
        if doppione and f.get("conferma_doppione") != "1":
            visibile = g.utente.is_admin or doppione.utente_id == g.utente.id
            return render_template("contatto_form.html", c=None, form=f, commerciali=commerciali_attivi(),
                                   doppione=doppione, doppione_visibile=visibile)
        proprietario = g.utente.id
        if g.utente.is_admin and f.get("utente_id", type=int):
            proprietario = f.get("utente_id", type=int)
        c = Contatto(utente_id=proprietario, studio=studio or f.get("titolare", "").strip(),
                     titolare=f.get("titolare", "").strip(), telefono=telefono, telefono_norm=norm_telefono(telefono),
                     email=f.get("email", "").strip(), citta=f.get("citta", "").strip(),
                     indirizzo=f.get("indirizzo", "").strip(), note=f.get("note", "").strip(),
                     richiamare_il=da_locale(f.get("richiamare_il")), stato="nuovo", fonte="manuale")
        db.session.add(c)
        db.session.flush()
        registra(c, "creazione", testo="Contatto inserito a mano")
        db.session.commit()
        flash(f"Contatto «{c.studio}» aggiunto.")
        if f.get("dopo") == "altro":
            return redirect(url_for("contatto_nuovo"))
        return redirect(url_for("contatto_scheda", cid=c.id))
    return render_template("contatto_form.html", c=None, form={}, commerciali=commerciali_attivi())


@app.route("/contatti/<int:cid>")
@login_richiesto
def contatto_scheda(cid):
    c = contatto_visibile(cid)
    # conteggio aperture della scheda (= richiami): non si ricontano i ritorni sulla stessa scheda a pochi minuti
    ultima = Attivita.query.filter_by(contatto_id=c.id, utente_id=g.utente.id, tipo="apertura") \
        .order_by(Attivita.quando.desc()).first()
    if not ultima or datetime.utcnow() - ultima.quando > FINESTRA_APERTURA:
        c.aperture = (c.aperture or 0) + 1
        registra(c, "apertura")
        db.session.commit()
    storia = Attivita.query.filter_by(contatto_id=c.id).filter(Attivita.tipo != "apertura") \
        .order_by(Attivita.quando.desc()).limit(100).all()
    aperture_per = dict(db.session.query(Attivita.utente_id, db.func.count()).filter_by(
        contatto_id=c.id, tipo="apertura").group_by(Attivita.utente_id).all())
    utenti = {u.id: u for u in Utente.query.all()}
    radiografia = db.session.get(Valutazione, c.valutazione_id) if c.valutazione_id else None
    return render_template("contatto.html", c=c, storia=storia, utenti=utenti, radiografia=radiografia,
                           esiti=ESITI_CHIAMATA, esiti_app=ESITI_APPUNTAMENTO, aperture_per=aperture_per,
                           commerciali=commerciali_attivi(), domani=per_input(
                               (datetime.now(ROMA) + timedelta(days=1)).replace(hour=10, minute=0)
                               .astimezone(timezone.utc).replace(tzinfo=None)))


@app.post("/contatti/<int:cid>/chiamata")
@login_richiesto
def contatto_chiamata(cid):
    c = contatto_visibile(cid)
    f = request.form
    esito = f.get("esito")
    subito_radiografia = esito == "presentato_radiografia"
    if subito_radiografia:
        esito = "presentato"
    nota = f.get("nota", "").strip()
    if esito in ESITI_CHIAMATA:
        etichetta, nuovo_stato = ESITI_CHIAMATA[esito]
        if esito == "appuntamento":
            quando = da_locale(f.get("appuntamento_il"))
            if not quando:
                flash("Indica data e ora dell'appuntamento.")
                return redirect(url_for("contatto_scheda", cid=c.id) + "#chiamata")
            c.appuntamento_il = quando
            c.richiamare_il = None
            testo = f"Appuntamento il {quando.replace(tzinfo=timezone.utc).astimezone(ROMA):%d/%m/%Y alle %H:%M}"
            nota = testo + (f" · {nota}" if nota else "")
        elif nuovo_stato == "richiamare":
            c.richiamare_il = da_locale(f.get("richiamare_il"))
        if esito == "non_interessato":
            c.richiamare_il = None
        c.stato = nuovo_stato
        c.tentativi = (c.tentativi or 0) + 1
        c.ultimo_contatto_il = datetime.utcnow()
        registra(c, "chiamata", esito=esito, testo=nota)
        flash(f"Registrato: {etichetta}.")
    elif esito in ESITI_APPUNTAMENTO:
        etichetta, nuovo_stato = ESITI_APPUNTAMENTO[esito]
        c.stato = nuovo_stato
        if esito == "non_presentato":
            c.richiamare_il = da_locale(f.get("richiamare_il"))
        registra(c, "appuntamento", esito=esito, testo=nota)
        flash(f"Registrato: {etichetta}.")
        if esito == "presentato" and subito_radiografia:
            c.modificato_il = datetime.utcnow()
            db.session.commit()
            return redirect(url_for("nuova", contatto=c.id))
    else:
        abort(400)
    if f.get("consenso_newsletter") == "1":
        imposta_consenso(c, True, email=f.get("email_nl", "").strip())
    c.modificato_il = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("contatto_scheda", cid=c.id))


def imposta_consenso(c, dato, email=""):
    """Registra (o revoca) il consenso alla newsletter raccolto dal commerciale."""
    import secrets
    if email and not c.email:
        c.email = email[:200]
    if dato and not c.newsletter:
        if not c.email:
            flash("Consenso newsletter non registrato: manca l'email del contatto.")
            return
        c.newsletter, c.disiscritto = True, False
        c.consenso_il, c.consenso_da = datetime.utcnow(), g.utente.id
        c.token_nl = c.token_nl or secrets.token_urlsafe(24)
        registra(c, "newsletter", esito="consenso", testo=f"Consenso alla newsletter raccolto ({c.email})")
    elif not dato and c.newsletter:
        c.newsletter = False
        registra(c, "newsletter", esito="revoca", testo="Tolto dalla newsletter")


@app.post("/contatti/<int:cid>/nota")
@login_richiesto
def contatto_nota(cid):
    c = contatto_visibile(cid)
    testo = request.form.get("nota", "").strip()
    if testo:
        registra(c, "nota", testo=testo)
        c.modificato_il = datetime.utcnow()
        db.session.commit()
    return redirect(url_for("contatto_scheda", cid=c.id) + "#storia")


@app.route("/contatti/<int:cid>/modifica", methods=["GET", "POST"])
@login_richiesto
def contatto_modifica(cid):
    c = contatto_visibile(cid)
    if request.method == "POST":
        f = request.form
        c.studio = f.get("studio", "").strip() or c.studio
        for campo in ("titolare", "email", "citta", "indirizzo", "note"):
            setattr(c, campo, f.get(campo, "").strip())
        c.telefono = f.get("telefono", "").strip()
        c.telefono_norm = norm_telefono(c.telefono)
        c.richiamare_il = da_locale(f.get("richiamare_il"))
        if "consenso_presente" in f:
            imposta_consenso(c, f.get("consenso_newsletter") == "1")
        c.modificato_il = datetime.utcnow()
        db.session.commit()
        flash("Contatto aggiornato.")
        return redirect(url_for("contatto_scheda", cid=c.id))
    return render_template("contatto_form.html", c=c, form={}, commerciali=commerciali_attivi())


@app.post("/contatti/<int:cid>/stato")
@login_richiesto
def contatto_stato(cid):
    """Spostamento manuale nella pipeline (es. riaprire un 'non interessato')."""
    c = contatto_visibile(cid)
    nuovo = request.form.get("stato")
    if nuovo in STATI_CONTATTO and nuovo != c.stato:
        registra(c, "stato", esito=nuovo, testo=f"Spostato da «{STATI_CONTATTO[c.stato]}» a «{STATI_CONTATTO[nuovo]}»")
        c.stato = nuovo
        c.modificato_il = datetime.utcnow()
        db.session.commit()
    return redirect(url_for("contatto_scheda", cid=c.id))


@app.post("/contatti/<int:cid>/elimina")
@login_richiesto
def contatto_elimina(cid):
    c = contatto_visibile(cid)
    Attivita.query.filter_by(contatto_id=c.id).delete()
    db.session.delete(c)
    db.session.commit()
    flash(f"Contatto «{c.studio}» eliminato.")
    return redirect(url_for("contatti"))


@app.post("/contatti/assegna")
@admin_richiesto
def contatti_assegna():
    """L'admin sposta uno o più contatti da un commerciale all'altro."""
    a = db.session.get(Utente, request.form.get("utente_id", type=int)) or abort(400)
    ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
    n = 0
    for c in Contatto.query.filter(Contatto.id.in_(ids)).all() if ids else []:
        if c.utente_id != a.id:
            da = db.session.get(Utente, c.utente_id)
            registra(c, "assegnazione", testo=f"Spostato da {da.nome if da else '—'} a {a.nome}")
            c.utente_id = a.id
            c.modificato_il = datetime.utcnow()
            n += 1
    db.session.commit()
    flash(f"{n} contatt{'o spostato' if n == 1 else 'i spostati'} a {a.nome}." if n else "Nessun contatto spostato.")
    return redirect(request.form.get("torna") or url_for("contatti"))


# ------------------------------------------------------------------ import da Excel / CSV
ALIAS = {
    "studio": ("studio", "nomestudio", "studiodentistico", "ragionesociale", "denominazione", "azienda",
               "clinica", "nome", "struttura", "societa"),
    "titolare": ("titolare", "referente", "dottore", "dott", "dottoressa", "medico", "responsabile", "contatto",
                 "nomecognome", "nometitolare", "legalerappresentante", "cognome"),
    "telefono": ("telefono", "tel", "cellulare", "cell", "numero", "numeroditelefono", "telefono1", "mobile",
                 "phone", "recapito", "telefonofisso"),
    "email": ("email", "mail", "posta", "emailaddress", "indirizzoemail", "pec"),
    "citta": ("citta", "comune", "localita", "city", "paese"),
    "provincia": ("provincia", "prov", "pr", "siglaprovincia"),
    "indirizzo": ("indirizzo", "via", "address", "sede", "ubicazione", "posizione"),
    "note": ("note", "nota", "commento", "commenti", "annotazioni"),
}


def _chiave(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)


def leggi_righe(nome_file, dati):
    """Righe (liste di stringhe) da un file .xlsx/.xls o .csv."""
    nome = (nome_file or "").lower()
    if nome.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(dati), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        righe = [["" if v is None else str(v).strip() for v in r] for r in ws.iter_rows(values_only=True)]
        wb.close()
        return righe
    if nome.endswith(".xls"):
        raise ValueError("Il formato .xls (Excel 97-2003) non è supportato: salva il file come .xlsx o .csv.")
    for codifica in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            testo = dati.decode(codifica)
            break
        except UnicodeDecodeError:
            continue
    campione = testo[:5000]
    try:
        dialetto = csv.Sniffer().sniff(campione, delimiters=";,\t|")
    except csv.Error:
        class dialetto(csv.excel):
            delimiter = ";" if campione.count(";") > campione.count(",") else ","
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(testo), dialetto)]


def mappa_colonne(intestazione):
    mappa = {}
    for i, h in enumerate(intestazione):
        k = _chiave(h)
        for campo, alias in ALIAS.items():
            if campo not in mappa and (k in alias or any(k.startswith(a) for a in alias if len(a) > 3)):
                mappa[campo] = i
                break
    return mappa


def importa_righe(righe, proprietario_id, nome_file="file"):
    """Crea i contatti. Restituisce un riepilogo (creati, doppioni, scartati, colonne riconosciute)."""
    righe = [r for r in righe if any(x for x in r)]
    if not righe:
        return {"creati": 0, "doppioni": [], "scartati": 0, "colonne": {}}
    mappa = mappa_colonne(righe[0])
    if "telefono" in mappa and ("studio" in mappa or "titolare" in mappa):
        dati = righe[1:]
        colonne = {k: righe[0][i] for k, i in mappa.items()}
    else:   # senza intestazione riconoscibile: ordine studio, titolare, telefono, città
        mappa, dati = {"studio": 0, "titolare": 1, "telefono": 2, "citta": 3}, righe
        colonne = {k: f"colonna {i + 1}" for k, i in mappa.items()}
    nuovi = []
    esistenti = {t for (t,) in db.session.query(Contatto.telefono_norm).filter(Contatto.telefono_norm.isnot(None))}
    creati, doppioni, scartati = 0, [], 0
    for r in dati[:5000]:
        val = {campo: (r[i].strip() if i < len(r) else "") for campo, i in mappa.items()}
        studio = val.get("studio") or val.get("titolare")
        tel = norm_telefono(val.get("telefono"))
        if not studio or len(tel) < 6:
            scartati += 1
            continue
        if tel in esistenti:
            doppioni.append(studio)
            continue
        citta = val.get("citta", "")
        if val.get("provincia") and not re.search(r"\([A-Za-z]{2}\)\s*$", citta):
            citta = f"{citta} ({val['provincia'].upper()})".strip()
        c = Contatto(utente_id=proprietario_id, studio=studio[:200], titolare=(val.get("titolare") or "")[:200]
                     if val.get("studio") else "", telefono=val.get("telefono", "")[:60], telefono_norm=tel,
                     email=val.get("email", "")[:200], citta=citta[:120], indirizzo=val.get("indirizzo", "")[:300],
                     note=val.get("note", ""), stato="nuovo", fonte="import")
        db.session.add(c)
        nuovi.append(c)
        esistenti.add(tel)
        creati += 1
    db.session.flush()
    for c in nuovi:
        db.session.add(Attivita(contatto_id=c.id, utente_id=g.utente.id, tipo="creazione",
                                testo=f"Importato da {nome_file}"))
    return {"creati": creati, "doppioni": doppioni, "scartati": scartati, "colonne": colonne}


@app.route("/contatti/importa", methods=["GET", "POST"])
@login_richiesto
def contatti_importa():
    esito = None
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Scegli un file Excel (.xlsx) o CSV.")
        else:
            proprietario = g.utente.id
            if g.utente.is_admin and request.form.get("utente_id", type=int):
                proprietario = request.form.get("utente_id", type=int)
            try:
                esito = importa_righe(leggi_righe(file.filename, file.read()), proprietario, file.filename)
            except ValueError as e:
                flash(str(e))
            except Exception as e:  # file rovinato o formato inatteso
                db.session.rollback()
                flash(f"Non riesco a leggere il file ({e.__class__.__name__}). Prova a salvarlo come .xlsx o .csv.")
            else:
                db.session.commit()
    return render_template("contatti_importa.html", esito=esito, commerciali=commerciali_attivi())


@app.route("/contatti/modello.csv")
@login_richiesto
def contatti_modello():
    testo = ("Studio;Titolare;Telefono;Email;Citta;Provincia;Indirizzo;Note\r\n"
             "Studio Dentistico Rossi;Dott. Mario Rossi;070 123456;info@studiorossi.it;Cagliari;CA;Via Roma 1;\r\n")
    return app.response_class("﻿" + testo, mimetype="text/csv",
                              headers={"Content-Disposition": "attachment; filename=modello-contatti.csv"})
