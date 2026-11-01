"""
Cervello dell'agente social: crea da solo il PED (piano editoriale) con l'IA (Claude, API Anthropic).

Da cosa parte:
  - il sito www.dentaliagroup.it (letto e riassunto: «Rileggi il sito» in /gestione/strategia)
  - le istruzioni scritte dall'admin (`Impostazioni.soc_istruzioni`)
  - la fase del percorso (avvio → crescita fan → fiducia → risposta diretta), calcolata dai post usciti
  - i post già fatti (per non ripetersi)
Cosa produce: una lista di post completi (tema, obiettivo, grafica, didascalia) salvata in `Impostazioni.soc_ped`.
L'agente prende da lì il prossimo post, lo disegna e lo mette tra le bozze da approvare.

Serve la variabile ANTHROPIC_API_KEY su Render (modello: ANTHROPIC_MODEL, default claude-sonnet-5-5).
Senza chiave l'agente usa la libreria di riserva di social_piano.py.
In TESTING nessuna chiamata esterna: risposte finte.
"""
import html
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

SITO = os.environ.get("SITO_URL", "https://www.dentaliagroup.it/")
API = "https://api.anthropic.com/v1/messages"

FASI = [
    {"id": "avvio", "nome": "Avvio", "fino_a": 6,
     "scopo": "presentare Dentalia e far crescere i follower della pagina: chi siamo, perché esistiamo, a chi ci "
              "rivolgiamo, il network, i valori. Contenuti leggeri, riconoscibili, da condividere."},
    {"id": "crescita", "nome": "Crescita fan", "fino_a": 18,
     "scopo": "aumentare follower e interazioni: consigli pratici di gestione per titolari di studi dentistici, "
              "domande che fanno commentare, elenchi da salvare, curiosità del settore. Valore senza vendere."},
    {"id": "fiducia", "nome": "Fiducia", "fino_a": 30,
     "scopo": "costruire autorevolezza: il metodo della radiografia in 6 aree, come lavoriamo, dietro le quinte, "
              "errori comuni e come evitarli, numeri e ragionamenti (mai inventati)."},
    {"id": "conversione", "nome": "Risposta diretta", "fino_a": None,
     "scopo": "portare all'azione: post a risposta diretta con invito chiaro al colloquio di valutazione "
              "(scrivere in privato o visitare dentaliagroup.it), alternati a post di valore per non stancare."},
]

REGOLE_META = """Regole per piacere all'algoritmo di Instagram e Facebook (Meta) e al pubblico:
- prima riga della didascalia = gancio forte (domanda, numero, affermazione che incuriosisce): è quella che si vede prima del «altro»
- un solo messaggio per post; frasi brevi, paragrafi di 1-2 righe, emoji con misura
- favorisci contenuti che si SALVANO e si CONDIVIDONO (elenchi pratici, checklist, errori da evitare) e che fanno COMMENTARE (domande aperte)
- chiudi con una call to action coerente con la fase (commenta, salva, condividi, scrivici in privato, visita dentaliagroup.it)
- 3-6 hashtag pertinenti in fondo (sempre #Dentalia), niente muri di hashtag
- linguaggio da collega esperto, concreto; mai promesse esagerate, mai numeri o testimonianze inventate, mai nomi o foto di pazienti, niente linguaggio clinico sulle cure
- varia i formati della grafica e i temi da un post all'altro"""

SCENE_SPIEGATE = """Modelli di grafica disponibili (campo "scena"):
- "titolo": frase grande su sfondo blu, eventuale frase piccola sotto (campo "testo")
- "foto": una foto del brand in alto e la frase sotto (campo "foto" obbligatorio)
- "lista": titolo + 3-4 punti brevi (campo "punti", max 45 caratteri l'uno)
- "domanda": domanda grande su sfondo chiaro, eventuale frase piccola sotto
- "cta": invito finale con pulsante (in "punti" metti 1 sola voce: la scritta del pulsante, max 25 caratteri)
Il "titolo" è la frase della grafica: max 90 caratteri, metti tra *asterischi* 1-3 parole chiave da colorare in oro.
Foto disponibili: foto-reception.jpg (reception con logo Dentalia), foto-camice-member.jpg (professionista in camice),
foto-porta-member.jpg (porta con targa Dentalia member), foto-biglietto.jpg (biglietto da visita), foto-montagne.jpg (paesaggio sardo)."""


