"""
Pannello KPI: imbuto commerciale (contattati -> appuntamenti -> presentati -> affiliati), preventivi in €,
richiami per commerciale. Ogni numero porta all'elenco che lo compone (filtri `kpi`, `da`, `a` su /contatti
e `da`, `a`, `tipo`, `stato` su /preventivi).
"""
import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import g, render_template, request

from app import (Attivita, Contatto, Contratto, Preventivo, STATI, Utente, app, calcola_totali, db, login_richiesto)

ROMA = ZoneInfo("Europe/Rome")

PERIODI = {"mese": "Questo mese", "30": "Ultimi 30 giorni", "trimestre": "Ultimi 3 mesi", "anno": "Quest'anno",
           "tutto": "Da sempre"}

# filtri KPI sull'elenco contatti: tipo di attività + esito che li definisce
FILTRI_KPI = {
    "contattati": ("Contattati", "chiamata", None),
    "appuntamenti": ("Hanno preso appuntamento", "chiamata", "appuntamento"),
    "presentati": ("Si sono presentati", "appuntamento", "presentato"),
    "non_presentati": ("Non si sono presentati", "appuntamento", "non_presentato"),
    "non_interessati": ("Non interessati", "chiamata", "non_interessato"),
}


def intervallo(args):
    """(da, a) come date (incluse) dal periodo scelto o dalle date esplicite."""
    oggi = datetime.now(ROMA).date()
    try:
        if args.get("da") or args.get("a"):
            da = date.fromisoformat(args["da"]) if args.get("da") else date(2000, 1, 1)
            a = date.fromisoformat(args["a"]) if args.get("a") else oggi
            return da, a, "personalizzato"
    except ValueError:
        pass
    periodo = args.get("periodo") if args.get("periodo") in PERIODI else "mese"
    if periodo == "mese":
        return oggi.replace(day=1), oggi, periodo
    if periodo == "30":
        return oggi - timedelta(days=29), oggi, periodo
    if periodo == "trimestre":
        return oggi - timedelta(days=89), oggi, periodo
    if periodo == "anno":
        return oggi.replace(month=1, day=1), oggi, periodo
    return date(2000, 1, 1), oggi, periodo


def limiti_utc(da, a):
    inizio = datetime.combine(da, time.min, ROMA).astimezone(timezone.utc).replace(tzinfo=None)
    fine = datetime.combine(a + timedelta(days=1), time.min, ROMA).astimezone(timezone.utc).replace(tzinfo=None)
    return inizio, fine


def ids_kpi(chiave, da, a, utente_id=None):
    """Id dei contatti che rientrano in un KPI nel periodo (per l'utente indicato, se c'è)."""
    _, tipo, esito = FILTRI_KPI[chiave]
    inizio, fine = limiti_utc(da, a)
    q = db.session.query(Attivita.contatto_id).filter(Attivita.tipo == tipo, Attivita.quando >= inizio,
                                                     Attivita.quando < fine)
    if esito:
        q = q.filter(Attivita.esito == esito)
    if utente_id:
        q = q.filter(Attivita.utente_id == utente_id)
    return q.distinct()


def perc(parte, totale):
    return round(parte * 100 / totale) if totale else 0


