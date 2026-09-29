import json
import math
import os
from datetime import datetime
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

from questions import AREAS, SCALE
from scoring import calcola, livello

app = Flask(__name__)

# Su Render la variabile DATABASE_URL punta al database Postgres.
# In locale, senza variabile, usa un file SQLite.
db_url = os.environ.get("DATABASE_URL", "sqlite:///radiografia.db")
# Indica esplicitamente il driver psycopg2 (installato da requirements.txt):
# le versioni recenti di SQLAlchemy altrimenti cercano "psycopg" (v3).
for prefisso in ("postgres://", "postgresql://"):
    if db_url.startswith(prefisso):
        db_url = "postgresql+psycopg2://" + db_url[len(prefisso):]
        break
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-cambiami")

db = SQLAlchemy(app)


# ------------------------------------------------------------------ modelli
class Utente(db.Model):
    """Commerciale / consulente che vende ed eroga la radiografia."""
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    telefono = db.Column(db.String(40))
    ruolo = db.Column(db.String(20), default="commerciale")  # "admin" o "commerciale"
    attivo = db.Column(db.Boolean, default=True)
    approvato = db.Column(db.Boolean, default=True)   # False = richiesta di accesso in attesa
    ultimo_accesso = db.Column(db.DateTime)
    creato_il = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def in_attesa(self):
        return self.approvato is False

    def imposta_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def verifica_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def is_admin(self):
        return self.ruolo == "admin"


