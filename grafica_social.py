"""
Grafiche dei post social in stile Dentalia (1080x1350, formato verticale di Instagram e LinkedIn).
Usa solo Pillow e i file in static/ (font Inter, logo, foto del brand): nessun servizio esterno.

Modelli (`scena`):
  titolo  – sfondo blu notte, frase grande; le parole tra *asterischi* diventano oro
  foto    – foto del brand in alto, frase sotto
  lista   – titolo + 3-4 punti numerati
  domanda – sfondo chiaro, domanda grande al centro
  cta     – invito finale (colloquio di valutazione) con pulsante oro
  immagine – solo la foto a tutta pagina, con il logo in basso
"""
import io
import os
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
FONT = os.path.join(BASE, "fonts")
W, H = 1080, 1350
NAVY = (6, 32, 57)
NAVY2 = (15, 51, 87)
ORO = (204, 161, 101)
ORO_CHIARO = (248, 242, 232)
BIANCO = (255, 255, 255)
GRIGIO = (190, 200, 212)
SCENE = ("titolo", "foto", "lista", "domanda", "cta", "immagine")
MARGINE = 96


def font(nome, size):
    file = {"titolo": "InterDisplay-Bold.otf", "semi": "Inter-SemiBold.otf",
            "medio": "Inter-Medium.otf", "testo": "Inter-Regular.otf"}[nome]
    try:
        return ImageFont.truetype(os.path.join(FONT, file), size)
    except OSError:
        return ImageFont.load_default(size)


def _parole(testo):
    """'Il *denaro* fermo' -> [('Il', False), ('denaro', True), ('fermo', False)]"""
    out = []
    pezzi = re.split(r"\*", testo or "")
    for i, pezzo in enumerate(pezzi):
        prima = pezzi[i - 1] if i else ""
        for j, p in enumerate(pezzo.split()):
            # es. «*ci penso*?» -> il «?» resta attaccato, senza spazio
            attaccato = j == 0 and out and not pezzo[:1].isspace() and not prima[-1:].isspace()
            out.append((p, i % 2 == 1, bool(attaccato)))
    return out


def _a_capo(draw, testo, f, larghezza):
    righe, riga = [], []
    for parola, oro, attaccato in _parole(testo):
        if attaccato and riga:
            riga.append((parola, oro, True))
            continue
        prova = "".join(("" if a else " ") + p for p, _, a in riga + [(parola, oro, False)])
        if riga and draw.textlength(prova.strip(), font=f) > larghezza:
            righe.append(riga)
            riga = []
        riga.append((parola, oro, False))
    if riga:
        righe.append(riga)
    return righe


def _blocco(draw, testo, f, x, y, larghezza, colore, oro=ORO, interlinea=1.12, centrato=False):
    """Scrive un testo a capo automatico; restituisce la y finale."""
    alto = int(f.size * interlinea)
    spazio = draw.textlength(" ", font=f)
    for riga in _a_capo(draw, testo, f, larghezza):
        tot = sum(draw.textlength(p, font=f) for p, _, _ in riga) + spazio * sum(1 for *_, a in riga[1:] if not a)
        cx = x + (larghezza - tot) / 2 if centrato else x
        for k, (parola, evid, attaccato) in enumerate(riga):
            if k and not attaccato:
                cx += spazio
            draw.text((cx, y), parola, font=f, fill=oro if evid else colore)
            cx += draw.textlength(parola, font=f)
        y += alto
    return y


def _adatta(draw, testo, nome, larghezza, max_righe, grande, piccolo=44):
    """Il font più grande con cui il testo sta in `max_righe` righe."""
    size = grande
    while size > piccolo:
        f = font(nome, size)
        if len(_a_capo(draw, testo, f, larghezza)) <= max_righe:
            return f
        size -= 4
    return font(nome, piccolo)


def _logo(img, chiaro=True, y=None):
    nome = "logo-full-white.png" if chiaro else "logo-full-navy.png"
    try:
        logo = Image.open(os.path.join(BASE, "social", nome)).convert("RGBA")
    except OSError:
        return
    logo.thumbnail((360, 100))
    logo = logo.crop(logo.getbbox() or (0, 0, logo.width, logo.height))
    img.paste(logo, (MARGINE, y if y is not None else H - 60 - logo.height), logo)