@app.route("/kpi")
@login_richiesto
def kpi():
    da, a, periodo = intervallo(request.args)
    inizio, fine = limiti_utc(da, a)
    if g.utente.is_admin:
        filtro = request.args.get("commerciale", type=int)
    else:
        filtro = g.utente.id
    utenti = Utente.query.filter(Utente.approvato.isnot(False)).order_by(Utente.nome).all()

    def conta(chiave, uid=filtro):
        return db.session.query(db.func.count()).select_from(ids_kpi(chiave, da, a, uid).subquery()).scalar() or 0

    imbuto = {k: conta(k) for k in FILTRI_KPI}

    # preventivi del periodo (per data del preventivo); le bozze non contano come "preventivato"
    q = Preventivo.query.filter(Preventivo.data >= da, Preventivo.data <= a)
    if filtro:
        q = q.filter(Preventivo.utente_id == filtro)
    prev = [(p, calcola_totali(json.loads(p.righe), p.sconto_globale)["imponibile"]) for p in q.all()]
    consegnati = [(p, v) for p, v in prev if p.stato != "bozza"]
    accettati = [(p, v) for p, v in consegnati if p.stato == "accettato"]
    euro_prev = sum(v for _, v in consegnati)
    euro_acc = sum(v for _, v in accettati)
    aff_acc = [(p, v) for p, v in accettati if p.tipo == "affiliazione"]
    serv_acc = [(p, v) for p, v in accettati if p.tipo != "affiliazione"]
    bozze = [(p, v) for p, v in prev if p.stato == "bozza"]
    qk = Contratto.query.filter(Contratto.stato == "firmato", Contratto.firmato_il >= inizio, Contratto.firmato_il < fine)
    if filtro:
        qk = qk.filter(Contratto.utente_id == filtro)
    firmati = qk.count()

    # contatti da chiamare adesso
    adesso = datetime.utcnow()
    qc = Contatto.query
    if filtro:
        qc = qc.filter(Contatto.utente_id == filtro)
    da_chiamare = qc.filter(Contatto.stato.in_(("nuovo", "richiamare")),
                            db.or_(Contatto.richiamare_il.is_(None), Contatto.richiamare_il <= adesso)).count()
    affiliati_totali = qc.filter(Contatto.stato == "cliente").count()

    # richiami per commerciale (chiamate registrate e aperture delle schede nel periodo)
    righe_comm = []
    for u in utenti:
        if filtro and u.id != filtro:
            continue
        att = db.session.query(Attivita.tipo, db.func.count()).filter(
            Attivita.utente_id == u.id, Attivita.quando >= inizio, Attivita.quando < fine,
            Attivita.tipo.in_(("chiamata", "apertura"))).group_by(Attivita.tipo).all()
        att = dict(att)
        lavorati = conta("contattati", u.id)
        app_ = conta("appuntamenti", u.id)
        pres = conta("presentati", u.id)
        acc_u = sum(v for p, v in accettati if p.utente_id == u.id)
        riga = {"u": u, "chiamate": att.get("chiamata", 0), "aperture": att.get("apertura", 0), "lavorati": lavorati,
                "appuntamenti": app_, "presentati": pres, "accettato": acc_u,
                "media": round(att.get("chiamata", 0) / lavorati, 1) if lavorati else 0}
        if any(riga[k] for k in ("chiamate", "aperture", "lavorati", "accettato")) or filtro:
            righe_comm.append(riga)
    righe_comm.sort(key=lambda r: (-r["chiamate"], r["u"].nome))

    filtri_url = {"da": da.isoformat(), "a": a.isoformat()}
    if filtro and g.utente.is_admin:
        filtri_url["commerciale"] = filtro
    return render_template(
        "kpi.html", periodi=PERIODI, periodo=periodo, da=da, a=a, utenti=utenti, filtro=filtro,
        imbuto=imbuto, perc=perc, filtri_url=filtri_url, da_chiamare=da_chiamare, affiliati_totali=affiliati_totali,
        euro_prev=euro_prev, euro_acc=euro_acc, n_prev=len(consegnati), n_acc=len(accettati),
        n_aff=len(aff_acc), euro_aff=sum(v for _, v in aff_acc), n_serv=len(serv_acc),
        euro_serv=sum(v for _, v in serv_acc), n_bozze=len(bozze), euro_bozze=sum(v for _, v in bozze),
        n_rif=len([1 for p, _ in consegnati if p.stato == "rifiutato"]), righe_comm=righe_comm, firmati=firmati,
        nome_filtro=next((u.nome for u in utenti if u.id == filtro), None))