class Valutazione(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    utente_id = db.Column(db.Integer, db.ForeignKey("utente.id"), nullable=False)
    studio = db.Column(db.String(200), nullable=False)
    referente = db.Column(db.String(200))
    citta = db.Column(db.String(120))
    email_cliente = db.Column(db.String(200))
    telefono_cliente = db.Column(db.String(40))
    note = db.Column(db.Text)
    risposte = db.Column(db.Text, nullable=False)   # JSON
    punteggi = db.Column(db.Text, nullable=False)   # JSON
    creata_il = db.Column(db.DateTime, default=datetime.utcnow)


class Servizio(db.Model):
    """Voce del listino (consulenze, pacchetti, formazione...)."""
    id = db.Column(db.Integer, primary_key=True)
    codice = db.Column(db.String(30))
    descrizione = db.Column(db.String(300), nullable=False)
    dettaglio = db.Column(db.Text)
    unita = db.Column(db.String(30), default="a corpo")
    prezzo = db.Column(db.Float, default=0)
    iva = db.Column(db.Float, default=22)
    area_id = db.Column(db.String(40))          # collega il servizio a un'area della radiografia
    attivo = db.Column(db.Boolean, default=True)


class Preventivo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    anno = db.Column(db.Integer, nullable=False)
    numero = db.Column(db.Integer, nullable=False)
    utente_id = db.Column(db.Integer, db.ForeignKey("utente.id"), nullable=False)
    valutazione_id = db.Column(db.Integer, db.ForeignKey("valutazione.id"))
    stato = db.Column(db.String(20), default="bozza")   # bozza, inviato, accettato, rifiutato
    data = db.Column(db.Date, nullable=False)
    validita_giorni = db.Column(db.Integer, default=30)
    cliente = db.Column(db.String(200), nullable=False)
    referente = db.Column(db.String(200))
    indirizzo = db.Column(db.String(300))
    citta = db.Column(db.String(120))
    piva_cliente = db.Column(db.String(40))
    email_cliente = db.Column(db.String(200))
    telefono_cliente = db.Column(db.String(40))
    oggetto = db.Column(db.String(300))
    righe = db.Column(db.Text, nullable=False, default="[]")   # JSON: descrizione, qta, prezzo, sconto, iva
    sconto_globale = db.Column(db.Float, default=0)
    note = db.Column(db.Text)
    condizioni = db.Column(db.Text)
    creato_il = db.Column(db.DateTime, default=datetime.utcnow)
    modificato_il = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def codice(self):
        return f"{self.anno}/{self.numero:03d}"


class Impostazioni(db.Model):
    """Dati della tua azienda: compaiono nell'intestazione dei preventivi."""
    id = db.Column(db.Integer, primary_key=True)
    ragione_sociale = db.Column(db.String(200), default="La tua azienda")
    indirizzo = db.Column(db.String(300))
    piva = db.Column(db.String(40))
    email = db.Column(db.String(200))
    telefono = db.Column(db.String(40))
    sito = db.Column(db.String(200))
    iban = db.Column(db.String(60))
    condizioni_default = db.Column(db.Text, default=(
        "Pagamento: 50% all'accettazione, saldo a fine attività.\n"
        "I prezzi si intendono IVA esclusa, salvo diversa indicazione."))
    validita_default = db.Column(db.Integer, default=30)


def impostazioni():
    imp = db.session.get(Impostazioni, 1)
    if not imp:
        imp = Impostazioni(id=1)
        db.session.add(imp)
        db.session.commit()
    return imp


LISTINO_INIZIALE = [
    ("RX-01", "Radiografia gestionale dello studio", "Analisi iniziale, incontro di restituzione e report", "a corpo", 490, None),
    ("CL-01", "Protocolli clinici e percorso paziente", "Redazione protocolli per le prestazioni principali", "a corpo", 1200, "clinica"),
    ("MK-01", "Piano marketing annuale", "Analisi canali, obiettivi, calendario attività", "a corpo", 1500, "marketing"),
    ("MK-02", "Gestione recensioni e scheda Google", "Setup e gestione mensile", "mese", 180, "marketing"),
    ("EP-01", "Formazione segreteria e accoglienza", "Script telefonico e gestione primo contatto", "giornata", 850, "esperienza"),
    ("EC-01", "Controllo di gestione e KPI", "Costo orario poltrona, cruscotto mensile", "a corpo", 1400, "economico"),
    ("TM-01", "Organigramma, mansionario e obiettivi", "Ruoli, riunioni, sistema incentivante", "a corpo", 1100, "team"),
    ("OR-01", "Riorganizzazione agenda e no-show", "Agenda a blocchi e promemoria automatici", "a corpo", 900, "organizzazione"),
    ("DG-01", "Consulenza digitalizzazione studio", "Scelta gestionale e prenotazione online", "a corpo", 950, "digitale"),
    ("CO-01", "Audit compliance GDPR e sicurezza", "Verifica documentale e scadenzario", "a corpo", 800, "compliance"),
    ("AF-01", "Affiancamento consulenziale", "Incontro in studio di mezza giornata", "incontro", 350, None),
]


def crea_dati_iniziali():
    impostazioni()
    if not Servizio.query.first():
        for cod, desc, det, un, pr, area in LISTINO_INIZIALE:
            db.session.add(Servizio(codice=cod, descrizione=desc, dettaglio=det, unita=un, prezzo=pr, iva=22, area_id=area))
        db.session.commit()


def crea_admin_iniziale():
    """Al primo avvio crea l'amministratore dalle variabili ADMIN_EMAIL / ADMIN_PASSWORD."""
    if Utente.query.filter_by(ruolo="admin").first():
        return
    email = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
    pw = os.environ.get("ADMIN_PASSWORD", "admin123")
    u = Utente(nome=os.environ.get("ADMIN_NOME", "Amministratore"), email=email, ruolo="admin")
    u.imposta_password(pw)
    db.session.add(u)
    db.session.commit()


def aggiorna_schema():
    """Aggiunge al database le colonne nuove dei modelli (create_all crea solo le tabelle mancanti)."""
    if not hasattr(db, "engine"):
        return
    from sqlalchemy import inspect, text
    ispettore = inspect(db.engine)
    with db.engine.begin() as conn:
        for tabella in db.metadata.sorted_tables:
            if not ispettore.has_table(tabella.name):
                continue
            esistenti = {c["name"] for c in ispettore.get_columns(tabella.name)}
            for col in tabella.columns:
                if col.name not in esistenti:
                    tipo = col.type.compile(dialect=db.engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{tabella.name}" ADD COLUMN "{col.name}" {tipo}'))


with app.app_context():
    db.create_all()
    try:
        aggiorna_schema()
    except Exception as e:  # non bloccare l'avvio: l'errore resta visibile nei log di Render
        print(f"ATTENZIONE: aggiornamento schema non riuscito: {e}", flush=True)
    crea_admin_iniziale()
    crea_dati_iniziali()


# ------------------------------------------------------------------ accesso
@app.before_request
def carica_utente():
    g.utente = None
    uid = session.get("uid")
    if uid:
        u = db.session.get(Utente, uid)
        if u and u.attivo:
            g.utente = u
        else:
            session.clear()


def login_richiesto(f):
    @wraps(f)
    def w(*a, **k):
        if not g.utente:
            return redirect(url_for("login", next=request.path))
        return f(*a, **k)
    return w


def admin_richiesto(f):
    @wraps(f)
    @login_richiesto
    def w(*a, **k):
        if not g.utente.is_admin:
            abort(403)
        return f(*a, **k)
    return w


def valutazione_visibile(vid):
    """Il commerciale vede solo le proprie valutazioni, l'admin tutte."""
    v = db.session.get(Valutazione, vid) or abort(404)
    if not g.utente.is_admin and v.utente_id != g.utente.id:
        abort(403)
    return v


@app.context_processor
def iniezioni():
    return {"utente": g.get("utente")}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = Utente.query.filter_by(email=request.form["email"].strip().lower()).first()
        if not u or not u.verifica_password(request.form["password"]):
            flash("Email o password non corretti.")
        elif u.in_attesa:
            flash("La tua richiesta di accesso è in attesa di approvazione da parte dell'amministratore.")
        elif not u.attivo:
            flash("Il tuo account è disattivato. Contatta l'amministratore.")
        else:
            session.clear()
            session["uid"] = u.id
            session.permanent = True
            u.ultimo_accesso = datetime.utcnow()
            db.session.commit()
            dest = request.args.get("next", "")
            if dest.startswith("/") and not dest.startswith("//"):
                return redirect(dest)
            return redirect(url_for("admin") if u.is_admin else url_for("index"))
    return render_template("login.html")


@app.route("/registrati", methods=["GET", "POST"])
def registrati():
    """Il commerciale chiede l'accesso: potrà entrare solo dopo l'attivazione da /admin."""
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        if not nome or "@" not in email:
            flash("Inserisci nome ed email validi.")
        elif len(pw) < 8:
            flash("La password deve avere almeno 8 caratteri.")
        elif pw != request.form.get("conferma", ""):
            flash("Le due password non coincidono.")
        elif Utente.query.filter_by(email=email).first():
            flash("Esiste già un account o una richiesta con questa email.")
        else:
            u = Utente(nome=nome, email=email, telefono=request.form.get("telefono", "").strip(),
                       ruolo="commerciale", attivo=False, approvato=False)
            u.imposta_password(pw)
            db.session.add(u)
            db.session.commit()
            return render_template("registrati.html", inviata=True)
    return render_template("registrati.html", inviata=False)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/profilo", methods=["GET", "POST"])
@login_richiesto
def profilo():
    if request.method == "POST":
        if not g.utente.verifica_password(request.form["attuale"]):
            flash("La password attuale non è corretta.")
        elif len(request.form["nuova"]) < 8:
            flash("La nuova password deve avere almeno 8 caratteri.")
        else:
            g.utente.imposta_password(request.form["nuova"])
            db.session.commit()
            flash("Password aggiornata.")
            return redirect(url_for("index"))
    return render_template("profilo.html")


# ------------------------------------------------------------------ pannello amministratore
@app.route("/admin")
@admin_richiesto
def admin():
    utenti = Utente.query.order_by(Utente.nome).all()
    in_attesa = [u for u in utenti if u.in_attesa]
    account = [u for u in utenti if not u.in_attesa]
    valutazioni = Valutazione.query.all()
    preventivi_tutti = Preventivo.query.all()
    conteggi = {u.id: {"radiografie": 0, "preventivi": 0, "accettato": 0.0} for u in utenti}
    for v in valutazioni:
        if v.utente_id in conteggi:
            conteggi[v.utente_id]["radiografie"] += 1
    accettato_totale = 0.0
    for p in preventivi_tutti:
        if p.utente_id in conteggi:
            conteggi[p.utente_id]["preventivi"] += 1
        if p.stato == "accettato":
            imp = calcola_totali(json.loads(p.righe), p.sconto_globale)["imponibile"]
            accettato_totale += imp
            if p.utente_id in conteggi:
                conteggi[p.utente_id]["accettato"] += imp
    kpi = {
        "commerciali": sum(1 for u in account if u.attivo and not u.is_admin),
        "in_attesa": len(in_attesa),
        "radiografie": len(valutazioni),
        "preventivi": len(preventivi_tutti),
        "accettato": accettato_totale,
    }
    return render_template("admin.html", in_attesa=in_attesa, account=account, conteggi=conteggi, kpi=kpi)


@app.post("/admin/utenti")
@admin_richiesto
def admin_crea_utente():
    email = request.form["email"].strip().lower()
    if Utente.query.filter_by(email=email).first():
        flash("Esiste già un utente con questa email.")
    elif len(request.form["password"]) < 8:
        flash("La password deve avere almeno 8 caratteri.")
    else:
        u = Utente(nome=request.form["nome"].strip(), email=email,
                   telefono=request.form.get("telefono", "").strip(),
                   ruolo=request.form.get("ruolo", "commerciale"), attivo=True, approvato=True)
        u.imposta_password(request.form["password"])
        db.session.add(u)
        db.session.commit()
        flash(f"Account attivo per {u.nome}: può entrare subito con {u.email}.")
    return redirect(url_for("admin"))


@app.post("/admin/utenti/<int:uid>/attiva")
@admin_richiesto
def admin_attiva(uid):
    u = db.session.get(Utente, uid) or abort(404)
    u.approvato = True
    u.attivo = True
    db.session.commit()
    flash(f"Accesso attivato per {u.nome}.")
    return redirect(url_for("admin"))


@app.post("/admin/utenti/<int:uid>/rifiuta")
@admin_richiesto
def admin_rifiuta(uid):
    u = db.session.get(Utente, uid) or abort(404)
    if not u.in_attesa:
        abort(400)
    db.session.delete(u)
    db.session.commit()
    flash(f"Richiesta di {u.nome} rifiutata.")
    return redirect(url_for("admin"))


@app.post("/admin/utenti/<int:uid>/stato")
@admin_richiesto
def cambia_stato(uid):
    u = db.session.get(Utente, uid) or abort(404)
    if u.id == g.utente.id:
        flash("Non puoi disattivare il tuo stesso account.")
    else:
        u.attivo = not u.attivo
        db.session.commit()
        flash(f"Account di {u.nome} {'riattivato' if u.attivo else 'disattivato'}.")
    return redirect(url_for("admin"))


@app.post("/admin/utenti/<int:uid>/password")
@admin_richiesto
def reimposta_password(uid):
    u = db.session.get(Utente, uid) or abort(404)
    pw = request.form["password"]
    if len(pw) < 8:
        flash("La password deve avere almeno 8 caratteri.")
    else:
        u.imposta_password(pw)
        db.session.commit()
        flash(f"Password di {u.nome} reimpostata.")
    return redirect(url_for("admin"))


@app.route("/commerciali")
def commerciali():
    return redirect(url_for("admin"))


# ------------------------------------------------------------------ valutazioni
def media_di(punteggi):
    return round(sum(punteggi.values()) / len(punteggi)) if punteggi else 0


@app.route("/")
@login_richiesto
def index():
    q = Valutazione.query
    filtro = request.args.get("commerciale", type=int)
    if not g.utente.is_admin:
        q = q.filter_by(utente_id=g.utente.id)
    elif filtro:
        q = q.filter_by(utente_id=filtro)
    utenti = {u.id: u for u in Utente.query.all()}
    righe = [{"v": v, "media": media_di(json.loads(v.punteggi)), "comm": utenti.get(v.utente_id)}
             for v in q.order_by(Valutazione.creata_il.desc()).all()]
    return render_template("index.html", righe=righe, utenti=utenti.values(), filtro=filtro)


@app.route("/nuova", methods=["GET", "POST"])
@login_richiesto
def nuova():
    if request.method == "POST":
        risposte = {
            d["id"]: request.form.get(d["id"])
            for a in AREAS for d in a["domande"]
            if request.form.get(d["id"])
        }
        v = Valutazione(
            utente_id=g.utente.id,
            studio=request.form["studio"].strip(),
            referente=request.form.get("referente", "").strip(),
            citta=request.form.get("citta", "").strip(),
            email_cliente=request.form.get("email_cliente", "").strip(),
            telefono_cliente=request.form.get("telefono_cliente", "").strip(),
            note=request.form.get("note", "").strip(),
            risposte=json.dumps(risposte),
            punteggi=json.dumps(calcola(risposte)),
        )
        db.session.add(v)
        db.session.commit()
        return redirect(url_for("risultato", vid=v.id))
    return render_template("nuova.html", aree=AREAS, scala=SCALE)


@app.route("/valutazione/<int:vid>")
@login_richiesto
def risultato(vid):
    v = valutazione_visibile(vid)
    punteggi = json.loads(v.punteggi)
    report = []
    for area in AREAS:
        s = punteggi.get(area["id"], 0)
        etichetta, classe = livello(s)
        report.append({
            "nome": area["nome"], "breve": area.get("breve", area["nome"]), "punteggio": s,
            "livello": etichetta, "classe": classe, "azioni": area["azioni"],
        })
    priorita = sorted(report, key=lambda r: r["punteggio"])
    return render_template(
        "risultato.html", v=v, report=report, priorita=priorita, media=media_di(punteggi),
        radar=radar_svg(report), commerciale=db.session.get(Utente, v.utente_id),
    )


@app.post("/valutazione/<int:vid>/elimina")
@login_richiesto
def elimina(vid):
    v = valutazione_visibile(vid)
    db.session.delete(v)
    db.session.commit()
    return redirect(url_for("index"))


def radar_svg(report, cx=300, cy=250, r=165, obiettivo=75):
    """Calcola le coordinate del grafico a ragno (disegnato in SVG nel template)."""
    n = len(report)

    def punto(i, valore, raggio=r):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        return (cx + raggio * valore / 100 * math.cos(ang),
                cy + raggio * valore / 100 * math.sin(ang))

    def poligono(valori):
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in (punto(i, val) for i, val in enumerate(valori)))

    assi, etichette, punti = [], [], []
    for i, rr in enumerate(report):
        assi.append(punto(i, 100))
        lx, ly = punto(i, 100, r + 16)
        ancora = "middle" if abs(lx - cx) < 10 else ("start" if lx > cx else "end")
        if ly < cy - 10:          # etichette in alto: salgono sopra la punta
            ly -= 8
        elif abs(ly - cy) <= 10:  # laterali: centrate sull'asse
            ly += 6
        else:
            ly += 22
        etichette.append({"x": lx, "y": ly, "ancora": ancora, "nome": rr["breve"], "punteggio": rr["punteggio"]})
        px, py = punto(i, rr["punteggio"])
        punti.append({"x": px, "y": py, "classe": rr["classe"]})
    return {
        "cx": cx, "cy": cy, "r": r, "assi": assi, "etichette": etichette, "punti": punti,
        "griglia": [poligono([liv] * n) for liv in (25, 50, 75, 100)],
        "obiettivo": poligono([obiettivo] * n),
        "studio": poligono([rr["punteggio"] for rr in report]),
    }


# ------------------------------------------------------------------ preventivi
STATI = {
    "bozza": "Bozza",
    "inviato": "Inviato",
    "accettato": "Accettato",
    "rifiutato": "Rifiutato",
}


@app.template_filter("ora_locale")
def ora_locale(dt, formato="%d/%m/%Y %H:%M"):
    """Le date sono salvate in UTC: le mostra con l'ora italiana."""
    if not dt:
        return ""
    from datetime import timezone
    from zoneinfo import ZoneInfo
    return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Rome")).strftime(formato)


@app.template_filter("euro")
def euro(valore):
    s = f"{float(valore or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€ {s}"


@app.template_filter("num")
def num(valore):
    v = float(valore or 0)
    return str(int(v)) if v == int(v) else f"{v:.2f}".rstrip("0").replace(".", ",")


def a_numero(testo, default=0.0):
    try:
        return float(str(testo).replace("€", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return default


def calcola_totali(righe, sconto_globale=0):
    """Imponibile per riga (quantità × prezzo − sconto riga), poi sconto globale, poi IVA per aliquota."""
    lordo, dettaglio_iva = 0.0, {}
    for r in righe:
        imp = r["qta"] * r["prezzo"] * (1 - r["sconto"] / 100)
        r["importo"] = round(imp, 2)
        lordo += imp
    fattore = 1 - (sconto_globale or 0) / 100
    for r in righe:
        dettaglio_iva.setdefault(r["iva"], 0.0)
        dettaglio_iva[r["iva"]] += r["importo"] * fattore
    imponibile = lordo * fattore
    iva = {aliq: round(base * aliq / 100, 2) for aliq, base in sorted(dettaglio_iva.items())}
    totale_iva = sum(iva.values())
    return {
        "lordo": round(lordo, 2),
        "sconto": round(lordo - imponibile, 2),
        "imponibile": round(imponibile, 2),
        "iva": iva,
        "basi_iva": {k: round(v, 2) for k, v in dettaglio_iva.items()},
        "totale_iva": round(totale_iva, 2),
        "totale": round(imponibile + totale_iva, 2),
    }


def righe_da_form(form):
    righe = []
    for desc, det, qta, prezzo, sconto, iva, unita in zip(
            form.getlist("r_desc"), form.getlist("r_det"), form.getlist("r_qta"), form.getlist("r_prezzo"),
            form.getlist("r_sconto"), form.getlist("r_iva"), form.getlist("r_unita")):
        if not desc.strip():
            continue
        righe.append({
            "descrizione": desc.strip(), "dettaglio": det.strip(), "unita": unita.strip(),
            "qta": a_numero(qta, 1), "prezzo": a_numero(prezzo),
            "sconto": min(max(a_numero(sconto), 0), 100), "iva": a_numero(iva, 22),
        })
    return righe


def preventivo_visibile(pid):
    p = db.session.get(Preventivo, pid) or abort(404)
    if not g.utente.is_admin and p.utente_id != g.utente.id:
        abort(403)
    return p


def prossimo_numero(anno):
    numeri = [p.numero for p in Preventivo.query.filter_by(anno=anno).all()]
    return (max(numeri) if numeri else 0) + 1


def listino_json():
    return [{"codice": s.codice or "", "descrizione": s.descrizione, "dettaglio": s.dettaglio or "",
             "unita": s.unita or "", "prezzo": s.prezzo or 0, "iva": s.iva if s.iva is not None else 22}
            for s in Servizio.query.order_by(Servizio.codice).all() if s.attivo]


def riga_da_servizio(s):
    return {"descrizione": s.descrizione, "dettaglio": s.dettaglio or "", "unita": s.unita or "",
            "qta": 1, "prezzo": s.prezzo or 0, "sconto": 0, "iva": s.iva if s.iva is not None else 22}


def suggerimenti_da_valutazione(v):
    """Aree della radiografia (dalla più critica) con le voci di listino collegate."""
    punteggi = json.loads(v.punteggi)
    servizi = [s for s in Servizio.query.all() if s.attivo]
    aree = []
    for a in AREAS:
        s_area = [riga_da_servizio(s) for s in servizi if s.area_id == a["id"]]
        if not s_area:
            continue
        pt = punteggi.get(a["id"], 0)
        etichetta, classe = livello(pt)
        aree.append({"nome": a["nome"], "punteggio": pt, "livello": etichetta, "classe": classe, "servizi": s_area})
    return sorted(aree, key=lambda x: x["punteggio"])


def suggerimenti_per(p):
    if not p.valutazione_id:
        return None
    v = db.session.get(Valutazione, p.valutazione_id)
    if not v or (not g.utente.is_admin and v.utente_id != g.utente.id):
        return None
    return {"valutazione": v, "aree": suggerimenti_da_valutazione(v)}


def valutazioni_collegabili():
    q = Valutazione.query if g.utente.is_admin else Valutazione.query.filter_by(utente_id=g.utente.id)
    return q.order_by(Valutazione.creata_il.desc()).all()


def salva_da_form(p, form):
    p.cliente = form["cliente"].strip()
    for campo in ("referente", "indirizzo", "citta", "piva_cliente", "email_cliente",
                  "telefono_cliente", "oggetto", "note", "condizioni"):
        setattr(p, campo, form.get(campo, "").strip())
    p.data = datetime.strptime(form["data"], "%Y-%m-%d").date() if form.get("data") else datetime.now().date()
    p.validita_giorni = int(a_numero(form.get("validita_giorni"), 30))
    p.sconto_globale = min(max(a_numero(form.get("sconto_globale")), 0), 100)
    p.righe = json.dumps(righe_da_form(form))
    if form.get("stato") in STATI:
        p.stato = form["stato"]
    vid = form.get("valutazione_id", type=int)
    if vid and (g.utente.is_admin or getattr(db.session.get(Valutazione, vid), "utente_id", None) == g.utente.id):
        p.valutazione_id = vid
    elif "valutazione_id" in form and not form.get("valutazione_id"):
        p.valutazione_id = None
    p.modificato_il = datetime.utcnow()


@app.route("/preventivi")
@login_richiesto
def preventivi():
    q = Preventivo.query
    if not g.utente.is_admin:
        q = q.filter_by(utente_id=g.utente.id)
    elif request.args.get("commerciale", type=int):
        q = q.filter_by(utente_id=request.args.get("commerciale", type=int))
    if request.args.get("stato") in STATI:
        q = q.filter_by(stato=request.args["stato"])
    elenco = q.order_by(Preventivo.creato_il.desc()).all()
    cerca = request.args.get("q", "").strip().lower()
    if cerca:
        elenco = [p for p in elenco if cerca in " ".join(
            [p.codice, p.cliente or "", p.oggetto or "", p.citta or ""]).lower()]
    utenti = {u.id: u for u in Utente.query.all()}
    righe = []
    for p in elenco:
        t = calcola_totali(json.loads(p.righe), p.sconto_globale)
        righe.append({"p": p, "tot": t, "comm": utenti.get(p.utente_id)})
    riepilogo = {s: sum(r["tot"]["imponibile"] for r in righe if r["p"].stato == s) for s in STATI}
    return render_template("preventivi.html", righe=righe, stati=STATI, riepilogo=riepilogo,
                           utenti=utenti.values(), args=request.args)


@app.route("/preventivi/nuovo", methods=["GET", "POST"])
@login_richiesto
def preventivo_nuovo():
    imp = impostazioni()
    if request.method == "POST":
        anno = datetime.now().year
        p = Preventivo(anno=anno, numero=prossimo_numero(anno), utente_id=g.utente.id)
        salva_da_form(p, request.form)
        db.session.add(p)
        db.session.commit()
        flash(f"Preventivo {p.codice} salvato.")
        return redirect(url_for("preventivo_modifica", pid=p.id))

    # nuovo preventivo, eventualmente precompilato da una radiografia
    p = Preventivo(data=datetime.now().date(), validita_giorni=imp.validita_default,
                   condizioni=imp.condizioni_default, stato="bozza", sconto_globale=0, cliente="")
    righe = []
    vid = request.args.get("valutazione", type=int)
    if vid:
        v = valutazione_visibile(vid)
        p.valutazione_id = v.id
        p.cliente, p.referente, p.citta = v.studio, v.referente, v.citta
        p.email_cliente, p.telefono_cliente = v.email_cliente, v.telefono_cliente
        p.oggetto = "Piano di miglioramento a seguito della radiografia dello studio"
        # preselezione: le voci di listino collegate alle aree sotto 75
        for area in suggerimenti_da_valutazione(v):
            if area["punteggio"] < 75:
                righe.extend(area["servizi"])
    return render_template("preventivo_form.html", p=p, righe=righe, stati=STATI, listino=listino_json(), nuovo=True,
                           suggerimenti=suggerimenti_per(p), valutazioni=valutazioni_collegabili())


@app.route("/preventivi/<int:pid>", methods=["GET", "POST"])
@login_richiesto
def preventivo_modifica(pid):
    p = preventivo_visibile(pid)
    if request.method == "POST":
        salva_da_form(p, request.form)
        db.session.commit()
        flash(f"Preventivo {p.codice} aggiornato.")
        if request.form.get("dopo") == "stampa":
            return redirect(url_for("preventivo_stampa", pid=p.id))
        return redirect(url_for("preventivo_modifica", pid=p.id))
    return render_template("preventivo_form.html", p=p, righe=json.loads(p.righe), stati=STATI,
                           listino=listino_json(), nuovo=False, suggerimenti=suggerimenti_per(p),
                           valutazioni=valutazioni_collegabili())


@app.route("/preventivi/<int:pid>/stampa")
@login_richiesto
def preventivo_stampa(pid):
    p = preventivo_visibile(pid)
    righe = json.loads(p.righe)
    from datetime import timedelta
    return render_template("preventivo_stampa.html", p=p, righe=righe,
                           tot=calcola_totali(righe, p.sconto_globale), imp=impostazioni(),
                           commerciale=db.session.get(Utente, p.utente_id),
                           scadenza=p.data + timedelta(days=p.validita_giorni or 0))


@app.post("/preventivi/<int:pid>/stato")
@login_richiesto
def preventivo_stato(pid):
    p = preventivo_visibile(pid)
    if request.form.get("stato") in STATI:
        p.stato = request.form["stato"]
        p.modificato_il = datetime.utcnow()
        db.session.commit()
    return redirect(request.referrer or url_for("preventivi"))


@app.post("/preventivi/<int:pid>/duplica")
@login_richiesto
def preventivo_duplica(pid):
    o = preventivo_visibile(pid)
    anno = datetime.now().year
    p = Preventivo(anno=anno, numero=prossimo_numero(anno), utente_id=g.utente.id, stato="bozza",
                   data=datetime.now().date(), valutazione_id=o.valutazione_id)
    for campo in ("validita_giorni", "cliente", "referente", "indirizzo", "citta", "piva_cliente", "email_cliente",
                  "telefono_cliente", "oggetto", "righe", "sconto_globale", "note", "condizioni"):
        setattr(p, campo, getattr(o, campo))
    db.session.add(p)
    db.session.commit()
    flash(f"Creato {p.codice} come copia di {o.codice}.")
    return redirect(url_for("preventivo_modifica", pid=p.id))


@app.post("/preventivi/<int:pid>/elimina")
@login_richiesto
def preventivo_elimina(pid):
    p = preventivo_visibile(pid)
    db.session.delete(p)
    db.session.commit()
    flash(f"Preventivo {p.codice} eliminato.")
    return redirect(url_for("preventivi"))


# ------------------------------------------------------------------ listino e impostazioni (solo admin)
@app.route("/listino", methods=["GET", "POST"])
@admin_richiesto
def listino():
    if request.method == "POST":
        sid = request.form.get("id", type=int)
        s = db.session.get(Servizio, sid) if sid else Servizio()
        s.codice = request.form.get("codice", "").strip()
        s.descrizione = request.form["descrizione"].strip()
        s.dettaglio = request.form.get("dettaglio", "").strip()
        s.unita = request.form.get("unita", "").strip() or "a corpo"
        s.prezzo = a_numero(request.form.get("prezzo"))
        s.iva = a_numero(request.form.get("iva"), 22)
        s.area_id = request.form.get("area_id") or None
        if not sid:
            db.session.add(s)
        db.session.commit()
        flash("Listino aggiornato.")
        return redirect(url_for("listino"))
    servizi = sorted(Servizio.query.all(), key=lambda s: (not s.attivo, s.codice or ""))
    return render_template("listino.html", servizi=servizi, aree=AREAS)


@app.post("/listino/<int:sid>/stato")
@admin_richiesto
def listino_stato(sid):
    s = db.session.get(Servizio, sid) or abort(404)
    s.attivo = not s.attivo
    db.session.commit()
    return redirect(url_for("listino"))


@app.route("/impostazioni", methods=["GET", "POST"])
@admin_richiesto
def impostazioni_azienda():
    imp = impostazioni()
    if request.method == "POST":
        for campo in ("ragione_sociale", "indirizzo", "piva", "email", "telefono", "sito", "iban", "condizioni_default"):
            setattr(imp, campo, request.form.get(campo, "").strip())
        imp.validita_default = int(a_numero(request.form.get("validita_default"), 30))
        db.session.commit()
        flash("Dati aziendali salvati.")
        return redirect(url_for("impostazioni_azienda"))
    return render_template("impostazioni.html", imp=imp)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
