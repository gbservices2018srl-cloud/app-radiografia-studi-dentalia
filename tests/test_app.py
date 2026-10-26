"""
Test automatici: GitHub li esegue a ogni push (vedi .github/workflows/test.yml).
In locale:  python -m unittest discover -s tests -v
Usano un database SQLite temporaneo, quindi non toccano i dati reali.
"""
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
        r = self.marco.post("/preventivi/nuovo", data=dati)
        pid = int(r.location.rstrip("/").rsplit("/", 1)[1])
        self.marco.post(f"/preventivi/{pid}/duplica")
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
