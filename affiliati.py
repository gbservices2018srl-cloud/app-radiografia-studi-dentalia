"""
Studi affiliati e cartina d'Italia.

- Admin → Studi affiliati (/admin/studi): elenco, aggiunta a mano, modifica, nascondi, elimina.
- In automatico: quando un contratto di affiliazione viene firmato lo studio entra da solo
  (`studio_da_contratto()`, chiamata da contratti.registra_firma) con i dati del contratto/scheda cliente.
  All'avvio `sincronizza_firmati()` recupera i contratti firmati prima di questa funzione.
- Coordinate: ricavate dall'indirizzo con OpenStreetMap (Nominatim), oppure scritte a mano.
- Pubblico: /api/studi-affiliati.json (CORS per www.dentaliagroup.it), letto dalla sezione «La rete Dentalia»
  della home del sito. Mostra città e, se `mostra_nome`, il nome dello studio. Mai indirizzi o altri dati.
"""
import json
import math
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime

from flask import abort, flash, jsonify, redirect, render_template, request, url_for

from app import Contratto, StudioAffiliato, admin_richiesto, app, db

NOMINATIM = "https://nominatim.openstreetmap.org/search"
ORIGINI_SITO = ("https://www.dentaliagroup.it", "https://dentaliagroup.it")
# stessa proiezione della cartina static/mappa/italia.svg (viewBox 0 0 537 636)
LON0, LAT1, K, COS = 6.55, 47.15, 60.0, math.cos(math.radians(42))
_geo_lock = threading.Lock()


def proietta(lat, lng):
    return round((lng - LON0) * COS * K, 1), round((LAT1 - lat) * K, 1)


def in_italia(lat, lng):
    return lat is not None and lng is not None and 35.4 <= lat <= 47.2 and 6.5 <= lng <= 18.7