def chiave():
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def modello():
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")


def disponibile(app=None):
    return bool(chiave()) or bool(app and app.config.get("TESTING"))


class ErroreIA(Exception):
    pass


def chiama_claude(sistema, messaggio, max_tokens=8000, app=None):
    if app is not None and app.config.get("TESTING"):
        return app.config.get("IA_RISPOSTA_FINTA", "[]")
    if not chiave():
        raise ErroreIA("manca la chiave ANTHROPIC_API_KEY su Render")
    corpo = json.dumps({"model": modello(), "max_tokens": max_tokens, "system": sistema,
                        "messages": [{"role": "user", "content": messaggio}]}).encode()
    req = urllib.request.Request(API, data=corpo, method="POST", headers={
        "x-api-key": chiave(), "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        dettaglio = e.read()[:400].decode(errors="replace")
        raise ErroreIA(f"{e.code}: {dettaglio}")
    except urllib.error.URLError as e:
        raise ErroreIA(f"connessione non riuscita: {e.reason}")
    return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")


def estrai_json(testo):
    """Prende il primo array/oggetto JSON dalla risposta (anche se l'IA aggiunge testo intorno)."""
    testo = re.sub(r"^```(?:json)?|```$", "", (testo or "").strip(), flags=re.M).strip()
    for apre, chiude in (("[", "]"), ("{", "}")):
        i, j = testo.find(apre), testo.rfind(chiude)
        if i != -1 and j > i:
            try:
                return json.loads(testo[i:j + 1])
            except ValueError:
                continue
    raise ErroreIA("risposta dell'IA non leggibile")


# ------------------------------------------------------------------ lettura del sito
class _Testo(HTMLParser):
    SALTA = {"script", "style", "noscript", "svg", "nav", "footer", "form"}

    def __init__(self):
        super().__init__()
        self.parti, self.link, self._salta = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SALTA:
            self._salta += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.link.append(href)
        if tag in ("p", "h1", "h2", "h3", "li", "br", "div", "section"):
            self.parti.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SALTA and self._salta:
            self._salta -= 1

    def handle_data(self, data):
        if not self._salta:
            self.parti.append(data)


def _scarica(url):
    req = urllib.request.Request(url, headers={"User-Agent": "DentaliaAgente/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        if "html" not in (r.headers.get("Content-Type") or ""):
            return ""
        return r.read(800_000).decode("utf-8", errors="replace")


def leggi_sito(max_pagine=15, app=None):
    """Testo delle pagine principali del sito (stesso dominio), ripulito. Restituisce il testo unito."""
    if app is not None and app.config.get("TESTING"):
        return "Dentalia: network di studi dentistici indipendenti. Radiografia dello studio in 6 aree."
    base = urllib.parse.urlparse(SITO)
    da_fare, visti, pezzi = [SITO], set(), []
    while da_fare and len(visti) < max_pagine:
        url = da_fare.pop(0).split("#")[0]
        if url in visti:
            continue
        visti.add(url)
        try:
            pagina = _scarica(url)
        except Exception:  # noqa: BLE001
            continue
        p = _Testo()
        p.feed(pagina)
        testo = html.unescape(re.sub(r"[ \t\r\f\v]+", " ", "".join(p.parti)))
        testo = re.sub(r"\n\s*\n+", "\n", testo).strip()
        if testo:
            pezzi.append(f"### {urllib.parse.urlparse(url).path or '/'}\n{testo[:3500]}")
        for href in p.link:
            assoluto = urllib.parse.urljoin(url, href)
            u = urllib.parse.urlparse(assoluto)
            if u.netloc == base.netloc and not re.search(r"\.(jpe?g|png|webp|gif|pdf|zip|svg|css|js|php)$", u.path, re.I) \
                    and "accesso" not in u.path and assoluto.split("#")[0] not in visti:
                da_fare.append(assoluto.split("#")[0])
    return "\n\n".join(pezzi)[:40000]


# ------------------------------------------------------------------ fasi e PED
def fase_per(numero_usciti):
    for f in FASI:
        if f["fino_a"] is None or numero_usciti < f["fino_a"]:
            return f
    return FASI[-1]


def genera_ped(istruzioni, sito, numero_usciti, titoli_fatti, quanti=6, app=None):
    """Chiede all'IA i prossimi `quanti` post completi. Restituisce una lista di dict pronti per l'agente."""
    fase = fase_per(numero_usciti)
    successive = [f for f in FASI if FASI.index(f) > FASI.index(fase)]
    sistema = ("Sei il social media manager di Dentalia (network di studi dentistici indipendenti, Consulting "
               "Sardegna Srl). Crei il piano editoriale (PED) per Instagram e la Pagina Facebook e scrivi i post. "
               "Rispondi SOLO con JSON valido, in italiano.")
    messaggio = f"""ISTRUZIONI DEL TITOLARE (hanno la precedenza su tutto):
{istruzioni or '(nessuna istruzione aggiuntiva)'}

CONTENUTI DEL SITO www.dentaliagroup.it (usa SOLO queste informazioni come fatti su Dentalia):
{sito or '(sito non ancora letto)'}

PERCORSO DEL PED: si parte dall'avvio dell'attività per far crescere la pagina e si arriva ai post a risposta diretta.
Fasi: {" → ".join(f["nome"] for f in FASI)}.
Post già pubblicati o programmati finora: {numero_usciti}. Fase attuale: «{fase['nome']}» — {fase['scopo']}
{('Se in questo blocco raggiungi la fine della fase, passa gradualmente alla successiva: «' + successive[0]['nome'] + '» — ' + successive[0]['scopo']) if successive else ''}

TITOLI GIÀ USATI (non ripeterli, non fare post simili):
{chr(10).join('- ' + t for t in titoli_fatti[-40:]) or '(nessuno)'}

{REGOLE_META}

{SCENE_SPIEGATE}

Crea i prossimi {quanti} post del PED, in ordine di uscita (uno ogni pochi giorni). Restituisci un array JSON di {quanti} oggetti con questi campi:
"fase" (uno tra: {", ".join(f["id"] for f in FASI)}), "tema" (2-3 parole, compare piccolo in alto nella grafica),
"obiettivo" (breve: es. far conoscere, follower, salvataggi, commenti, contatti), "scena", "titolo", "testo" (facoltativo),
"punti" (array, per lista/cta), "foto" (solo per la scena foto), "didascalia" (testo completo del post, 400-1200 caratteri, con hashtag finali)."""
    risposta = chiama_claude(sistema, messaggio, app=app)
    dati = estrai_json(risposta)
    if isinstance(dati, dict):
        dati = dati.get("post") or dati.get("ped") or [dati]
    post = []
    for d in dati:
        if not isinstance(d, dict) or not d.get("didascalia") or not (d.get("titolo") or d.get("scena") == "immagine"):
            continue
        scena = d.get("scena") if d.get("scena") in ("titolo", "foto", "lista", "domanda", "cta") else "titolo"
        foto = d.get("foto") if scena == "foto" else None
        if scena == "foto" and foto not in ("foto-reception.jpg", "foto-camice-member.jpg", "foto-porta-member.jpg",
                                            "foto-biglietto.jpg", "foto-montagne.jpg"):
            foto = "foto-reception.jpg"
        post.append({
            "id": "ia-" + secrets.token_hex(5),
            "fase": d.get("fase") if d.get("fase") in [f["id"] for f in FASI] else fase["id"],
            "tema": str(d.get("tema") or "")[:60], "obiettivo": str(d.get("obiettivo") or "")[:80],
            "scena": scena, "titolo": str(d.get("titolo") or "")[:200], "testo": str(d.get("testo") or "")[:200],
            "punti": [str(x)[:60] for x in (d.get("punti") or [])][:4], "foto": foto,
            "didascalia": str(d["didascalia"])[:2150], "creato": datetime.utcnow().strftime("%Y-%m-%d"),
        })
    if not post:
        raise ErroreIA("l'IA non ha proposto post validi")
    return post
