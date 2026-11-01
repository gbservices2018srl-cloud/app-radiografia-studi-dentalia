"""
/gestione — pubblicazione automatica sui social (Instagram e pagina LinkedIn di Dentalia). Solo admin.

Come funziona:
  1. L'agente (dentro l'app, nessun servizio esterno) ogni N giorni (default 3) prepara una BOZZA:
     prende un'idea dal piano editoriale (social_piano.IDEE + idee aggiunte), a rotazione per tema,
     genera la grafica Dentalia (grafica_social.py) e la didascalia, e la programma per la data giusta.
     Mai più di MAX_BOZZE bozze in attesa. Avvisa l'admin via email.
  2. L'admin la guarda, la corregge se vuole e la APPROVA (oppure la scarta).
  3. Un controllo ogni 10 minuti pubblica i post approvati la cui data è arrivata:
       Instagram  -> Graph API (graph.instagram.com o graph.facebook.com: si capisce da solo alla verifica)
       LinkedIn   -> API Posts della pagina aziendale (serve un'app LinkedIn con «Community Management API»)
     Se un canale non è collegato, il post resta «da pubblicare a mano»: si scarica l'immagine, si copia il testo
     e si segna come pubblicato.
In test (TESTING) nessuna chiamata esce: le pubblicazioni finiscono in app.config["SOCIAL_PUBBLICATI"].
"""
import io
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from zoneinfo import ZoneInfo

from flask import Response, abort, flash, g, redirect, render_template, request, send_file, url_for
from PIL import Image, ImageOps

import grafica_social
from app import (SocialMedia, SocialPost, Utente, admin_richiesto, app, db, impostazioni)
from newsletter import Postino, app_url, conf_smtp, smtp_pronto
from social_piano import IDEE, LINEA_BASE, TEMI

ROMA = ZoneInfo("Europe/Rome")
MAX_BOZZE = 2
CANALI = {"instagram": "Instagram", "linkedin": "LinkedIn"}
STATI_POST = {"bozza": "Da approvare", "approvato": "Programmato", "in_pubblicazione": "In pubblicazione",
              "pubblicato": "Pubblicato", "errore": "Errore", "scartato": "Scartato"}
FOTO_BASE = ["foto-reception.jpg", "foto-camice-member.jpg", "foto-porta-member.jpg", "foto-biglietto.jpg",
             "foto-montagne.jpg"]
SCENE_NOMI = {"titolo": "Frase grande (blu)", "foto": "Foto + frase", "lista": "Elenco numerato",
              "domanda": "Domanda (chiaro)", "cta": "Invito con pulsante", "immagine": "Solo foto"}
META_VERSIONE = os.environ.get("META_VERSION", "v24.0")
GRAPH_IG = f"https://graph.instagram.com/{META_VERSIONE}"
GRAPH_FB = f"https://graph.facebook.com/{META_VERSIONE}"
LINKEDIN = "https://api.linkedin.com/rest"
_lock = threading.Lock()


# ------------------------------------------------------------------ utilità
def li_versione():
    return os.environ.get("LINKEDIN_VERSION", "202510")


def ig_pronto(imp=None):
    imp = imp or impostazioni()
    return bool(imp.soc_ig_token and imp.soc_ig_user)


def li_pronto(imp=None):
    imp = imp or impostazioni()
    return bool(imp.soc_li_token and imp.soc_li_org)


def canali_di(p):
    return [c for c in (p.canali or "").split(",") if c in CANALI]


def esiti_di(p):
    try:
        return json.loads(p.esiti or "{}")
    except ValueError:
        return {}


def ora_pubblicazione(imp=None):
    imp = imp or impostazioni()
    try:
        h, m = (imp.soc_ora or "09:30").split(":")
        return int(h), int(m)
    except ValueError:
        return 9, 30


def a_utc(locale):
    return locale.replace(tzinfo=ROMA).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def prossima_data(dopo_utc=None, giorni=3):
    """Primo giorno feriale almeno `giorni` dopo, all'ora di pubblicazione (restituito in UTC)."""
    h, m = ora_pubblicazione()
    base = (dopo_utc or datetime.utcnow()).replace(tzinfo=ZoneInfo("UTC")).astimezone(ROMA)
    giorno = (base + timedelta(days=giorni)).replace(hour=h, minute=m, second=0, microsecond=0, tzinfo=None)
    while giorno.weekday() >= 5:
        giorno += timedelta(days=1)
    return a_utc(giorno)


def idee_tutte():
    imp = impostazioni()
    try:
        mie = json.loads(imp.soc_idee or "[]")
    except ValueError:
        mie = []
    return IDEE + [dict(i, propria=True) for i in mie]


def idea_per_id(iid):
    return next((i for i in idee_tutte() if i["id"] == iid), None)