def geocodifica(indirizzo="", cap="", citta="", provincia=""):
    """(lat, lng) da OpenStreetMap: prima l'indirizzo completo, poi solo il comune. None se non trovato."""
    if app.config.get("TESTING"):
        return app.config.get("GEO_FINTO", (39.2238, 9.1217))
    tentativi = []
    if indirizzo and citta:
        tentativi.append(", ".join(x for x in (indirizzo, cap, citta, provincia) if x))
    if citta:
        tentativi.append(", ".join(x for x in (citta, provincia) if x))
    for q in tentativi:
        with _geo_lock:  # Nominatim chiede massimo una richiesta al secondo
            try:
                url = NOMINATIM + "?" + urllib.parse.urlencode(
                    {"q": q, "countrycodes": "it", "format": "json", "limit": 1})
                req = urllib.request.Request(url, headers={
                    "User-Agent": "DentaliaArea/1.0 (https://area.dentaliagroup.it; info@dentaliagroup.it)"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    dati = json.loads(r.read())
            except Exception as err:  # noqa: BLE001
                print(f"STUDI: geocodifica non riuscita per «{q}»: {err}", flush=True)
                dati = []
            finally:
                time.sleep(1.1)
        if dati:
            lat, lng = float(dati[0]["lat"]), float(dati[0]["lon"])
            if in_italia(lat, lng):
                return lat, lng
    return None


def posiziona(s, forza=False):
    if forza or s.lat is None or s.lng is None:
        punto = geocodifica(s.indirizzo, s.cap, s.citta, s.provincia)
        if punto:
            s.lat, s.lng = punto
            s.posizione_auto = True
    return s.lat is not None


def studio_da_contratto(k, contatto=None):
    """Crea o aggiorna lo studio affiliato dal contratto firmato (non tocca quelli modificati a mano)."""
    contatto = contatto or contatto_del_contratto(k)
    s = StudioAffiliato.query.filter_by(contratto_id=k.id).first()
    if not s and contatto:
        s = StudioAffiliato.query.filter_by(contatto_id=contatto.id).first()
    if s and s.origine == "manuale":
        s.contratto_id = s.contratto_id or k.id
        return s
    nuovo = s is None
    if nuovo:
        s = StudioAffiliato(origine="contratto", visibile=True, mostra_nome=True)
        db.session.add(s)
    nome = (contatto.studio if contatto and contatto.studio else None) or k.ragione_sociale or "Studio Dentalia"
    s.nome = s.nome if (s.nome and not nuovo) else nome[:200]
    s.contratto_id, s.contatto_id = k.id, (contatto.id if contatto else s.contatto_id)
    for campo in ("indirizzo", "cap", "citta", "provincia"):
        valore = getattr(k, campo, None) or (getattr(contatto, campo, None) if contatto else None)
        if valore and not getattr(s, campo):
            setattr(s, campo, str(valore).strip()[:200])
    s.affiliato_il = s.affiliato_il or k.firmato_il or datetime.utcnow()
    return s


def contatto_del_contratto(k):
    try:
        from contratti import contatto_del
        return contatto_del(k)
    except Exception:  # noqa: BLE001
        return None


def sincronizza_firmati():
    """Contratti firmati senza studio in elenco: li aggiunge (e cerca le coordinate in un thread)."""
    with app.app_context():
        try:
            gia = {r[0] for r in db.session.query(StudioAffiliato.contratto_id).all() if r[0]}
            nuovi = []
            for k in Contratto.query.filter_by(stato="firmato").all():
                if k.id not in gia:
                    nuovi.append(studio_da_contratto(k, contatto_del_contratto(k)))
            db.session.commit()
        except Exception as err:  # noqa: BLE001
            db.session.rollback()
            print(f"STUDI: sincronizzazione non riuscita: {err}", flush=True)
    posiziona_mancanti_in_background()


def posiziona_mancanti_in_background(attesa=0):
    if app.config.get("TESTING"):
        return

    def lavoro():
        time.sleep(attesa)
        with app.app_context():
            for s in StudioAffiliato.query.filter(StudioAffiliato.lat.is_(None)).all():
                if posiziona(s):
                    db.session.commit()

    threading.Thread(target=lavoro, daemon=True, name="studi-geo").start()


# ------------------------------------------------------------------ pagine admin
CAMPI = ("nome", "indirizzo", "cap", "citta", "provincia")


def _leggi_form(s, f):
    for campo in CAMPI:
        setattr(s, campo, (f.get(campo) or "").strip()[:200] or None)
    if s.provincia:
        s.provincia = s.provincia.upper()[:4]
    s.mostra_nome = f.get("mostra_nome") == "1"
    s.visibile = f.get("visibile") == "1"
    try:
        lat, lng = float(f.get("lat", "").replace(",", ".")), float(f.get("lng", "").replace(",", "."))
        if in_italia(lat, lng):
            s.lat, s.lng, s.posizione_auto = lat, lng, False
    except ValueError:
        pass


@app.route("/admin/studi", methods=["GET", "POST"])
@admin_richiesto
def studi_affiliati():
    if request.method == "POST":
        f = request.form
        azione = f.get("azione")
        if azione == "aggiungi":
            if not (f.get("nome") or "").strip() or not (f.get("citta") or "").strip():
                flash("Per aggiungere uno studio servono almeno nome e comune.")
                return redirect(url_for("studi_affiliati"))
            s = StudioAffiliato(origine="manuale", affiliato_il=datetime.utcnow())
            _leggi_form(s, f)
            db.session.add(s)
            trovato = posiziona(s)
            db.session.commit()
            flash(f"«{s.nome}» aggiunto alla rete." + ("" if trovato else
                  " Non ho trovato il punto sulla cartina: scrivi latitudine e longitudine nella scheda."))
        elif azione == "sincronizza":
            sincronizza_firmati()
            flash("Elenco aggiornato con i contratti firmati.")
        return redirect(url_for("studi_affiliati"))
    studi = StudioAffiliato.query.order_by(StudioAffiliato.citta, StudioAffiliato.nome).all()
    punti = [dict(id=s.id, nome=s.nome, citta=s.citta, xy=proietta(s.lat, s.lng), visibile=s.visibile)
             for s in studi if s.lat is not None]
    firmati_senza = Contratto.query.filter_by(stato="firmato").count() - \
        StudioAffiliato.query.filter(StudioAffiliato.contratto_id.isnot(None)).count()
    return render_template("studi.html", studi=studi, punti=punti, firmati_senza=max(0, firmati_senza),
                           visibili=sum(1 for s in studi if s.visibile and s.lat is not None))


@app.route("/admin/studi/<int:sid>", methods=["GET", "POST"])
@admin_richiesto
def studio_affiliato(sid):
    s = db.session.get(StudioAffiliato, sid) or abort(404)
    if request.method == "POST":
        f = request.form
        if f.get("azione") == "elimina":
            nome = s.nome
            db.session.delete(s)
            db.session.commit()
            flash(f"«{nome}» tolto dalla cartina e dall'elenco.")
            return redirect(url_for("studi_affiliati"))
        vecchio = (s.indirizzo, s.cap, s.citta, s.provincia)
        lat_prima = (s.lat, s.lng)
        _leggi_form(s, f)
        s.origine = "manuale" if s.origine == "contratto" else s.origine  # modificato a mano: il contratto non lo sovrascrive
        if f.get("azione") == "riposiziona" or ((s.indirizzo, s.cap, s.citta, s.provincia) != vecchio
                                                and (s.lat, s.lng) == lat_prima):
            if not posiziona(s, forza=True):
                flash("Non ho trovato l'indirizzo sulla cartina: scrivi latitudine e longitudine.")
        db.session.commit()
        flash("Studio salvato.")
        return redirect(url_for("studio_affiliato", sid=s.id))
    xy = proietta(s.lat, s.lng) if s.lat is not None else None
    return render_template("studio.html", s=s, xy=xy)


# ------------------------------------------------------------------ dati pubblici per il sito
def dati_pubblici():
    studi = StudioAffiliato.query.filter(StudioAffiliato.visibile.is_(True), StudioAffiliato.lat.isnot(None)) \
        .order_by(StudioAffiliato.affiliato_il).all()
    return {
        "aggiornato": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "totale": len(studi),
        "citta": len({(s.citta or "").strip().lower() for s in studi if s.citta}),
        "proiezione": {"lon0": LON0, "lat1": LAT1, "k": K, "cos": COS, "viewbox": [0, 0, 537, 636]},
        "studi": [{"nome": s.nome if s.mostra_nome else None, "citta": s.citta,
                   "provincia": s.provincia, "lat": round(s.lat, 4), "lng": round(s.lng, 4),
                   "x": proietta(s.lat, s.lng)[0], "y": proietta(s.lat, s.lng)[1]} for s in studi],
    }


@app.route("/api/studi-affiliati.json")
def studi_pubblici():
    r = jsonify(dati_pubblici())
    origine = request.headers.get("Origin", "")
    r.headers["Access-Control-Allow-Origin"] = origine if origine in ORIGINI_SITO else ORIGINI_SITO[0]
    r.headers["Vary"] = "Origin"
    r.headers["Cache-Control"] = "public, max-age=600"
    r.headers["X-Robots-Tag"] = "noindex"
    return r


if not app.config.get("TESTING") and "unittest" not in sys.modules:
    threading.Thread(target=lambda: (time.sleep(20), sincronizza_firmati()), daemon=True, name="studi-sync").start()