def _kicker(draw, testo, x, y, colore=ORO):
    if not testo:
        return y
    f = font("semi", 30)
    draw.rectangle([x, y + 14, x + 54, y + 18], fill=colore)
    draw.text((x + 74, y), testo.upper(), font=f, fill=colore, spacing=4)
    return y + 70


def _piede(draw, img, chiaro=True, sito=True):
    colore = GRIGIO if chiaro else (95, 107, 122)
    draw.line([MARGINE, H - 150, W - MARGINE, H - 150], fill=(ORO if chiaro else (227, 225, 220)), width=2)
    _logo(img, chiaro)
    if sito:
        f = font("medio", 28)
        t = "dentaliagroup.it"
        draw.text((W - MARGINE - draw.textlength(t, font=f), H - 104), t, font=f, fill=colore)


def _sfondo_navy(img):
    """Blu notte con una luce morbida in alto a destra e un arco oro decorativo."""
    d = ImageDraw.Draw(img)
    luce = Image.new("L", (W, H), 0)
    ImageDraw.Draw(luce).ellipse([W - 620, -520, W + 420, 520], fill=90)
    luce = luce.filter(ImageFilter.GaussianBlur(160))
    img.paste(Image.new("RGB", (W, H), NAVY2), (0, 0), luce)
    d.arc([W - 330, -230, W + 230, 330], 95, 185, fill=ORO, width=3)
    return d


def _foto(nome, larghezza, altezza):
    percorso = nome if os.path.isabs(nome or "") else os.path.join(BASE, "social", "foto-base", nome or "")
    try:
        im = Image.open(percorso).convert("RGB")
    except (OSError, ValueError):
        im = Image.new("RGB", (larghezza, altezza), NAVY2)
    return ImageOps.fit(im, (larghezza, altezza), Image.LANCZOS, centering=(0.5, 0.4))


