#!/usr/bin/env python3
"""
AstroPulse backend — basic, standard-library only.

No external dependencies. Python 3.11+.

Run:
    python3 backend/server.py
    # open http://localhost:8000

What it does:
  - Serves the AstroPulse frontend (index.html) at /
  - Stores heart-rate readings, mood check-ins and crew actions
    in a local SQLite database (astropulse.db, created on first run,
    never committed to git)
  - Computes each astronaut's own 7-day personal baseline
    (mean +/- standard deviation of resting heart rate)
  - Evaluates the deterministic rules R1-R5 and returns a status:
    GREEN / AMBER / RED / STALE. It never returns GREEN when there
    is no recent data (R4).

This is a prototype for the NASA Space Apps Challenge 2026.
It is not a medical device, it does not diagnose, and it does not
replace a flight surgeon. Demo data inserted with /api/seed is
synthetic and labelled as such.
"""

import argparse
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "index.html"
DEFAULT_DB = Path(__file__).resolve().parent / "astropulse.db"

# Rule thresholds (see README.md, Rules R1-R5)
STALE_AFTER_SECONDS = 10 * 60      # R4: no reading in 10 minutes -> STALE
BASELINE_DAYS = 7
MIN_BASELINE_READINGS = 10
SPO2_AMBER = 95.0
SPO2_RED = 92.0
MOOD_LOW = 2                       # mood 1-5, <=2 is low


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_ts(value):
    """Parse an ISO timestamp, defaulting to now. Returns ISO string."""
    if not value:
        return now_iso()
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return now_iso()


def get_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            astronaut_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            hr_bpm REAL,
            hrv_ms REAL,
            spo2 REAL,
            temp_c REAL,
            sleep_h REAL,
            source TEXT DEFAULT 'manual',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            astronaut_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            mood INTEGER,
            energy INTEGER,
            stress INTEGER,
            sleep_quality INTEGER,
            note TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            astronaut_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            rule_id TEXT,
            action TEXT NOT NULL,
            status TEXT DEFAULT 'logged',
            note TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    return conn


