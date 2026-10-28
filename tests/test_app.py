"""
Test automatici: GitHub li esegue a ogni push (vedi .github/workflows/test.yml).
In locale:  python -m unittest discover -s tests -v
Usano un database SQLite temporaneo, quindi non toccano i dati reali.
"""
import io
import json
import os
import sys
import tempfile
import unittest

# Su GitHub i test girano due volte: con SQLite e con un vero Postgres (TEST_DATABASE_URL).
DB = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{DB}"
os.environ["ADMIN_EMAIL"] = "admin@test.it"
os.environ["ADMIN_PASSWORD"] = "admin-test-123"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as m  # noqa: E402


def login(email, pw):
    c = m.app.test_client()
    c.post("/login", data={"email": email, "password": pw})
    return c


def risposte(valore):
    return {d["id"]: str(valore) for a in m.AREAS for d in a["domande"]}


def affiliazione(client, vid, prezzo="5000", stato="accettato", cliente="Studio"):
    """Crea il preventivo di affiliazione di una radiografia (obbligatorio prima dei servizi)."""
    return client.post("/preventivi/nuovo", data={"tipo": "affiliazione", "cliente": cliente, "data": "2026-10-27",
                                                 "validita_giorni": "30", "stato": stato, "valutazione_id": str(vid),
                                                 "aff_prezzo": prezzo})


FIRMA_FINTA = "data:image/png;base64," + "iVBORw0KGgo" * 400
DATI_CONTRATTO = {"ragione_sociale": "Studio Test Srl", "piva": "01234567890", "indirizzo": "Via Roma 1", "cap": "09100",
                  "citta": "Cagliari", "provincia": "ca", "legale_rappresentante": "Dott. Mario Test",
                  "email": "studio@test.it"}


def firma_contratto(client, vid):
    """Completa e firma (sul dispositivo) il contratto dell'affiliazione accettata di una radiografia."""
    with m.app.app_context():
        kid = m.contratto_di(m.affiliazione_di(vid).id).id
    client.post(f"/contratti/{kid}", data={**DATI_CONTRATTO, "azione": "pronto"})
    client.post(f"/contratti/{kid}/firma", data={"letto": "1", "clausole": "1", "firmatario": "Dott. Mario Test",
                                                "firma": FIRMA_FINTA})
    return kid


class TestApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m.app.config["TESTING"] = True
        cls.admin = login("admin@test.it", "admin-test-123")
        for nome, email in (("Marco Bianchi", "marco@test.it"), ("Laura Verdi", "laura@test.it")):
            cls.admin.post("/admin/utenti", data={"nome": nome, "email": email, "password": "password123",
                                                 "ruolo": "commerciale"})
        cls.marco = login("marco@test.it", "password123")
        cls.laura = login("laura@test.it", "password123")

    def test_01_login_obbligatorio(self):
        r = m.app.test_client().get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.location)

    def test_02_password_errata(self):
        r = m.app.test_client().post("/login", data={"email": "admin@test.it", "password": "no"})
        self.assertIn("non corretti", r.get_data(as_text=True))

    def test_03_radiografia_e_permessi(self):
        dati = {"studio": "Studio Test", "citta": "Milano", **risposte(2)}
        r = self.marco.post("/nuova", data=dati)
        self.assertEqual(r.status_code, 302)
        pagina = self.marco.get(r.location)
        self.assertEqual(pagina.status_code, 200)
        self.assertIn("Report di azione", pagina.get_data(as_text=True))
        self.assertEqual(self.laura.get(r.location).status_code, 403)
        self.assertEqual(self.admin.get(r.location).status_code, 200)

    def test_04_punteggi(self):
        self.assertTrue(all(v == 0 for v in m.calcola(risposte(1)).values()))
        self.assertTrue(all(v == 100 for v in m.calcola(risposte(5)).values()))

    def test_05_totali_preventivo(self):
        righe = [{"qta": 1, "prezzo": 900, "sconto": 0, "iva": 22},
                 {"qta": 6, "prezzo": 180, "sconto": 10, "iva": 22},
                 {"qta": 2, "prezzo": 350, "sconto": 0, "iva": 22}]
        t = m.calcola_totali(righe, 5)
        self.assertEqual(t["imponibile"], 2443.40)
        self.assertEqual(t["totale"], 2980.95)

    def test_06_preventivo_da_radiografia(self):
        r = self.marco.post("/nuova", data={"studio": "Studio Suggerimenti", **risposte(1)})
        vid = int(r.location.rstrip("/").rsplit("/", 1)[1])
        affiliazione(self.marco, vid, cliente="Studio Suggerimenti")
        firma_contratto(self.marco, vid)
        form = self.marco.get(f"/preventivi/nuovo?valutazione={vid}").get_data(as_text=True)
        self.assertIn("Voci suggerite dalla radiografia", form)
        self.assertIn("Studio Suggerimenti", form)

        dati = {"cliente": "Studio Suggerimenti", "data": "2026-09-29", "validita_giorni": "30",
                "stato": "bozza", "sconto_globale": "0", "valutazione_id": str(vid),
                "r_desc": ["Voce A", "Voce B"], "r_det": ["", ""], "r_qta": ["1", "2"],
                "r_prezzo": ["100", "50"], "r_sconto": ["0", "0"], "r_iva": ["22", "22"],
                "r_unita": ["a corpo", "ora"]}
        r = self.marco.post("/preventivi/nuovo", data=dati)
        self.assertEqual(r.status_code, 302)
        pid = int(r.location.rstrip("/").rsplit("/", 1)[1])
        with m.app.app_context():
            p = m.db.session.get(m.Preventivo, pid)
            self.assertEqual(len(json.loads(p.righe)), 2)
            self.assertEqual(p.valutazione_id, vid)
        stampa = self.marco.get(f"/preventivi/{pid}/stampa")
        self.assertEqual(stampa.status_code, 200)
        self.assertIn("244,00", stampa.get_data(as_text=True))   # 200 + 22% IVA
        self.assertEqual(self.laura.get(f"/preventivi/{pid}").status_code, 403)

    def test_07_numerazione_e_duplica(self):
        dati = {"cliente": "Numerazione", "data": "2026-09-29", "r_desc": ["X"], "r_det": [""], "r_qta": ["1"],
                "r_prezzo": ["10"], "r_sconto": ["0"], "r_iva": ["22"], "r_unita": [""]}
        r = self.admin.post("/preventivi/nuovo", data=dati)
        pid = int(r.location.rstrip("/").rsplit("/", 1)[1])
        self.admin.post(f"/preventivi/{pid}/duplica")
        with m.app.app_context():
            numeri = sorted(p.numero for p in m.Preventivo.query.all())
            self.assertEqual(numeri, list(range(1, len(numeri) + 1)))

    def test_08_archivio_e_filtri(self):
        self.assertEqual(self.marco.get("/preventivi").status_code, 200)
        self.assertEqual(self.marco.get("/preventivi?stato=bozza&q=test").status_code, 200)
        self.assertEqual(self.admin.get("/preventivi?commerciale=2").status_code, 200)

    def test_09_pagine_admin(self):
        for url in ("/admin", "/listino", "/impostazioni"):
            self.assertEqual(self.admin.get(url).status_code, 200, url)
            self.assertEqual(self.marco.get(url).status_code, 403, url)

    def test_11_richiesta_accesso_e_attivazione(self):
        anonimo = m.app.test_client()
        r = anonimo.post("/registrati", data={"nome": "Giulia Neri", "email": "giulia@test.it", "telefono": "",
                                              "password": "password123", "conferma": "password123"})
        self.assertIn("Richiesta inviata", r.get_data(as_text=True))
        # non può entrare finché non è attivata
        r = anonimo.post("/login", data={"email": "giulia@test.it", "password": "password123"})
        self.assertIn("in attesa", r.get_data(as_text=True))
        # l'admin la vede e la attiva
        pannello = self.admin.get("/admin").get_data(as_text=True)
        self.assertIn("Giulia Neri", pannello)
        self.assertIn("Richieste di accesso", pannello)
        with m.app.app_context():
            uid = m.Utente.query.filter_by(email="giulia@test.it").first().id
        self.assertEqual(self.marco.post(f"/admin/utenti/{uid}/attiva").status_code, 403)
        self.admin.post(f"/admin/utenti/{uid}/attiva")
        giulia = m.app.test_client()
        r = giulia.post("/login", data={"email": "giulia@test.it", "password": "password123"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(giulia.get("/").status_code, 200)
        # disattivazione: la sessione viene chiusa
        self.admin.post(f"/admin/utenti/{uid}/stato")
        self.assertEqual(giulia.get("/").status_code, 302)

    def test_12_rifiuto_richiesta(self):
        m.app.test_client().post("/registrati", data={"nome": "Spam", "email": "spam@test.it",
                                                      "password": "password123", "conferma": "password123"})
        with m.app.app_context():
            uid = m.Utente.query.filter_by(email="spam@test.it").first().id
        self.admin.post(f"/admin/utenti/{uid}/rifiuta")
        with m.app.app_context():
            self.assertIsNone(m.Utente.query.filter_by(email="spam@test.it").first())

    def test_13_admin_atterra_su_admin(self):
        r = m.app.test_client().post("/login", data={"email": "admin@test.it", "password": "admin-test-123"})
        self.assertTrue(r.location.endswith("/admin"))

    def test_14_dati_azienda_e_sdi(self):
        with m.app.app_context():
            imp = m.impostazioni()
            imp.piva, imp.indirizzo, imp.sdi = "04149000921", "Via delle Orchidee 33", None
            m.db.session.commit()
            m.completa_dati_azienda()
            imp = m.impostazioni()
            self.assertEqual(imp.sdi, "M5UXCR1")
            self.assertEqual(imp.indirizzo, "Via delle Orchidee 33, 09067 Elmas (CA)")
            # un secondo avvio non sovrascrive modifiche fatte a mano
            imp.indirizzo = "Indirizzo cambiato a mano"
            m.db.session.commit()
            m.completa_dati_azienda()
            self.assertEqual(m.impostazioni().indirizzo, "Indirizzo cambiato a mano")
        self.admin.post("/impostazioni", data={"ragione_sociale": "CONSULTING SARDEGNA SRL", "piva": "04149000921",
                                               "sdi": "M5UXCR1", "validita_default": "15"})
        pagina = self.admin.get("/impostazioni").get_data(as_text=True)
        self.assertIn("M5UXCR1", pagina)

    def test_15_area_privata_e_pulizia(self):
        self.assertTrue(m.app.test_client().get("/area-privata").location.endswith("/login"))
        self.assertTrue(self.admin.get("/area-privata/").location.endswith("/admin"))
        self.assertIn("Area privata", m.app.test_client().get("/login").get_data(as_text=True))
        prova = m.app.test_client()
        self.admin.post("/admin/utenti", data={"nome": "Prova", "email": "prova@gmail.com",
                                               "password": "password123", "ruolo": "commerciale"})
        prova.post("/login", data={"email": "prova@gmail.com", "password": "password123"})
        prova.post("/nuova", data={"studio": "Studio di prova", **risposte(3)})
        with m.app.app_context():
            m.pulizia_dati_prova()
            self.assertIsNone(m.Utente.query.filter_by(email="prova@gmail.com").first())
            self.assertFalse([v for v in m.Valutazione.query.all() if v.studio == "Studio di prova"])
            self.assertIsNotNone(m.Utente.query.filter_by(email="admin@test.it").first())

    def test_10_listino_iniziale(self):
        with m.app.app_context():
            self.assertGreater(m.Servizio.query.count(), 5)


    def test_16_pagina_domande(self):
        # solo l'admin la vede
        self.assertEqual(self.marco.get("/admin/domande").status_code, 403)
        pagina = self.admin.get("/admin/domande").get_data(as_text=True)
        self.assertIn("Domande della radiografia", pagina)

        # radiografia fatta con le domande di adesso
        r = self.marco.post("/nuova", data={"studio": "Studio Prima", **risposte(3)})
        vid_prima = int(r.location.rstrip("/").rsplit("/", 1)[1])
        nome_prima = m.AREE_INIZIALI[0]["nome"]

        # l'admin cambia le domande: rinomina la prima area, toglie l'ultima, ne aggiunge una nuova
        aree = json.loads(json.dumps(m.AREE_INIZIALI))
        aree[0]["nome"] = "Area Rinominata Test"
        aree[0]["domande"][0]["testo"] = "Domanda cambiata dal pannello?"
        aree.pop()
        aree.append({"nome": "Area Extra Test", "breve": "Extra", "domande": [{"testo": "Domanda extra test?"}],
                     "azioni": ["Azione extra test"]})
        r = self.admin.post("/admin/domande", data={"dati": json.dumps(aree)})
        self.assertEqual(r.status_code, 302)
        with m.app.app_context():
            nuove = m.aree_correnti()
        self.assertEqual(nuove[0]["nome"], "Area Rinominata Test")
        self.assertEqual(nuove[-1]["nome"], "Area Extra Test")
        self.assertTrue(nuove[-1]["id"] and nuove[-1]["domande"][0]["id"])
        self.assertEqual(len(nuove), len(m.AREE_INIZIALI))

        # i commerciali vedono le domande nuove e la radiografia nuova le usa
        form = self.marco.get("/nuova").get_data(as_text=True)
        self.assertIn("Domanda extra test?", form)
        self.assertIn("Domanda cambiata dal pannello?", form)
        tutte = {d["id"]: "5" for a in nuove for d in a["domande"]}
        r = self.marco.post("/nuova", data={"studio": "Studio Dopo", **tutte})
        vid_dopo = int(r.location.rstrip("/").rsplit("/", 1)[1])
        with m.app.app_context():
            v = m.db.session.get(m.Valutazione, vid_dopo)
            self.assertEqual(json.loads(v.punteggi)[nuove[-1]["id"]], 100)
        dopo = self.marco.get(f"/valutazione/{vid_dopo}").get_data(as_text=True)
        self.assertIn("Area Extra Test", dopo)

        # la radiografia vecchia resta con le domande di allora
        prima = self.marco.get(f"/valutazione/{vid_prima}").get_data(as_text=True)
        self.assertIn(nome_prima, prima)
        self.assertNotIn("Area Extra Test", prima)

        # dati non validi: area senza nome, meno di 3 aree -> non salva
        sbagliate = json.loads(json.dumps(nuove))
        sbagliate[1]["nome"] = ""
        r = self.admin.post("/admin/domande", data={"dati": json.dumps(sbagliate)}, follow_redirects=True)
        self.assertIn("non ha un nome", r.get_data(as_text=True))
        r = self.admin.post("/admin/domande", data={"dati": json.dumps(nuove[:2])}, follow_redirects=True)
        self.assertIn("almeno 3 aree", r.get_data(as_text=True))
        with m.app.app_context():
            self.assertEqual(m.aree_correnti()[0]["nome"], "Area Rinominata Test")

        # il commerciale non può modificarle
        self.assertEqual(self.marco.post("/admin/domande", data={"dati": json.dumps(nuove)}).status_code, 403)
        self.assertEqual(self.marco.post("/admin/domande/ripristina").status_code, 403)

        # ripristino delle domande iniziali
        self.admin.post("/admin/domande/ripristina")
        with m.app.app_context():
            self.assertEqual(m.aree_correnti(), m.AREE_INIZIALI)
        self.assertIn("Area Extra Test", self.marco.get(f"/valutazione/{vid_dopo}").get_data(as_text=True))

    def test_18_note_interne_per_domanda(self):
        form = self.marco.get("/nuova").get_data(as_text=True)
        self.assertIn('name="nota_', form)
        with m.app.app_context():
            aree = m.aree_correnti()
        tutte = {d["id"]: "2" for a in aree for d in a["domande"]}
        qid = aree[0]["domande"][0]["id"]
        r = self.marco.post("/nuova", data={"studio": "Studio Note", **tutte,
                                           "nota_" + qid: "Il titolare era scettico sui richiami"})
        self.assertEqual(r.status_code, 302)
        pagina = self.marco.get(r.location).get_data(as_text=True)
        self.assertIn("Il titolare era scettico sui richiami", pagina)
        self.assertIn("note-interne no-print", pagina)
        self.assertIn("Il titolare era scettico", self.admin.get(r.location).get_data(as_text=True))
        self.assertEqual(self.laura.get(r.location).status_code, 403)

    def test_19_migrazione_tra_database(self):
        from sqlalchemy import create_engine, func, select
        from migrazione import copia_dati
        cartella = tempfile.mkdtemp()
        destinazione = f"sqlite:///{os.path.join(cartella, 'nuovo.db')}"
        # il database di origine = quello dei test (pieno), la destinazione = nuovo e con le righe di avvio
        with m.app.app_context():
            src = m.db.engine
            dest = create_engine(destinazione)
            m.db.metadata.create_all(dest)
            n_val = m.Valutazione.query.count()
            n_ut = m.Utente.query.count()
            esito = copia_dati(src.url.render_as_string(hide_password=False), dest, m.db.metadata)
        self.assertIsNotNone(esito)
        self.assertEqual(esito["valutazione"], n_val)
        with dest.connect() as c:
            self.assertEqual(c.execute(select(func.count()).select_from(m.db.metadata.tables["utente"])).scalar(), n_ut)
        # una seconda volta non sovrascrive (destinazione non vuota)
        self.assertIsNone(copia_dati(src.url.render_as_string(hide_password=False), dest, m.db.metadata))

    def test_20_elimina_radiografia_con_preventivo(self):
        with m.app.app_context():
            aree = m.aree_correnti()
        r = self.marco.post("/nuova", data={"studio": "Studio Da Eliminare", **{d["id"]: "3" for a in aree for d in a["domande"]}})
        vid = int(r.location.rstrip("/").rsplit("/", 1)[1])
        r = affiliazione(self.marco, vid, stato="bozza", cliente="Studio Da Eliminare")
        pid = int(r.location.rstrip("/").rsplit("/", 1)[1])
        r = self.marco.post(f"/valutazione/{vid}/elimina")
        self.assertEqual(r.status_code, 302)
        with m.app.app_context():
            self.assertIsNone(m.db.session.get(m.Valutazione, vid))
            p = m.db.session.get(m.Preventivo, pid)
            self.assertIsNotNone(p)
            self.assertIsNone(p.valutazione_id)

    # ---------------------------------------------------------------- CRM
    def _nuovo_contatto(self, client, **campi):
        dati = {"studio": "Studio CRM", "titolare": "Dott. Bianchi", "telefono": "070 555 0101", **campi}
        r = client.post("/contatti/nuovo", data=dati)
        self.assertEqual(r.status_code, 302)
        return int(r.location.rstrip("/").rsplit("/", 1)[1])

    def test_21_crm_flusso_chiamate(self):
        cid = self._nuovo_contatto(self.marco, telefono="070 555 0101")
        pagina = self.marco.get(f"/contatti/{cid}").get_data(as_text=True)
        self.assertIn("Com'è andata la chiamata?", pagina)
        with m.app.app_context():
            c = m.db.session.get(m.Contatto, cid)
            self.assertEqual((c.stato, c.aperture), ("nuovo", 1))
        # riaprire subito la scheda non riconta l'apertura
        self.marco.get(f"/contatti/{cid}")
        self.marco.post(f"/contatti/{cid}/chiamata", data={"esito": "non_risponde", "nota": "Squilla a vuoto",
                                                          "richiamare_il": "2026-11-02T10:00"})
        with m.app.app_context():
            c = m.db.session.get(m.Contatto, cid)
            self.assertEqual((c.stato, c.tentativi, c.aperture), ("richiamare", 1, 1))
            self.assertIsNotNone(c.richiamare_il)
        # appuntamento senza data: non cambia nulla
        self.marco.post(f"/contatti/{cid}/chiamata", data={"esito": "appuntamento"})
        with m.app.app_context():
            self.assertEqual(m.db.session.get(m.Contatto, cid).stato, "richiamare")
        self.marco.post(f"/contatti/{cid}/chiamata", data={"esito": "appuntamento", "appuntamento_il": "2026-11-05T15:30"})
        with m.app.app_context():
            c = m.db.session.get(m.Contatto, cid)
            self.assertEqual((c.stato, c.tentativi), ("appuntamento", 2))
            self.assertEqual(c.appuntamento_il.hour, 14)   # 15:30 ora italiana = 14:30 UTC
        r = self.marco.post(f"/contatti/{cid}/chiamata", data={"esito": "presentato_radiografia"})
        self.assertIn(f"/nuova?contatto={cid}", r.location)
        form = self.marco.get(f"/nuova?contatto={cid}").get_data(as_text=True)
        self.assertIn('value="Studio CRM"', form)
        with m.app.app_context():
            aree = m.aree_correnti()
        r = self.marco.post("/nuova", data={"studio": "Studio CRM", "contatto_id": str(cid),
                                           **{d["id"]: "2" for a in aree for d in a["domande"]}})
        vid = int(r.location.rstrip("/").rsplit("/", 1)[1])
        with m.app.app_context():
            c = m.db.session.get(m.Contatto, cid)
            self.assertEqual((c.stato, c.valutazione_id), ("presentato", vid))
            self.assertEqual(m.db.session.get(m.Valutazione, vid).contatto_id, cid)
            tipi = [a.tipo for a in m.Attivita.query.filter_by(contatto_id=cid).all()]
            self.assertIn("radiografia", tipi)
        # note sempre possibili, permessi e riassegnazione dall'admin
        self.marco.post(f"/contatti/{cid}/nota", data={"nota": "Interessato al magazzino"})
        self.assertIn("Interessato al magazzino", self.marco.get(f"/contatti/{cid}").get_data(as_text=True))
        self.assertEqual(self.laura.get(f"/contatti/{cid}").status_code, 403)
        self.assertEqual(self.admin.get(f"/contatti/{cid}").status_code, 200)
        self.assertEqual(self.marco.post("/contatti/assegna", data={"ids": str(cid), "utente_id": "1"}).status_code, 403)
        with m.app.app_context():
            laura = m.Utente.query.filter_by(email="laura@test.it").first().id
        self.admin.post("/contatti/assegna", data={"ids": str(cid), "utente_id": str(laura)})
        self.assertEqual(self.laura.get(f"/contatti/{cid}").status_code, 200)
        self.assertEqual(self.marco.get(f"/contatti/{cid}").status_code, 403)

    def test_22_crm_non_interessato_va_in_newsletter(self):
        cid = self._nuovo_contatto(self.marco, studio="Studio Newsletter", telefono="070 555 0202",
                                   email="info@newsletter.it")
        self.marco.post(f"/contatti/{cid}/chiamata", data={"esito": "non_interessato", "consenso_newsletter": "1"})
        with m.app.app_context():
            c = m.db.session.get(m.Contatto, cid)
            self.assertEqual((c.stato, c.newsletter), ("non_interessato", True))
            self.assertIsNotNone(c.consenso_il)
        # senza spunta del consenso non si entra in newsletter
        cid2 = self._nuovo_contatto(self.marco, studio="Studio Senza Consenso", telefono="070 555 0909",
                                    email="no@consenso.it")
        self.marco.post(f"/contatti/{cid2}/chiamata", data={"esito": "non_interessato"})
        with m.app.app_context():
            self.assertFalse(m.db.session.get(m.Contatto, cid2).newsletter)
        elenco = self.marco.get("/contatti?stato=non_interessato").get_data(as_text=True)
        self.assertIn("Studio Newsletter", elenco)

    def test_23_crm_import_csv_e_doppioni(self):
        csv_testo = ("Nome studio;Titolare;Cellulare;Comune;Provincia\n"
                     "Studio Uno;Dott. Uno;+39 333 1111111;Cagliari;CA\n"
                     "Studio Due;Dott.ssa Due;070 2222222;Quartu;CA\n"
                     "Studio Uno bis;;333 111 1111;Cagliari;CA\n"
                     "Senza telefono;Dott. Tre;;Sassari;SS\n")
        r = self.marco.post("/contatti/importa", content_type="multipart/form-data",
                            data={"file": (io.BytesIO(csv_testo.encode("utf-8")), "contatti.csv")})
        testo = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        with m.app.app_context():
            uno = m.Contatto.query.filter_by(studio="Studio Uno").first()
            self.assertEqual((uno.titolare, uno.citta, uno.fonte, uno.stato), ("Dott. Uno", "Cagliari (CA)", "import", "nuovo"))
            self.assertIsNotNone(m.Contatto.query.filter_by(studio="Studio Due").first())
            self.assertIsNone(m.Contatto.query.filter_by(studio="Studio Uno bis").first())   # stesso telefono
            self.assertIsNone(m.Contatto.query.filter_by(studio="Senza telefono").first())
        self.assertIn("Importazione completata", testo)

    def test_24_crm_import_excel(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Studio", "Titolare", "Telefono", "Email", "Città"])
        ws.append(["Studio Excel", "Dott. Excel", "079 9999999", "excel@studio.it", "Sassari"])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        r = self.admin.post("/contatti/importa", content_type="multipart/form-data",
                            data={"file": (buf, "contatti.xlsx")})
        self.assertEqual(r.status_code, 200)
        with m.app.app_context():
            c = m.Contatto.query.filter_by(studio="Studio Excel").first()
            self.assertEqual((c.email, c.citta), ("excel@studio.it", "Sassari"))
        self.assertIn("Studio Excel", self.admin.get("/contatti?q=excel").get_data(as_text=True))
        self.assertEqual(self.admin.get("/contatti/modello.csv").status_code, 200)

    def test_25_affiliazione_obbligatoria_e_prezzo_minimo(self):
        cid = self._nuovo_contatto(self.marco, studio="Studio Affiliando", telefono="070 555 0303")
        self.marco.post(f"/contatti/{cid}/chiamata", data={"esito": "appuntamento", "appuntamento_il": "2026-11-10T10:00"})
        self.marco.post(f"/contatti/{cid}/chiamata", data={"esito": "presentato"})
        with m.app.app_context():
            aree = m.aree_correnti()
        r = self.marco.post("/nuova", data={"studio": "Studio Affiliando", "contatto_id": str(cid),
                                           **{d["id"]: "2" for a in aree for d in a["domande"]}})
        vid = int(r.location.rstrip("/").rsplit("/", 1)[1])
        self.assertIn("Crea il preventivo di affiliazione", self.marco.get(f"/valutazione/{vid}").get_data(as_text=True))
        # senza affiliazione si viene portati al preventivo di affiliazione
        r = self.marco.get(f"/preventivi/nuovo?valutazione={vid}")
        self.assertEqual(r.status_code, 302)
        self.assertIn("tipo=affiliazione", r.location)
        form = self.marco.get(r.location).get_data(as_text=True)
        self.assertIn("Licenza di uso per marchio Dentalia", form)
        self.assertIn("Report scritto delle criticità dello studio", form)
        # sotto i 4.000 € non si salva
        with m.app.app_context():
            n_prima = m.Preventivo.query.count()
        r = affiliazione(self.marco, vid, prezzo="3500", stato="bozza", cliente="Studio Affiliando")
        self.assertIn("deve stare tra", r.get_data(as_text=True))
        with m.app.app_context():
            self.assertEqual(m.Preventivo.query.count(), n_prima)
        r = affiliazione(self.marco, vid, prezzo="4500", stato="inviato", cliente="Studio Affiliando")
        pid = int(r.location.rstrip("/").rsplit("/", 1)[1])
        with m.app.app_context():
            p = m.db.session.get(m.Preventivo, pid)
            t = m.calcola_totali(json.loads(p.righe), p.sconto_globale)
            self.assertEqual((p.tipo, t["imponibile"], t["totale"]), ("affiliazione", 4500.0, 5490.0))
        # i servizi restano bloccati finché l'affiliazione non è accettata
        r = self.marco.get(f"/preventivi/nuovo?valutazione={vid}")
        self.assertIn(f"/preventivi/{pid}", r.location)
        servizi = {"tipo": "servizi", "cliente": "Studio Affiliando", "data": "2026-10-27", "valutazione_id": str(vid),
                   "r_desc": ["Consulenza"], "r_det": [""], "r_qta": ["1"], "r_prezzo": ["900"], "r_sconto": ["0"],
                   "r_iva": ["22"], "r_unita": ["a corpo"]}
        self.marco.post("/preventivi/nuovo", data=servizi)
        with m.app.app_context():
            self.assertEqual(m.Preventivo.query.filter_by(valutazione_id=vid, tipo="servizi").count(), 0)
        # accettata: nasce il contratto da firmare; i servizi restano bloccati fino alla firma
        self.marco.post(f"/preventivi/{pid}/stato", data={"stato": "accettato"})
        with m.app.app_context():
            self.assertEqual(m.db.session.get(m.Contatto, cid).stato, "contratto")
            k = m.contratto_di(pid)
            self.assertEqual((k.stato, k.ragione_sociale), ("da_compilare", "Studio Affiliando"))
            kid = k.id
        r = self.marco.get(f"/preventivi/nuovo?valutazione={vid}")
        self.assertIn(f"/contratti/{kid}", r.location)
        self.assertIn("Fai firmare il contratto", self.marco.get(f"/valutazione/{vid}").get_data(as_text=True))
        scheda = self.marco.get(f"/contratti/{kid}").get_data(as_text=True)
        self.assertIn("BOZZA PROVVISORIA", scheda)
        self.assertEqual(self.laura.get(f"/contratti/{kid}").status_code, 403)
        # senza i dati obbligatori non va in firma
        self.marco.post(f"/contratti/{kid}", data={"ragione_sociale": "Studio Affiliando", "azione": "pronto"})
        with m.app.app_context():
            self.assertEqual(m.db.session.get(m.Contratto, kid).stato, "da_compilare")
        self.marco.post(f"/contratti/{kid}", data={**DATI_CONTRATTO, "azione": "pronto"})
        with m.app.app_context():
            k = m.db.session.get(m.Contratto, kid)
            self.assertEqual((k.stato, k.provincia), ("da_firmare", "CA"))
            self.assertIn("Studio Test Srl", k.testo)
            self.assertIn("4.500,00", k.testo)
            self.assertIn("Licenza di uso per marchio Dentalia", k.testo)
            token = k.token
        # firma dal link, senza login
        anonimo = m.app.test_client()
        pagina = anonimo.get(f"/firma/{token}").get_data(as_text=True)
        self.assertIn("Firma il contratto", pagina)
        anonimo.post(f"/firma/{token}", data={"firmatario": "Dott. Mario Test", "firma": FIRMA_FINTA})   # senza spunte
        with m.app.app_context():
            self.assertEqual(m.db.session.get(m.Contratto, kid).stato, "da_firmare")
        anonimo.post(f"/firma/{token}", data={"letto": "1", "clausole": "1", "firmatario": "Dott. Mario Test",
                                             "firma": FIRMA_FINTA})
        with m.app.app_context():
            k = m.db.session.get(m.Contratto, kid)
            self.assertEqual((k.stato, k.firma_modo, k.firmatario), ("firmato", "link", "Dott. Mario Test"))
            self.assertEqual(len(k.hash_testo), 64)
            self.assertEqual(m.db.session.get(m.Contatto, cid).stato, "cliente")
        self.assertIn("Contratto firmato", anonimo.get(f"/firma/{token}").get_data(as_text=True))
        self.assertEqual(anonimo.get(f"/firma/{token}/copia").status_code, 200)
        self.assertEqual(anonimo.get("/firma/inesistente").status_code, 404)
        self.assertIn("impronta SHA-256", self.marco.get(f"/contratti/{kid}/stampa").get_data(as_text=True))
        self.assertIn("Crea preventivo dei servizi", self.marco.get(f"/valutazione/{vid}").get_data(as_text=True))
        self.assertEqual(self.marco.get(f"/preventivi/nuovo?valutazione={vid}").status_code, 200)
        self.marco.post("/preventivi/nuovo", data=servizi)
        with m.app.app_context():
            self.assertEqual(m.Preventivo.query.filter_by(valutazione_id=vid, tipo="servizi").count(), 1)
        stampa = self.marco.get(f"/preventivi/{pid}/stampa").get_data(as_text=True)
        self.assertIn("Start-up kit Dentalia Marketing", stampa)
        self.assertIn("5.490,00", stampa)
        self.assertEqual(self.marco.get(f"/preventivi/{pid}").status_code, 200)

    def test_26_impostazioni_affiliazione(self):
        base = {"ragione_sociale": "CONSULTING SARDEGNA SRL", "validita_default": "30"}
        self.admin.post("/impostazioni", data={**base, "aff_titolo": "X", "aff_prezzo": "5000", "aff_minimo": "6000",
                                              "aff_voci": "A\nB"})
        with m.app.app_context():
            self.assertEqual(m.conf_affiliazione()["minimo"], 4000.0)   # minimo sopra il prezzo: rifiutato
        self.admin.post("/impostazioni", data={**base, "aff_titolo": "", "aff_prezzo": "5000", "aff_minimo": "4000",
                                              "aff_voci": ""})
        with m.app.app_context():
            c = m.conf_affiliazione()
            self.assertEqual((len(c["voci"]), c["prezzo"], c["minimo"]), (11, 5000.0, 4000.0))
        self.assertIn("Preventivo di affiliazione", self.admin.get("/impostazioni").get_data(as_text=True))
        self.assertIn("Modello del contratto", self.admin.get("/impostazioni").get_data(as_text=True))

    def test_27_pannello_kpi_cliccabile(self):
        cid = self._nuovo_contatto(self.laura, studio="Studio KPI", telefono="070 555 0404")
        self.laura.post(f"/contatti/{cid}/chiamata", data={"esito": "non_risponde"})
        self.laura.post(f"/contatti/{cid}/chiamata", data={"esito": "appuntamento", "appuntamento_il": "2026-11-12T11:00"})
        self.laura.post(f"/contatti/{cid}/chiamata", data={"esito": "presentato"})
        pagina = self.laura.get("/kpi?periodo=tutto").get_data(as_text=True)
        self.assertIn("Imbuto commerciale", pagina)
        self.assertIn("kpi=appuntamenti", pagina)
        with m.app.app_context():
            uid = m.Utente.query.filter_by(email="laura@test.it").first().id
        for chiave in ("contattati", "appuntamenti", "presentati"):
            elenco = self.laura.get(f"/contatti?kpi={chiave}&da=2000-01-01").get_data(as_text=True)
            self.assertIn("Studio KPI", elenco, chiave)
        self.assertNotIn("Studio KPI", self.laura.get("/contatti?kpi=non_interessati&da=2000-01-01").get_data(as_text=True))
        # l'admin vede tutto il team e filtra per commerciale; la tabella dei richiami conta le chiamate
        adm = self.admin.get(f"/kpi?periodo=tutto&commerciale={uid}").get_data(as_text=True)
        self.assertIn("Richiami per commerciale", adm)
        self.assertIn("Laura Verdi", adm)
        self.assertEqual(self.admin.get("/kpi").status_code, 200)
        for q in ("stato=consegnati&da=2000-01-01&a=2100-01-01", "tipo=affiliazione&stato=accettato", "tipo=servizi"):
            self.assertEqual(self.admin.get(f"/preventivi?{q}").status_code, 200)

    def test_28_newsletter_invio_e_disiscrizione(self):
        cid = self._nuovo_contatto(self.marco, studio="Studio Iscritto", titolare="Dott. Iscritto", telefono="070 555 0505")
        self.marco.post(f"/contatti/{cid}/chiamata", data={"esito": "non_interessato", "consenso_newsletter": "1",
                                                          "email_nl": "iscritto@studio.it"})
        with m.app.app_context():
            c = m.db.session.get(m.Contatto, cid)
            self.assertEqual((c.newsletter, c.email), (True, "iscritto@studio.it"))
            token = c.token_nl
        self.assertEqual(self.marco.get("/newsletter").status_code, 403)
        self.assertIn("Studio Iscritto", self.admin.get("/newsletter").get_data(as_text=True))
        m.app.config["EMAIL_INVIATE"] = []
        r = self.admin.post("/newsletter/nuova", data={"oggetto": "Novità Dentalia", "azione": "salva",
                                                     "corpo": "Ciao **a tutti**.\n\n- primo punto\n- secondo punto\n\nhttps://www.dentaliagroup.it"})
        nid = int(r.location.rstrip("/").rsplit("/", 1)[1])
        self.assertIn("<strong>a tutti</strong>", self.admin.get(f"/newsletter/{nid}").get_data(as_text=True))
        self.admin.post(f"/newsletter/{nid}/prova")
        self.assertEqual(len(m.app.config["EMAIL_INVIATE"]), 1)
        self.assertEqual(m.app.config["EMAIL_INVIATE"][0]["To"], "admin@test.it")
        self.admin.post(f"/newsletter/{nid}/invia")
        inviate = [e for e in m.app.config["EMAIL_INVIATE"] if e["To"] == "iscritto@studio.it"]
        self.assertEqual(len(inviate), 1)
        html = inviate[0].get_body(("html",)).get_content()
        self.assertIn(f"/newsletter/disiscrivi/{token}", html)
        self.assertIn("Gentile Dott. Iscritto", html)
        self.assertIn("List-Unsubscribe", str(inviate[0]))
        with m.app.app_context():
            self.assertEqual(m.db.session.get(m.Newsletter, nid).stato, "inviata")
        # disiscrizione col link (senza login)
        anonimo = m.app.test_client()
        self.assertIn("Sì, disiscrivimi", anonimo.get(f"/newsletter/disiscrivi/{token}").get_data(as_text=True))
        self.assertIn("Non riceverai più", anonimo.post(f"/newsletter/disiscrivi/{token}").get_data(as_text=True))
        with m.app.app_context():
            c = m.db.session.get(m.Contatto, cid)
            self.assertEqual((c.newsletter, c.disiscritto), (False, True))
        self.assertIn("non valido", anonimo.get("/newsletter/disiscrivi/sbagliato").get_data(as_text=True))
        self.assertEqual(self.admin.get("/newsletter/esporta.csv").status_code, 200)

    def test_29_sequenza_automatica(self):
        with m.app.app_context():
            self.assertEqual(m.SequenzaEmail.query.count(), 6)   # copy iniziale pronto
        self.assertIn("Sequenza spenta", self.admin.get("/newsletter/sequenza").get_data(as_text=True))
        cid = self._nuovo_contatto(self.marco, studio="Studio Funnel", titolare="Dott. Funnel", telefono="070 555 0606",
                                   email="funnel@studio.it")
        self.marco.post(f"/contatti/{cid}/chiamata", data={"esito": "no_appuntamento", "consenso_newsletter": "1"})
        import sequenza as seq
        m.app.config["EMAIL_INVIATE"] = []
        with m.app.app_context():
            self.assertEqual(seq.esegui_giro(), 0)                   # spenta: non parte nulla
        self.admin.post("/newsletter/sequenza", data={"attiva": "1"})
        per_funnel = lambda: [e for e in m.app.config["EMAIL_INVIATE"] if e["To"] == "funnel@studio.it"]
        with m.app.app_context():
            seq.esegui_giro()
            self.assertEqual(len(per_funnel()), 1)                   # email del giorno 0
            seq.esegui_giro()
            self.assertEqual(len(per_funnel()), 1)                   # mai due nello stesso giorno, la 2a è al giorno 3
            c = m.db.session.get(m.Contatto, cid)
            # tre giorni dopo il consenso parte la seconda
            c.consenso_il -= __import__("datetime").timedelta(days=3)
            for inv in m.SequenzaInvio.query.filter_by(contatto_id=cid).all():
                inv.inviata_il -= __import__("datetime").timedelta(days=3)
            m.db.session.commit()
            seq.esegui_giro()
            self.assertEqual(len(per_funnel()), 2)
        oggetti = [e["Subject"] for e in m.app.config["EMAIL_INVIATE"] if e["To"] == "funnel@studio.it"]
        self.assertEqual(len(oggetti), 2)
        self.assertIn("Promessa", oggetti[0])
        html = per_funnel()[-1].get_body(("html",)).get_content()
        self.assertIn("Gentile Dott. Funnel", html)
        self.assertIn("aree/sviluppo-commerciale", html)
        # se prende appuntamento la sequenza si ferma
        self.marco.post(f"/contatti/{cid}/chiamata", data={"esito": "appuntamento", "appuntamento_il": "2026-12-01T10:00"})
        with m.app.app_context():
            c = m.db.session.get(m.Contatto, cid)
            c.consenso_il -= __import__("datetime").timedelta(days=30)
            for inv in m.SequenzaInvio.query.filter_by(contatto_id=cid).all():
                inv.inviata_il -= __import__("datetime").timedelta(days=30)
            m.db.session.commit()
            seq.esegui_giro()
            self.assertEqual(len(per_funnel()), 2)
        # modifica di un'email e pagina
        with m.app.app_context():
            eid = m.SequenzaEmail.query.order_by(m.SequenzaEmail.giorno).first().id
        self.admin.post(f"/newsletter/sequenza/{eid}", data={"giorno": "0", "oggetto": "Benvenuto nuovo", "corpo": "Testo",
                                                           "attiva": "1", "azione": "salva"})
        self.assertIn("Benvenuto nuovo", self.admin.get("/newsletter/sequenza").get_data(as_text=True))
        self.admin.post("/newsletter/sequenza", data={"attiva": "0"})
        self.assertEqual(self.marco.get("/newsletter/sequenza").status_code, 403)

    def test_30_contratto_firma_sul_dispositivo_e_modello(self):
        with m.app.app_context():
            aree = m.aree_correnti()
        r = self.laura.post("/nuova", data={"studio": "Studio Firma Qui", **{d["id"]: "3" for a in aree for d in a["domande"]}})
        vid = int(r.location.rstrip("/").rsplit("/", 1)[1])
        affiliazione(self.laura, vid, cliente="Studio Firma Qui")
        # modello dei legali con segnaposto
        self.admin.post("/impostazioni", data={"ragione_sociale": "CONSULTING SARDEGNA SRL", "validita_default": "30",
                                              "contratto_testo": "CONTRATTO {numero_contratto}\n\nTra {azienda_ragione_sociale} e {cliente_ragione_sociale} per {totale}."})
        kid = firma_contratto(self.laura, vid)
        with m.app.app_context():
            k = m.db.session.get(m.Contratto, kid)
            self.assertEqual((k.stato, k.firma_modo), ("firmato", "dispositivo"))
            self.assertIn("Tra CONSULTING SARDEGNA SRL e Studio Test Srl per € 6.100,00.", k.testo)
            self.assertNotIn("BOZZA", k.testo)
        self.assertIn("Studio Test Srl", self.laura.get("/contratti?stato=firmato").get_data(as_text=True))
        self.laura.post(f"/contratti/{kid}/firma-azienda", data={"firmatario_azienda": "Laura Verdi", "firma_azienda": FIRMA_FINTA})
        with m.app.app_context():
            self.assertEqual(m.db.session.get(m.Contratto, kid).firmatario_azienda, "Laura Verdi")
        self.assertIn("contratti firmati", self.admin.get("/kpi?periodo=tutto").get_data(as_text=True))
        self.admin.post("/impostazioni", data={"ragione_sociale": "CONSULTING SARDEGNA SRL", "validita_default": "30",
                                              "contratto_testo": ""})

    def test_31_preventivi_raggruppati_per_cliente(self):
        base = {"data": "2026-10-28", "r_desc": ["Voce"], "r_det": [""], "r_qta": ["1"], "r_sconto": ["0"],
                "r_iva": ["22"], "r_unita": [""]}
        for stato, prezzo in (("accettato", "100"), ("sospeso", "200"), ("inviato", "300")):
            self.admin.post("/preventivi/nuovo", data={**base, "cliente": "Clinica Raggruppata", "stato": stato,
                                                     "oggetto": f"Servizio {stato}", "r_prezzo": [prezzo]})
        pagina = self.admin.get("/preventivi?q=raggruppata").get_data(as_text=True)
        self.assertEqual(pagina.count('class="card pv-cliente"'), 1)
        self.assertEqual(pagina.count('class="pv-btn s-'), 3)
        for colore in ("s-verde", "s-arancio", "s-rosso"):
            self.assertIn(f"pv-btn {colore}", pagina)
        self.assertIn("Sospeso", pagina)

    def test_17_radiografie_vecchie_conservano_le_domande(self):
        with m.app.app_context():
            u = m.Utente.query.filter_by(email="marco@test.it").first()
            v = m.Valutazione(utente_id=u.id, studio="Studio Storico", risposte="{}", punteggi="{}")
            m.db.session.add(v)
            m.db.session.commit()
            vid = v.id
            m.fissa_questionario_radiografie()
            v = m.db.session.get(m.Valutazione, vid)
            self.assertEqual(json.loads(v.questionario), m.AREE_INIZIALI)


if __name__ == "__main__":
    unittest.main(verbosity=2)