def genera(scena="titolo", titolo="", testo="", punti=None, tema="", foto=None, foto_bytes=None):
    """Restituisce i byte JPEG della grafica."""
    scena = scena if scena in SCENE else "titolo"
    larg = W - 2 * MARGINE
    if scena in ("domanda", "cta"):
        img = Image.new("RGB", (W, H), ORO_CHIARO if scena == "domanda" else NAVY)
    else:
        img = Image.new("RGB", (W, H), NAVY)

    if scena == "immagine":
        if foto_bytes:
            try:
                im = ImageOps.fit(Image.open(io.BytesIO(foto_bytes)).convert("RGB"), (W, H), Image.LANCZOS)
            except Exception:
                im = _foto(None, W, H)
        else:
            im = _foto(foto, W, H)
        img.paste(im, (0, 0))
        sfuma = Image.new("L", (1, 320))
        for i in range(320):
            sfuma.putpixel((0, i), int(220 * (i / 319) ** 1.4))
        img.paste(Image.new("RGB", (W, 320), NAVY), (0, H - 320), sfuma.resize((W, 320)))
        d = ImageDraw.Draw(img)
        if titolo:
            f = _adatta(d, titolo, "titolo", larg, 2, 64)
            _blocco(d, titolo, f, MARGINE, H - 190 - 2 * int(f.size * 1.12) - 20, larg, BIANCO)
        _logo(img, True)

    elif scena == "titolo":
        d = _sfondo_navy(img)
        y = _kicker(d, tema, MARGINE, 190)
        f = _adatta(d, titolo, "titolo", larg, 6, 104)
        y = _blocco(d, titolo, f, MARGINE, y + 30, larg, BIANCO)
        if testo:
            _blocco(d, testo, font("testo", 40), MARGINE, y + 44, larg - 60, GRIGIO, interlinea=1.4)
        _piede(d, img)

    elif scena == "foto":
        alto_foto = 700
        if foto_bytes:
            try:
                im = ImageOps.fit(Image.open(io.BytesIO(foto_bytes)).convert("RGB"), (W, alto_foto), Image.LANCZOS)
            except Exception:
                im = _foto(None, W, alto_foto)
        else:
            im = _foto(foto, W, alto_foto)
        img.paste(im, (0, 0))
        sfuma = Image.new("L", (1, 260))
        for i in range(260):
            sfuma.putpixel((0, i), int(255 * (i / 259) ** 1.6))
        img.paste(Image.new("RGB", (W, 260), NAVY), (0, alto_foto - 260), sfuma.resize((W, 260)))
        d = ImageDraw.Draw(img)
        y = _kicker(d, tema, MARGINE, alto_foto - 40)
        f = _adatta(d, titolo, "titolo", larg, 4, 80)
        y = _blocco(d, titolo, f, MARGINE, y + 10, larg, BIANCO)
        if testo and y < H - 260:
            _blocco(d, testo, font("testo", 34), MARGINE, y + 24, larg, GRIGIO, interlinea=1.4)
        _piede(d, img)

    elif scena == "lista":
        d = _sfondo_navy(img)
        y = _kicker(d, tema, MARGINE, 190)
        f = _adatta(d, titolo, "titolo", larg, 3, 96)
        y = _blocco(d, titolo, f, MARGINE, y + 20, larg, BIANCO) + 70
        voci = [p for p in (punti or []) if p.strip()][:4]
        ft = font("medio", 46 if len(voci) <= 3 else 40)
        fn = font("titolo", 44)
        for i, voce in enumerate(voci, 1):
            d.rounded_rectangle([MARGINE, y, MARGINE + 76, y + 76], radius=20, fill=ORO)
            n = str(i)
            d.text((MARGINE + 38 - d.textlength(n, font=fn) / 2, y + 10), n, font=fn, fill=NAVY)
            fine = _blocco(d, voce, ft, MARGINE + 110, y + 12, larg - 110, BIANCO, interlinea=1.3)
            y = max(y + 76, fine) + 50
        _piede(d, img)

    elif scena == "domanda":
        d = ImageDraw.Draw(img)
        d.text((MARGINE - 10, 120), "“", font=font("titolo", 300), fill=ORO)
        f = _adatta(d, titolo, "titolo", larg, 6, 96)
        alto = len(_a_capo(d, titolo, f, larg)) * int(f.size * 1.12)
        y = max(430, (H - alto) // 2 - 40)
        y = _blocco(d, titolo, f, MARGINE, y, larg, NAVY, oro=(143, 106, 51))
        if testo:
            _blocco(d, testo, font("testo", 38), MARGINE, y + 40, larg, (95, 107, 122), interlinea=1.4)
        if tema:
            _kicker(d, tema, MARGINE, 380, colore=(143, 106, 51))
        _piede(d, img, chiaro=False)

    else:  # cta
        d = _sfondo_navy(img)
        try:
            simbolo = Image.open(os.path.join(BASE, "social", "icon-white.png")).convert("RGBA")
            simbolo.thumbnail((150, 150))
            img.paste(simbolo, ((W - simbolo.width) // 2, 300), simbolo)
        except OSError:
            pass
        f = _adatta(d, titolo, "titolo", larg, 5, 92)
        y = _blocco(d, titolo, f, MARGINE, 520, larg, BIANCO, centrato=True)
        if testo:
            y = _blocco(d, testo, font("testo", 38), MARGINE + 30, y + 36, larg - 60, GRIGIO, interlinea=1.4,
                        centrato=True)
        etichetta = (punti or ["Prenota il colloquio di valutazione"])[0]
        fb = font("semi", 38)
        lb = d.textlength(etichetta, font=fb) + 100
        x0, y0 = (W - lb) / 2, min(y + 70, H - 330)
        d.rounded_rectangle([x0, y0, x0 + lb, y0 + 100], radius=50, fill=ORO)
        d.text((x0 + 50, y0 + 28), etichetta, font=fb, fill=NAVY)
        _piede(d, img)

    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, optimize=True, progressive=True)
    return out.getvalue()
