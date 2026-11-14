"""Tests for the AstroPulse backend (stdlib only).

Run:  python3 -m unittest discover -s backend -v

Each test case starts the real server on an ephemeral port with a
fresh temporary SQLite database, and talks to it over HTTP.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.server import Handler, get_db  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402


def call(port, method, path, body=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        cls.db_path = tmp.name
        Handler.db_path = cls.db_path
        get_db(cls.db_path).close()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        os.unlink(cls.db_path)

    def test_health(self):
        status, body = call(self.port, "GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["version"], "2.0.0")
        self.assertIn("counts", body)

    def test_seed_and_red_status(self):
        # Seed 7 days of synthetic baseline for APX-01 (baseline ~68).
        status, body = call(self.port, "POST", "/api/seed",
                            {"astronaut_id": "APX-07", "base_hr_bpm": 68})
        self.assertEqual(status, 201)
        self.assertEqual(body["inserted"], 28)
        self.assertEqual(body["operators_seeded"], 4)

        # High heart rate -> AMBER (R1).
        status, body = call(self.port, "POST", "/api/readings",
                            {"astronaut_id": "APX-07", "hr_bpm": 79, "hrv_ms": 38, "spo2": 98})
        self.assertEqual(status, 201)
        self.assertEqual(body["status"]["status"], "AMBER")
        self.assertIn("R1", body["status"]["rules_fired"])

        # Low mood on top -> RED (R1 + R5 + R2).
        status, body = call(self.port, "POST", "/api/checkin",
                            {"astronaut_id": "APX-07", "mood": 2, "energy": 2,
                             "stress": 4, "sleep_quality": 2})
        self.assertEqual(status, 201)
        self.assertEqual(body["status"]["status"], "RED")
        self.assertIn("R2", body["status"]["rules_fired"])

        # Baseline: mean ~68, alert line ~ mean + 2 SD.
        status, body = call(self.port, "GET", "/api/baseline?astronaut_id=APX-07")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(body["baseline"]["n"], 28)
        self.assertAlmostEqual(body["baseline"]["mean_hr_bpm"], 68, delta=2)

    def test_reading_validation(self):
        # Missing hr_bpm -> 400 with field error.
        status, body = call(self.port, "POST", "/api/readings", {"astronaut_id": "APX-01"})
        self.assertEqual(status, 400)
        self.assertIn("hr_bpm", body.get("fields", {}))

        # Impossible heart rate -> 400.
        status, body = call(self.port, "POST", "/api/readings",
                            {"astronaut_id": "APX-01", "hr_bpm": 400})
        self.assertEqual(status, 400)

        # Mood outside 1-5 -> 400.
        status, body = call(self.port, "POST", "/api/checkin",
                            {"astronaut_id": "APX-01", "mood": 9})
        self.assertEqual(status, 400)

    def test_operators_crud(self):
        status, body = call(self.port, "POST", "/api/operators",
                            {"crew_id": "APX-99", "name": "T. Test", "role": "Medic",
                             "status": "NOMINAL", "baseline_hr_bpm": 62})
        self.assertEqual(status, 201)
        self.assertEqual(body["crew_id"], "APX-99")

        # Duplicate crew_id -> 409.
        status, _ = call(self.port, "POST", "/api/operators",
                         {"crew_id": "APX-99", "name": "Dup", "role": "Medic"})
        self.assertEqual(status, 409)

        # Update status.
        status, body = call(self.port, "PUT", "/api/operators/APX-99", {"status": "WATCH"})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "WATCH")

        # Delete, then 404 on read.
        status, _ = call(self.port, "DELETE", "/api/operators/APX-99")
        self.assertEqual(status, 200)
        status, _ = call(self.port, "GET", "/api/operators/APX-99")
        self.assertEqual(status, 404)

    def test_sections_crud(self):
        status, body = call(self.port, "POST", "/api/sections",
                            {"title": "Mi Sección", "content": "Notas de la misión."})
        self.assertEqual(status, 201)
        self.assertEqual(body["slug"], "mi-seccion")
        self.assertFalse(body["built_in"])

        # Built-in sections cannot be deleted.
        status, body = call(self.port, "DELETE", "/api/sections/verdict")
        self.assertEqual(status, 400)

        # Custom section can be renamed then deleted.
        status, body = call(self.port, "PUT", "/api/sections/mi-seccion",
                            {"title": "Mi Sección 2"})
        self.assertEqual(status, 200)
        self.assertEqual(body["title"], "Mi Sección 2")
        status, _ = call(self.port, "DELETE", "/api/sections/mi-seccion")
        self.assertEqual(status, 200)

    def test_trends_and_export(self):
        status, body = call(self.port, "GET", "/api/trends?astronaut_id=APX-01&days=7")
        self.assertEqual(status, 200)
        self.assertEqual(body["days"], 7)
        self.assertTrue(len(body["trend"]) >= 1)

        status, body = call(self.port, "GET", "/api/export")
        self.assertEqual(status, 200)
        for table in ("operators", "sections", "readings", "checkins", "actions"):
            self.assertIn(table, body)

    def test_alerts(self):
        # Drive APX-01 RED first (seed + high HR + low mood), then check alerts.
        call(self.port, "POST", "/api/seed", {"astronaut_id": "APX-01", "base_hr_bpm": 68})
        call(self.port, "POST", "/api/readings",
             {"astronaut_id": "APX-01", "hr_bpm": 79, "hrv_ms": 38, "spo2": 98})
        call(self.port, "POST", "/api/checkin",
             {"astronaut_id": "APX-01", "mood": 2, "energy": 2, "stress": 4, "sleep_quality": 2})
        status, body = call(self.port, "GET", "/api/alerts")
        self.assertEqual(status, 200)
        self.assertTrue(any(a["astronaut_id"] == "APX-01" and a["status"] == "RED" for a in body))


if __name__ == "__main__":
    unittest.main()