def scegli_idea():
    """Idea non ancora usata (si ricomincia quando sono finite), con un tema diverso dall'ultimo post."""
    tutte = idee_tutte()
    if not tutte:
        return None
    usate = [r[0] for r in db.session.query(SocialPost.idea).filter(SocialPost.idea.isnot(None),
                                                                    SocialPost.stato != "scartato")
             .order_by(SocialPost.id).all()]
    libere = [i for i in tutte if i["id"] not in set(usate)]
    if not libere:  # finito il giro: riparte dalle meno recenti
        ordine = {iid: n for n, iid in enumerate(usate)}
        libere = sorted(tutte, key=lambda i: ordine.get(i["id"], -1))[:max(1, len(tutte) // 2)]
    ultimo = SocialPost.query.filter(SocialPost.stato != "scartato").order_by(SocialPost.id.desc()).first()
    diverse = [i for i in libere if not ultimo or i.get("tema") != ultimo.tema]
    return (diverse or libere)[0]


def nuovo_media(dati, nome="", archivio=False, tipo="image/jpeg"):
    m = SocialMedia(token=secrets.token_urlsafe(24), dati=dati, nome=nome[:200], archivio=archivio, tipo=tipo)
    db.session.add(m)
    db.session.flush()
    return m


def foto_bytes(p):
    if (p.foto or "").startswith("m:"):
        try:
            m = db.session.get(SocialMedia, int(p.foto[2:]))
        except ValueError:
            m = None
        return m.dati if m else None
    return None


def disegna(p):
    """Rigenera la grafica del post e la salva (sostituisce la precedente)."""
    nome_foto = p.foto[5:] if (p.foto or "").startswith("base:") else None
    punti = [r.strip() for r in (p.punti or "").splitlines() if r.strip()]
    jpg = grafica_social.genera(p.scena or "titolo", titolo=p.titolo or "", testo=p.testo or "", punti=punti,
                                tema=p.tema or "", foto=nome_foto, foto_bytes=foto_bytes(p))
    vecchio = db.session.get(SocialMedia, p.media_id) if p.media_id else None
    if vecchio and not vecchio.archivio:
        vecchio.dati, vecchio.token = jpg, secrets.token_urlsafe(24)
    else:
        p.media_id = nuovo_media(jpg, f"post-{p.id or 'nuovo'}.jpg").id
    return jpg


def link_media(p):
    m = db.session.get(SocialMedia, p.media_id) if p.media_id else None
    return f"{app_url()}{url_for('social_media', token=m.token)}" if m else None


def post_da_idea(idea, data=None, utente_id=None):
    foto = idea.get("foto")
    p = SocialPost(stato="bozza", idea=idea["id"], tema=idea.get("tema"), scena=idea.get("scena", "titolo"),
                   titolo=idea.get("titolo"), testo=idea.get("testo"), punti="\n".join(idea.get("punti") or []),
                   foto=("base:" + foto) if foto and not foto.startswith(("base:", "m:")) else foto,
                   didascalia=idea.get("didascalia"), canali=",".join(CANALI), creato_da=utente_id,
                   data_prevista=data or prossima_data(giorni=2))
    db.session.add(p)
    db.session.flush()
    disegna(p)
    return p


# ------------------------------------------------------------------ chiamate HTTP (solo urllib, niente librerie in più)
class ErroreSocial(Exception):
    pass


def http(metodo, url, dati=None, json_body=None, headers=None, grezzo=False):
    headers = dict(headers or {})
    corpo = None
    if json_body is not None:
        corpo = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif isinstance(dati, (bytes, bytearray)):
        corpo = bytes(dati)
    elif dati is not None:
        corpo = urllib.parse.urlencode(dati).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=corpo, method=metodo, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            testo = r.read()
            return r.status, dict(r.headers), (testo if grezzo else _json(testo))
    except urllib.error.HTTPError as e:
        testo = e.read()
        dettaglio = _json(testo)
        msg = dettaglio.get("error", {}).get("message") if isinstance(dettaglio.get("error"), dict) else None
        msg = msg or dettaglio.get("message") or testo[:300].decode(errors="replace")
        raise ErroreSocial(f"{e.code}: {msg}")
    except urllib.error.URLError as e:
        raise ErroreSocial(f"connessione non riuscita: {e.reason}")


def _json(b):
    try:
        return json.loads(b or b"{}")
    except ValueError:
        return {}


# ------------------------------------------------------------------ Instagram
def ig_base(imp):
    return GRAPH_FB if imp.soc_ig_modo == "facebook" else GRAPH_IG


def verifica_instagram(token, user_id=""):
    """Riconosce il tipo di token. Restituisce (modo, user_id, username, token_da_salvare).
    Se non riesce, l'errore riporta le risposte di Meta per capire cosa non va."""
    token = token.strip()
    user_id = re.sub(r"\D", "", user_id or "")
    errori = []
    if not token.startswith("EA"):  # token «Instagram Login» (di solito inizia con IG)
        try:
            _, _, d = http("GET", f"{GRAPH_IG}/me?" + urllib.parse.urlencode(
                {"fields": "user_id,username", "access_token": token}))
            if d.get("username"):
                return "instagram", str(d.get("user_id") or d.get("id")), d["username"], token
        except ErroreSocial as e:
            errori.append(f"instagram.com: {e}")
    if user_id:  # token di Meta (utente di sistema, «accesso unificato» o Facebook): basta l'ID account Instagram
        try:
            _, _, d = http("GET", f"{GRAPH_FB}/{user_id}?" + urllib.parse.urlencode(
                {"fields": "id,username", "access_token": token}))
            if d.get("username") or d.get("id"):
                return "facebook", user_id, d.get("username") or user_id, token
        except ErroreSocial as e:
            errori.append(f"account {user_id}: {e}")
    try:  # token Facebook di un utente: cerca la Pagina collegata all'account Instagram professionale
        _, _, d = http("GET", f"{GRAPH_FB}/me/accounts?" + urllib.parse.urlencode(
            {"fields": "name,access_token,instagram_business_account{id,username}", "access_token": token}))
        for pagina in d.get("data", []):
            ig = pagina.get("instagram_business_account")
            if ig and (not user_id or ig.get("id") == user_id):
                return "facebook", ig["id"], ig.get("username") or pagina.get("name"), pagina.get("access_token") or token
    except ErroreSocial as e:
        errori.append(f"pagine: {e}")
    if token.startswith("EA") and not errori:
        errori.append("token di Meta senza Pagina collegata: scrivi anche l'ID account Instagram")
    raise ErroreSocial("nessun account Instagram trovato. Risposte di Meta → " + " | ".join(errori or ["nessuna"]))


def pubblica_instagram(p, imp):
    url_img = link_media(p)
    base, tok, uid = ig_base(imp), imp.soc_ig_token, imp.soc_ig_user
    _, _, d = http("POST", f"{base}/{uid}/media", dati={"image_url": url_img, "caption": (p.didascalia or "")[:2200],
                                                        "access_token": tok})
    contenitore = d.get("id")
    if not contenitore:
        raise ErroreSocial(f"Instagram non ha preparato il post: {d}")
    for _ in range(10):  # le immagini di solito sono pronte subito
        _, _, s = http("GET", f"{base}/{contenitore}?" + urllib.parse.urlencode(
            {"fields": "status_code", "access_token": tok}))
        if s.get("status_code") in (None, "FINISHED"):
            break
        if s.get("status_code") == "ERROR":
            raise ErroreSocial("Instagram non è riuscito a leggere l'immagine")
        time.sleep(3)
    _, _, d = http("POST", f"{base}/{uid}/media_publish", dati={"creation_id": contenitore, "access_token": tok})
    mid = d.get("id")
    link = None
    try:
        _, _, info = http("GET", f"{base}/{mid}?" + urllib.parse.urlencode({"fields": "permalink", "access_token": tok}))
        link = info.get("permalink")
    except ErroreSocial:
        pass
    return {"id": mid, "link": link}


# ------------------------------------------------------------------ LinkedIn
def li_headers(imp):
    return {"Authorization": f"Bearer {imp.soc_li_token}", "LinkedIn-Version": li_versione(),
            "X-Restli-Protocol-Version": "2.0.0"}


RISERVATI_LI = re.compile(r"([\\|{}@\[\]()<>*_~])")


def testo_linkedin(testo):
    """Il testo dei post LinkedIn ha caratteri riservati: vanno «protetti», gli hashtag diventano veri hashtag."""
    pezzi = re.split(r"(#\w+)", testo or "")
    out = []
    for pz in pezzi:
        if re.fullmatch(r"#\w+", pz):
            out.append("{hashtag|\\#|" + pz[1:] + "}")
        else:
            out.append(RISERVATI_LI.sub(r"\\\1", pz).replace("#", "\\#"))
    return "".join(out)[:3000]


def verifica_linkedin(token, org=""):
    imp = impostazioni()
    h = {"Authorization": f"Bearer {token.strip()}", "LinkedIn-Version": li_versione(),
         "X-Restli-Protocol-Version": "2.0.0"}
    org = re.sub(r"\D", "", org or "")
    if not org:
        _, _, d = http("GET", f"{LINKEDIN}/organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED", headers=h)
        elenco = [e.get("organization", "") for e in d.get("elements", [])]
        if not elenco:
            raise ErroreSocial("il token non risulta amministratore di nessuna pagina aziendale")
        org = elenco[0].rsplit(":", 1)[-1]
    _, _, d = http("GET", f"{LINKEDIN}/organizations/{org}", headers=h)
    nome = d.get("localizedName") or (d.get("name") or {}).get("localized", {}).get("it_IT") or f"Pagina {org}"
    del imp
    return org, nome


def pubblica_linkedin(p, imp):
    m = db.session.get(SocialMedia, p.media_id)
    autore = f"urn:li:organization:{imp.soc_li_org}"
    h = li_headers(imp)
    _, _, d = http("POST", f"{LINKEDIN}/images?action=initializeUpload",
                   json_body={"initializeUploadRequest": {"owner": autore}}, headers=h)
    valore = d.get("value", {})
    if not valore.get("uploadUrl"):
        raise ErroreSocial(f"LinkedIn non ha dato l'indirizzo di caricamento: {d}")
    http("PUT", valore["uploadUrl"], dati=m.dati, headers={"Authorization": h["Authorization"],
                                                           "Content-Type": "image/jpeg"}, grezzo=True)
    corpo = {"author": autore, "commentary": testo_linkedin(p.didascalia), "visibility": "PUBLIC",
             "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                              "thirdPartyDistributionChannels": []},
             "content": {"media": {"id": valore["image"], "altText": re.sub(r"\*", "", p.titolo or "Dentalia")[:400]}},
             "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
    _, intest, _ = http("POST", f"{LINKEDIN}/posts", json_body=corpo, headers=h, grezzo=True)
    urn = {k.lower(): v for k, v in intest.items()}.get("x-restli-id")
    return {"id": urn, "link": f"https://www.linkedin.com/feed/update/{urn}/" if urn else None}


# ------------------------------------------------------------------ pubblicazione
def pubblica(p):
    """Pubblica il post sui canali scelti e collegati (salta quelli già riusciti). Restituisce gli esiti."""
    imp = impostazioni()
    esiti = esiti_di(p)
    if not p.media_id:
        disegna(p)
        db.session.commit()
    for canale in canali_di(p):
        if esiti.get(canale, {}).get("ok"):
            continue
        pronto = ig_pronto(imp) if canale == "instagram" else li_pronto(imp)
        if not pronto:
            esiti[canale] = {"ok": False, "manuale": True, "errore": "canale non collegato: pubblicalo a mano"}
            continue
        try:
            if app.config.get("TESTING"):
                app.config.setdefault("SOCIAL_PUBBLICATI", []).append((canale, p.id))
                r = {"id": f"finto-{canale}-{p.id}", "link": None}
            elif canale == "instagram":
                r = pubblica_instagram(p, imp)
            else:
                r = pubblica_linkedin(p, imp)
            esiti[canale] = {"ok": True, "id": r.get("id"), "link": r.get("link"),
                             "il": datetime.utcnow().strftime("%Y-%m-%d %H:%M")}
        except Exception as err:  # noqa: BLE001  l'errore resta scritto sul post
            esiti[canale] = {"ok": False, "errore": str(err)[:400]}
    p.esiti = json.dumps(esiti)
    riusciti = [c for c in canali_di(p) if esiti.get(c, {}).get("ok")]
    errori = [f"{CANALI[c]}: {esiti[c].get('errore')}" for c in canali_di(p)
              if not esiti.get(c, {}).get("ok") and not esiti.get(c, {}).get("manuale")]
    if errori:
        p.stato, p.errore = "errore", " · ".join(errori)[:500]
    else:
        p.stato, p.errore = "pubblicato", None
        p.pubblicato_il = datetime.utcnow() if riusciti else p.pubblicato_il
        if not riusciti:  # nessun canale collegato: resta da fare a mano
            p.stato = "approvato"
            p.errore = "Nessun canale collegato: scarica l'immagine, copia il testo e segnalo come pubblicato."
    db.session.commit()
    return esiti


def giro_pubblicazione():
    """Pubblica i post approvati la cui data è arrivata. Il passaggio a «in_pubblicazione» è atomico:
    anche con più processi un post non parte due volte."""
    if not _lock.acquire(blocking=False):
        return 0
    fatti = 0
    try:
        adesso = datetime.utcnow()
        imp = impostazioni()
        collegati = [c for c in CANALI if (ig_pronto(imp) if c == "instagram" else li_pronto(imp))]
        if not collegati:
            return 0
        pronti = SocialPost.query.filter(SocialPost.stato == "approvato", SocialPost.data_prevista <= adesso) \
            .order_by(SocialPost.data_prevista).limit(20).all()
        for p in pronti:
            if not set(canali_di(p)) & set(collegati):
                continue  # i suoi canali non sono collegati: resta da pubblicare a mano
            preso = SocialPost.query.filter_by(id=p.id, stato="approvato").update({"stato": "in_pubblicazione"})
            db.session.commit()
            if not preso:
                continue
            db.session.refresh(p)
            pubblica(p)
            fatti += 1
        return fatti
    finally:
        _lock.release()


# ------------------------------------------------------------------ agente
def bozze_in_attesa():
    return SocialPost.query.filter_by(stato="bozza").count()


def agente_dovuto(imp=None, adesso=None):
    imp = imp or impostazioni()
    adesso = adesso or datetime.utcnow()
    if not imp.soc_agente:
        return False
    ogni = imp.soc_ogni or 3
    return not imp.soc_ultimo or adesso - imp.soc_ultimo >= timedelta(days=ogni) - timedelta(minutes=30)


def crea_bozza_agente(forza=False):
    """Prepara una bozza dal piano editoriale. Restituisce il post o None (se non è il momento o ci sono già 2 bozze)."""
    imp = impostazioni()
    if not forza and not agente_dovuto(imp):
        return None
    if bozze_in_attesa() >= MAX_BOZZE:
        return None
    idea = scegli_idea()
    if not idea:
        return None
    ogni = imp.soc_ogni or 3
    ultimo_prog = (db.session.query(db.func.max(SocialPost.data_prevista))
                   .filter(SocialPost.stato.in_(("bozza", "approvato"))).scalar())
    data = prossima_data(giorni=2)
    if ultimo_prog and ultimo_prog > datetime.utcnow():
        data = max(data, prossima_data(ultimo_prog, giorni=ogni))
    p = post_da_idea(idea, data=data)
    imp.soc_ultimo = datetime.utcnow()
    db.session.commit()
    if imp.soc_avviso is not False:
        avvisa_bozza(p)
    return p


def avvisa_bozza(p):
    if not smtp_pronto():
        return
    destinatari = [u.email for u in Utente.query.filter_by(ruolo="admin").all() if u.email and u.attivo is not False]
    if not destinatari:
        return
    try:
        with app.test_request_context(base_url=app_url()):
            link = f"{app_url()}{url_for('social_post', pid=p.id)}"
        quando = p.data_prevista.replace(tzinfo=ZoneInfo("UTC")).astimezone(ROMA).strftime("%d/%m alle %H:%M")
        c = conf_smtp()
        with Postino() as postino:
            for dest in destinatari:
                m = EmailMessage()
                m["Subject"] = f"Social Dentalia: nuova bozza da approvare ({p.tema or 'post'})"
                m["From"] = formataddr((c["nome"], c["utente"] or "info@dentaliagroup.it"))
                m["To"] = dest
                titolo = re.sub(r"\*", "", p.titolo or "")
                m.set_content(f"Ho preparato un nuovo post per Instagram e LinkedIn.\n\n«{titolo}»\n\n"
                              f"Uscirà il {quando} se lo approvi.\nGuardalo, correggilo e approvalo qui: {link}\n\n"
                              "— l'agente social dell'app Dentalia")
                postino.manda(m)
    except Exception as err:  # noqa: BLE001
        print(f"SOCIAL: avviso bozza non inviato: {err}", flush=True)


def _ciclo():
    time.sleep(90)
    while True:
        try:
            with app.app_context():
                crea_bozza_agente()
                giro_pubblicazione()
        except Exception as err:  # noqa: BLE001
            print(f"SOCIAL: errore nel ciclo: {err}", flush=True)
            try:
                with app.app_context():
                    db.session.rollback()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(10 * 60)


if not app.config.get("TESTING") and os.environ.get("SOCIAL_AUTO", "1") != "0" and "unittest" not in sys.modules:
    threading.Thread(target=_ciclo, daemon=True, name="social").start()


# ------------------------------------------------------------------ filtri per i template
@app.template_filter("senza_asterischi")
def senza_asterischi(t):
    return re.sub(r"\*", "", t or "")


def nascondi(token):
    return f"…{token[-6:]}" if token else ""


def _riepilogo():
    imp = impostazioni()
    conta = dict(db.session.query(SocialPost.stato, db.func.count()).group_by(SocialPost.stato).all())
    li_scade = None
    if imp.soc_li_scade:
        li_scade = (imp.soc_li_scade - datetime.utcnow()).days
    return {"imp": imp, "ig": ig_pronto(imp), "li": li_pronto(imp), "conta": conta, "li_scade": li_scade,
            "stati": STATI_POST, "canali_nomi": CANALI}


# ------------------------------------------------------------------ pagine
@app.get("/m/<token>.jpg")
def social_media(token):
    """Immagine pubblica (serve a Instagram per scaricarla). Il token è casuale e lungo."""
    m = SocialMedia.query.filter_by(token=token).first() or abort(404)
    r = Response(m.dati, mimetype=m.tipo or "image/jpeg")
    r.headers["Cache-Control"] = "public, max-age=86400"
    r.headers["X-Robots-Tag"] = "noindex"
    return r


@app.get("/gestione")
@admin_richiesto
def gestione():
    vista = request.args.get("vista", "attesa")
    q = SocialPost.query
    if vista == "attesa":
        q = q.filter(SocialPost.stato.in_(("bozza", "errore"))).order_by(SocialPost.data_prevista)
    elif vista == "programmati":
        q = q.filter(SocialPost.stato.in_(("approvato", "in_pubblicazione"))).order_by(SocialPost.data_prevista)
    elif vista == "pubblicati":
        q = q.filter_by(stato="pubblicato").order_by(SocialPost.pubblicato_il.desc())
    else:
        vista = "scartati"
        q = q.filter_by(stato="scartato").order_by(SocialPost.id.desc())
    posts = q.limit(60).all()
    media = {m.id: m for m in SocialMedia.query.filter(SocialMedia.id.in_([p.media_id for p in posts if p.media_id]))
             .with_entities(SocialMedia.id, SocialMedia.token).all()} if posts else {}
    return render_template("gestione.html", posts=posts, vista=vista, media=media, esiti_di=esiti_di,
                           canali_di=canali_di, bozze=bozze_in_attesa(), max_bozze=MAX_BOZZE, **_riepilogo())


@app.route("/gestione/post/nuovo", methods=["GET", "POST"])
@app.route("/gestione/post/<int:pid>", methods=["GET", "POST"])
@admin_richiesto
def social_post(pid=None):
    p = db.session.get(SocialPost, pid) if pid else None
    if pid and not p:
        abort(404)
    if request.method == "POST":
        nuovo = p is None
        if nuovo:
            p = SocialPost(stato="bozza", creato_da=g.utente.id)
            db.session.add(p)
        if p.stato in ("pubblicato", "in_pubblicazione"):
            flash("Questo post è già pubblicato: non si può modificare.")
            return redirect(url_for("social_post", pid=p.id))
        f = request.form
        p.scena = f.get("scena") if f.get("scena") in grafica_social.SCENE else "titolo"
        p.tema = f.get("tema", "").strip()[:80] or None
        p.titolo = f.get("titolo", "").strip()[:300]
        p.testo = f.get("testo", "").strip() or None
        p.punti = f.get("punti", "").strip() or None
        p.foto = f.get("foto") or None
        p.didascalia = f.get("didascalia", "").strip()
        p.canali = ",".join(c for c in CANALI if f.get(f"canale_{c}")) or ""
        try:
            locale = datetime.strptime(f.get("data_prevista", ""), "%Y-%m-%dT%H:%M")
            p.data_prevista = a_utc(locale)
        except ValueError:
            p.data_prevista = p.data_prevista or prossima_data(giorni=1)
        azione = f.get("azione", "salva")
        if not p.titolo and p.scena != "immagine":
            db.session.rollback()
            flash("Scrivi almeno il titolo della grafica.")
            return redirect(request.url)
        if azione in ("approva", "pubblica") and not p.didascalia:
            db.session.rollback()
            flash("Manca la didascalia (il testo del post).")
            return redirect(request.url)
        db.session.flush()
        disegna(p)
        p.errore = None
        if azione == "approva":
            p.stato, p.approvato_il = "approvato", datetime.utcnow()
            if p.data_prevista < datetime.utcnow():
                p.data_prevista = datetime.utcnow()
            db.session.commit()
            quando = p.data_prevista.replace(tzinfo=ZoneInfo("UTC")).astimezone(ROMA).strftime("%d/%m alle %H:%M")
            r = _riepilogo()
            if r["ig"] or r["li"]:
                flash(f"Approvato: verrà pubblicato da solo il {quando}.")
            else:
                flash(f"Approvato per il {quando}. Nessun social è ancora collegato: quel giorno pubblicalo a mano "
                      "(scarica immagine + copia testo) oppure collega i canali.")
            return redirect(url_for("gestione", vista="programmati"))
        if azione == "pubblica":
            p.stato, p.approvato_il = "in_pubblicazione", datetime.utcnow()
            db.session.commit()
            esiti = pubblica(p)
            if p.stato == "pubblicato":
                flash("Pubblicato! " + " · ".join(CANALI[c] for c, e in esiti.items() if e.get("ok")))
            else:
                flash(p.errore or "Pubblicazione non riuscita.")
            return redirect(url_for("social_post", pid=p.id))
        if p.stato in ("errore", "scartato"):
            p.stato = "bozza"
        db.session.commit()
        flash("Bozza salvata." if nuovo or p.stato == "bozza" else "Modifiche salvate.")
        return redirect(url_for("social_post", pid=p.id))

    if p is None:  # nuovo post vuoto
        p = SocialPost(stato="bozza", scena="titolo", canali=",".join(CANALI), data_prevista=prossima_data(giorni=1))
    media = db.session.get(SocialMedia, p.media_id) if p.media_id else None
    foto_archivio = SocialMedia.query.filter_by(archivio=True).order_by(SocialMedia.id.desc()) \
        .with_entities(SocialMedia.id, SocialMedia.token, SocialMedia.nome).all()
    data_locale = p.data_prevista.replace(tzinfo=ZoneInfo("UTC")).astimezone(ROMA).strftime("%Y-%m-%dT%H:%M") \
        if p.data_prevista else ""
    return render_template("gestione_post.html", p=p, media=media, foto_base=FOTO_BASE, foto_archivio=foto_archivio,
                           scene=SCENE_NOMI, temi=TEMI + ["Domanda della settimana"], data_locale=data_locale,
                           esiti=esiti_di(p), canali_di=canali_di, link_immagine=link_media(p) if media else None,
                           **_riepilogo())


@app.post("/gestione/post/<int:pid>/stato")
@admin_richiesto
def social_post_stato(pid):
    p = db.session.get(SocialPost, pid) or abort(404)
    azione = request.form.get("azione")
    if azione == "scarta" and p.stato != "pubblicato":
        p.stato = "scartato"
        flash("Post scartato: l'agente non riproporrà questa idea finché non ha usato le altre.")
    elif azione == "bozza" and p.stato in ("approvato", "errore", "scartato"):
        p.stato, p.errore = "bozza", None
        flash("Riportato tra le bozze da approvare.")
    elif azione == "manuale" and p.stato != "pubblicato":
        p.stato, p.pubblicato_il, p.errore = "pubblicato", datetime.utcnow(), None
        esiti = esiti_di(p)
        for c in canali_di(p):
            if not esiti.get(c, {}).get("ok"):
                esiti[c] = {"ok": True, "manuale": True, "il": datetime.utcnow().strftime("%Y-%m-%d %H:%M")}
        p.esiti = json.dumps(esiti)
        flash("Segnato come pubblicato a mano.")
    elif azione == "riprova" and p.stato == "errore":
        p.stato, p.errore = "in_pubblicazione", None
        db.session.commit()
        pubblica(p)
        flash("Pubblicato." if p.stato == "pubblicato" else f"Ancora non riuscito: {p.errore}")
        return redirect(url_for("social_post", pid=p.id))
    elif azione == "elimina" and p.stato != "pubblicato":
        if p.media_id:
            m = db.session.get(SocialMedia, p.media_id)
            if m and not m.archivio:
                db.session.delete(m)
        db.session.delete(p)
        db.session.commit()
        flash("Post eliminato.")
        return redirect(url_for("gestione"))
    db.session.commit()
    return redirect(url_for("social_post", pid=p.id))


@app.get("/gestione/post/<int:pid>/immagine")
@admin_richiesto
def social_scarica(pid):
    p = db.session.get(SocialPost, pid) or abort(404)
    m = db.session.get(SocialMedia, p.media_id) if p.media_id else None
    if not m:
        abort(404)
    return send_file(io.BytesIO(m.dati), mimetype="image/jpeg", as_attachment=True,
                     download_name=f"dentalia-post-{p.id}.jpg")


@app.post("/gestione/anteprima")
@admin_richiesto
def social_anteprima():
    """Anteprima al volo mentre si scrive (non salva nulla)."""
    f = request.form
    p = SocialPost(scena=f.get("scena"), tema=f.get("tema"), titolo=f.get("titolo"), testo=f.get("testo"),
                   punti=f.get("punti"), foto=f.get("foto"))
    nome_foto = p.foto[5:] if (p.foto or "").startswith("base:") else None
    jpg = grafica_social.genera(p.scena or "titolo", titolo=p.titolo or "", testo=p.testo or "",
                                punti=[r for r in (p.punti or "").splitlines() if r.strip()], tema=p.tema or "",
                                foto=nome_foto, foto_bytes=foto_bytes(p))
    return Response(jpg, mimetype="image/jpeg")


@app.post("/gestione/agente/ora")
@admin_richiesto
def social_agente_ora():
    if bozze_in_attesa() >= MAX_BOZZE:
        flash(f"Ci sono già {MAX_BOZZE} bozze da approvare: prima approvale o scartale.")
        return redirect(url_for("gestione"))
    iid = request.form.get("idea")
    if iid:
        idea = idea_per_id(iid) or abort(404)
        p = post_da_idea(idea, utente_id=g.utente.id)
        db.session.commit()
    else:
        p = crea_bozza_agente(forza=True)
    if not p:
        flash("Non ci sono idee disponibili: aggiungine qualcuna in «Idee e linea».")
        return redirect(url_for("gestione"))
    flash("Ecco la nuova bozza: controllala e approvala.")
    return redirect(url_for("social_post", pid=p.id))


@app.route("/gestione/foto", methods=["GET", "POST"])
@admin_richiesto
def social_foto():
    if request.method == "POST":
        if request.form.get("elimina"):
            m = db.session.get(SocialMedia, int(request.form["elimina"])) or abort(404)
            if m.archivio:
                usata = SocialPost.query.filter(SocialPost.foto == f"m:{m.id}",
                                                SocialPost.stato.in_(("bozza", "approvato"))).first()
                if usata:
                    flash("Questa foto è usata da un post non ancora pubblicato: cambiala prima nel post.")
                else:
                    db.session.delete(m)
                    db.session.commit()
                    flash("Foto eliminata.")
            return redirect(url_for("social_foto"))
        caricate = 0
        for file in request.files.getlist("foto"):
            if not file or not file.filename:
                continue
            try:
                im = ImageOps.exif_transpose(Image.open(file.stream)).convert("RGB")
            except Exception:  # noqa: BLE001
                flash(f"«{file.filename}» non è un'immagine valida.")
                continue
            im.thumbnail((2000, 2000))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=88, optimize=True)
            nuovo_media(out.getvalue(), file.filename, archivio=True)
            caricate += 1
        db.session.commit()
        flash(f"Foto caricate: {caricate}." if caricate else "Nessuna foto caricata.")
        return redirect(url_for("social_foto"))
    foto = SocialMedia.query.filter_by(archivio=True).order_by(SocialMedia.id.desc()) \
        .with_entities(SocialMedia.id, SocialMedia.token, SocialMedia.nome, SocialMedia.creato_il).all()
    return render_template("gestione_foto.html", foto=foto, foto_base=FOTO_BASE, **_riepilogo())


@app.route("/gestione/idee", methods=["GET", "POST"])
@admin_richiesto
def social_idee():
    imp = impostazioni()
    try:
        mie = json.loads(imp.soc_idee or "[]")
    except ValueError:
        mie = []
    if request.method == "POST":
        f = request.form
        if f.get("azione") == "linea":
            imp.soc_linea = f.get("linea", "").strip() or None
            flash("Linea editoriale salvata.")
        elif f.get("azione") == "aggiungi":
            titolo = f.get("titolo", "").strip()
            if not titolo or not f.get("didascalia", "").strip():
                flash("Per una nuova idea servono titolo e didascalia.")
                return redirect(url_for("social_idee"))
            mie.append({"id": "mia-" + secrets.token_hex(4), "tema": f.get("tema", "").strip() or "Il network",
                        "scena": f.get("scena") if f.get("scena") in grafica_social.SCENE else "titolo",
                        "titolo": titolo[:300], "testo": f.get("testo", "").strip(),
                        "punti": [r.strip() for r in f.get("punti", "").splitlines() if r.strip()],
                        "foto": f.get("foto") or None, "didascalia": f.get("didascalia", "").strip()})
            imp.soc_idee = json.dumps(mie, ensure_ascii=False)
            flash("Idea aggiunta: l'agente la userà nei prossimi giri.")
        elif f.get("azione") == "togli":
            mie = [i for i in mie if i["id"] != f.get("id")]
            imp.soc_idee = json.dumps(mie, ensure_ascii=False)
            flash("Idea tolta.")
        db.session.commit()
        return redirect(url_for("social_idee"))
    usate = dict(db.session.query(SocialPost.idea, db.func.count()).filter(SocialPost.idea.isnot(None))
                 .group_by(SocialPost.idea).all())
    return render_template("gestione_idee.html", idee=idee_tutte(), usate=usate, linea=imp.soc_linea or LINEA_BASE,
                           scene=SCENE_NOMI, temi=TEMI + ["Domanda della settimana"], foto_base=FOTO_BASE,
                           prossima=scegli_idea(), **_riepilogo())


@app.route("/gestione/collegamenti", methods=["GET", "POST"])
@admin_richiesto
def social_collegamenti():
    imp = impostazioni()
    if request.method == "POST":
        f = request.form
        azione = f.get("azione")
        try:
            if azione == "instagram":
                token = f.get("token", "").strip() or imp.soc_ig_token or ""
                if not token:
                    raise ErroreSocial("incolla il token")
                if app.config.get("TESTING"):
                    modo, uid, nome, tok = "instagram", f.get("user_id") or "1789", "dentalia_test", token
                else:
                    modo, uid, nome, tok = verifica_instagram(token, f.get("user_id", "").strip())
                imp.soc_ig_modo, imp.soc_ig_user, imp.soc_ig_nome, imp.soc_ig_token = modo, uid, nome, tok
                flash(f"Instagram collegato: @{nome}.")
            elif azione == "linkedin":
                token = f.get("token", "").strip() or imp.soc_li_token or ""
                if not token:
                    raise ErroreSocial("incolla il token")
                if app.config.get("TESTING"):
                    org, nome = re.sub(r"\D", "", f.get("org", "")) or "123", "Dentalia (test)"
                else:
                    org, nome = verifica_linkedin(token, f.get("org", ""))
                imp.soc_li_org, imp.soc_li_nome, imp.soc_li_token = org, nome, token
                if f.get("token", "").strip():
                    imp.soc_li_scade = datetime.utcnow() + timedelta(days=60)
                flash(f"LinkedIn collegato: {nome}.")
            elif azione == "scollega_instagram":
                imp.soc_ig_token = imp.soc_ig_user = imp.soc_ig_nome = imp.soc_ig_modo = None
                flash("Instagram scollegato.")
            elif azione == "scollega_linkedin":
                imp.soc_li_token = imp.soc_li_org = imp.soc_li_nome = imp.soc_li_scade = None
                flash("LinkedIn scollegato.")
            db.session.commit()
        except ErroreSocial as err:
            db.session.rollback()
            if azione == "instagram" and f.get("user_id", "").strip() and not imp.soc_ig_token:
                imp.soc_ig_user = re.sub(r"\D", "", f.get("user_id"))[:40] or None
                db.session.commit()
            flash(f"Collegamento non riuscito: {err}")
        return redirect(url_for("social_collegamenti"))
    return render_template("gestione_collegamenti.html", nascondi=nascondi, li_versione=li_versione(),
                           **_riepilogo())


@app.route("/gestione/agente", methods=["GET", "POST"])
@admin_richiesto
def social_agente():
    imp = impostazioni()
    if request.method == "POST":
        f = request.form
        imp.soc_agente = f.get("attivo") == "1"
        try:
            imp.soc_ogni = min(30, max(1, int(f.get("ogni", "3"))))
        except ValueError:
            imp.soc_ogni = 3
        ora = f.get("ora", "09:30")
        imp.soc_ora = ora if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", ora) else "09:30"
        imp.soc_avviso = f.get("avviso") == "1"
        db.session.commit()
        flash("Agente acceso: preparerà una bozza ogni %d giorni." % imp.soc_ogni if imp.soc_agente
              else "Agente spento: nessuna bozza automatica.")
        return redirect(url_for("social_agente"))
    prossima = None
    if imp.soc_agente:
        prossima = (imp.soc_ultimo + timedelta(days=imp.soc_ogni or 3)) if imp.soc_ultimo else datetime.utcnow()
    return render_template("gestione_agente.html", prossima=prossima, bozze=bozze_in_attesa(), max_bozze=MAX_BOZZE,
                           smtp_ok=smtp_pronto(), idea=scegli_idea(), **_riepilogo())
