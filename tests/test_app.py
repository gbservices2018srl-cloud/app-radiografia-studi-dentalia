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

    def test_10_listino_iniziale(self):
        with m.app.app_context():
            self.assertGreater(m.Servizio.query.count(), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