def baseline(conn, astronaut_id):
    """Personal 7-day baseline for one astronaut, or None."""
    since = (datetime.now(timezone.utc) - timedelta(days=BASELINE_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT hr_bpm FROM readings WHERE astronaut_id = ? AND ts >= ? AND hr_bpm IS NOT NULL",
        (astronaut_id, since),
    ).fetchall()
    values = [r["hr_bpm"] for r in rows]
    if len(values) < MIN_BASELINE_READINGS:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return {
        "n": len(values),
        "days": BASELINE_DAYS,
        "mean_hr_bpm": round(mean, 1),
        "sd_hr_bpm": round(math.sqrt(var), 1),
        "alert_hr_bpm": round(mean + 2 * math.sqrt(var), 1),  # mean + 2 SD
    }


def latest_reading(conn, astronaut_id):
    row = conn.execute(
        "SELECT * FROM readings WHERE astronaut_id = ? ORDER BY ts DESC LIMIT 1",
        (astronaut_id,),
    ).fetchone()
    return dict(row) if row else None


def latest_checkin(conn, astronaut_id):
    row = conn.execute(
        "SELECT * FROM checkins WHERE astronaut_id = ? ORDER BY ts DESC LIMIT 1",
        (astronaut_id,),
    ).fetchone()
    return dict(row) if row else None


def evaluate(conn, astronaut_id):
    """Rules R1-R5. Returns status, rules fired and one recommended action."""
    base = baseline(conn, astronaut_id)
    reading = latest_reading(conn, astronaut_id)
    checkin = latest_checkin(conn, astronaut_id)

    if reading is None:
        return {
            "astronaut_id": astronaut_id,
            "status": "STALE",
            "baseline": base,
            "latest_reading": None,
            "latest_checkin": checkin,
            "rules_fired": ["R4"],
            "reason": "No readings yet. Never GREEN on missing data.",
            "recommended_action": "Check the sensor link and log a manual reading.",
        }

    # R4: stale telemetry
    last_ts = datetime.fromisoformat(reading["ts"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - last_ts).total_seconds()
    if age > STALE_AFTER_SECONDS:
        return {
            "astronaut_id": astronaut_id,
            "status": "STALE",
            "baseline": base,
            "latest_reading": reading,
            "latest_checkin": checkin,
            "rules_fired": ["R4"],
            "reason": f"Last reading is {int(age // 60)} min old. Never GREEN on missing data.",
            "recommended_action": "Restore the telemetry link; do not clear the alert until fresh data arrives.",
        }

    rules = []
    status = "GREEN"
    reasons = []

    hr = reading.get("hr_bpm")
    spo2 = reading.get("spo2")
    mood = checkin.get("mood") if checkin else None

    # R1: resting HR above personal baseline + 2 SD
    hr_high = bool(base and hr is not None and hr > base["alert_hr_bpm"])
    if hr_high:
        rules.append("R1")
        status = "AMBER"
        reasons.append(
            f"Heart rate {hr} bpm is above your usual alert line "
            f"({base['alert_hr_bpm']} bpm = your 7-day mean + 2 SD)."
        )

    # R3: low SpO2
    if spo2 is not None and spo2 < SPO2_RED:
        rules.append("R3")
        status = "RED"
        reasons.append(f"SpO2 {spo2}% is below {SPO2_RED}%.")
    elif spo2 is not None and spo2 < SPO2_AMBER:
        rules.append("R3")
        if status != "RED":
            status = "AMBER"
        reasons.append(f"SpO2 {spo2}% is below {SPO2_AMBER}%.")

    # R5 / R2: low mood, alone or combined with elevated HR
    if mood is not None and mood <= MOOD_LOW:
        rules.append("R5")
        if hr_high:
            rules.append("R2")
            status = "RED"
            reasons.append(f"Mood {mood}/5 is low and heart rate is elevated.")
        else:
            if status != "RED":
                status = "AMBER"
            reasons.append(f"Mood {mood}/5 is low.")

    if status == "GREEN":
        reasons.append("Heart rate and mood are inside your own 7-day baseline.")
        action = "Continue normal duties. Next check-in in the morning."
    elif status == "AMBER":
        action = "Rest, do a 5-minute breathing exercise, drink water, log what changed."
    else:  # RED
        action = "Stop strenuous activity, rest, and notify the flight surgeon (queued if offline)."

    return {
        "astronaut_id": astronaut_id,
        "status": status,
        "baseline": base,
        "latest_reading": reading,
        "latest_checkin": checkin,
        "rules_fired": rules,
        "reason": " ".join(reasons),
        "recommended_action": action,
    }


class Handler(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB

    # --- helpers -----------------------------------------------------
    def _send_json(self, status_code, payload):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _conn(self):
        return get_db(self.db_path)

    def log_message(self, fmt, *args):  # keep the console readable
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # --- routes ------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            if not INDEX_HTML.exists():
                self._send_json(404, {"error": "index.html not found"})
                return
            body = INDEX_HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/health":
            self._send_json(200, {"ok": True, "service": "astropulse", "time": now_iso()})
            return

        conn = self._conn()
        try:
            astronaut_id = query.get("astronaut_id", ["crew-01"])[0]

            if path == "/api/status":
                self._send_json(200, evaluate(conn, astronaut_id))
            elif path == "/api/baseline":
                self._send_json(200, {"astronaut_id": astronaut_id, "baseline": baseline(conn, astronaut_id)})
            elif path == "/api/readings":
                limit = int(query.get("limit", ["100"])[0])
                rows = conn.execute(
                    "SELECT * FROM readings WHERE astronaut_id = ? ORDER BY ts DESC LIMIT ?",
                    (astronaut_id, max(1, min(limit, 500))),
                ).fetchall()
                self._send_json(200, [dict(r) for r in rows])
            elif path == "/api/checkins":
                rows = conn.execute(
                    "SELECT * FROM checkins WHERE astronaut_id = ? ORDER BY ts DESC LIMIT 50",
                    (astronaut_id,),
                ).fetchall()
                self._send_json(200, [dict(r) for r in rows])
            elif path == "/api/events":
                rows = conn.execute(
                    "SELECT * FROM actions WHERE astronaut_id = ? ORDER BY ts DESC LIMIT 50",
                    (astronaut_id,),
                ).fetchall()
                self._send_json(200, [dict(r) for r in rows])
            else:
                self._send_json(404, {"error": "not found", "path": path})
        finally:
            conn.close()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        conn = self._conn()
        try:
            if path == "/api/readings":
                astronaut_id = str(data.get("astronaut_id") or "crew-01")
                hr = data.get("hr_bpm")
                if hr is None:
                    self._send_json(400, {"error": "hr_bpm is required"})
                    return
                ts = parse_ts(data.get("ts"))
                cur = conn.execute(
                    "INSERT INTO readings (astronaut_id, ts, hr_bpm, hrv_ms, spo2, temp_c, sleep_h, source, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (astronaut_id, ts, hr, data.get("hrv_ms"), data.get("spo2"),
                     data.get("temp_c"), data.get("sleep_h"), data.get("source", "manual"), now_iso()),
                )
                conn.commit()
                self._send_json(201, {"id": cur.lastrowid, "status": evaluate(conn, astronaut_id)})
            elif path == "/api/checkin":
                astronaut_id = str(data.get("astronaut_id") or "crew-01")
                mood = data.get("mood")
                if mood is None or not 1 <= int(mood) <= 5:
                    self._send_json(400, {"error": "mood (1-5) is required"})
                    return
                ts = parse_ts(data.get("ts"))
                cur = conn.execute(
                    "INSERT INTO checkins (astronaut_id, ts, mood, energy, stress, sleep_quality, note, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (astronaut_id, ts, int(mood), data.get("energy"), data.get("stress"),
                     data.get("sleep_quality"), data.get("note"), now_iso()),
                )
                conn.commit()
                self._send_json(201, {"id": cur.lastrowid, "status": evaluate(conn, astronaut_id)})
            elif path == "/api/actions":
                astronaut_id = str(data.get("astronaut_id") or "crew-01")
                action = data.get("action")
                if not action:
                    self._send_json(400, {"error": "action is required"})
                    return
                ts = parse_ts(data.get("ts"))
                cur = conn.execute(
                    "INSERT INTO actions (astronaut_id, ts, rule_id, action, status, note, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (astronaut_id, ts, data.get("rule_id"), action,
                     data.get("status", "logged"), data.get("note"), now_iso()),
                )
                conn.commit()
                self._send_json(201, {"id": cur.lastrowid})
            elif path == "/api/seed":
                # Demo only: 7 days of synthetic baseline readings, labelled synthetic.
                astronaut_id = str(data.get("astronaut_id") or "crew-01")
                base_hr = float(data.get("base_hr_bpm", 68))
                count = 0
                start = datetime.now(timezone.utc) - timedelta(days=7)
                for day in range(7):
                    for hour in (8, 12, 18, 22):
                        ts = (start + timedelta(days=day, hours=hour)).isoformat()
                        hr = base_hr + ((day * 7 + hour) % 9) - 4  # 64-72, deterministic
                        conn.execute(
                            "INSERT INTO readings (astronaut_id, ts, hr_bpm, hrv_ms, spo2, temp_c, sleep_h, source, created_at)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (astronaut_id, ts, hr, 42, 98, 36.6, 7.5, "synthetic-seed", now_iso()),
                        )
                        count += 1
                conn.commit()
                self._send_json(201, {"inserted": count, "astronaut_id": astronaut_id, "note": "synthetic demo data"})
            else:
                self._send_json(404, {"error": "not found", "path": path})
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="AstroPulse backend (stdlib only)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()

    Handler.db_path = Path(args.db)
    get_db(Handler.db_path).close()  # create tables on start
    print(f"AstroPulse backend running at http://{args.host}:{args.port}")
    print(f"Database: {Handler.db_path}")
    print("Frontend: http://127.0.0.1:8000/  (add --host 0.0.0.0 to share on your network)")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
