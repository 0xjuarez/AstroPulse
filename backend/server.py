#!/usr/bin/env python3
"""
AstroPulse backend v2 — standard-library only.

No external dependencies. Python 3.11+.

Run:
    python3 backend/server.py
    # Frontend + API at http://localhost:8000

    python3 -m unittest discover -s backend -v   # tests (temp DB, own port)

What it does:
  - Serves the AstroPulse frontend (index.html) at /
  - Stores operators (crew), sections, heart-rate readings, mood
    check-ins and crew actions in a local SQLite database
    (astropulse.db, created on first run, never committed to git)
  - Computes each astronaut's own 7-day personal baseline
    (mean +/- standard deviation of resting heart rate)
  - Evaluates the deterministic rules R1-R5 and returns a status:
    GREEN / AMBER / RED / STALE. It never returns GREEN when there
    is no recent data (R4).
  - Validates every input (ranges for all six challenge indicators:
    heart rate, blood pressure, blood glucose, temperature, sleep,
    mood) and returns structured JSON errors.

This is a prototype for the NASA Space Apps Challenge 2026.
It is not a medical device, it does not diagnose, and it does not
replace a flight surgeon. Demo data inserted with /api/seed is
synthetic and labelled as such.
"""

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

VERSION = "2.0.0"
STARTED_AT = time.time()

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
BP_SYS_AMBER = 130                 # systolic >= 130 -> AMBER
BP_SYS_RED = 140                   # systolic >= 140 -> RED
GLUCOSE_LOW = 70                   # mg/dL, outside 70-140 -> AMBER
GLUCOSE_HIGH = 140
TEMP_HIGH = 37.3                   # deg C, >= 37.3 -> AMBER

MAX_BODY_BYTES = 64 * 1024         # reject absurd payloads

# Default crew (synthetic demo personas, labelled as such on seed).
DEFAULT_OPERATORS = [
    {"crew_id": "APX-01", "name": "E. Vasquez", "role": "Commander", "status": "NOMINAL", "baseline_hr_bpm": 68},
    {"crew_id": "APX-02", "name": "A. Reyes", "role": "Pilot", "status": "NOMINAL", "baseline_hr_bpm": 66},
    {"crew_id": "APX-03", "name": "K. Tanaka", "role": "Science Officer", "status": "WATCH", "baseline_hr_bpm": 70},
    {"crew_id": "APX-04", "name": "D. Moreau", "role": "Flight Engineer", "status": "NOMINAL", "baseline_hr_bpm": 64},
]

# Core sections of the console (built-in; title can be renamed, never deleted).
CORE_SECTIONS = [
    ("crew", "Crew", "Crew roster and per-astronaut status."),
    ("verdict", "01 · Verdict", "Am I OK today — for me?"),
    ("indicators", "02 · Indicators", "The six challenge indicators, colour-coded at a glance."),
    ("body", "03 · Body", "Clickable human figure: function and status per body part."),
    ("charts", "04 · Charts", "Live HR + ECG and the 7-day trend."),
    ("guidance", "05 · Guidance", "Treatment guidance and mission-routine prompts."),
    ("checkinPanel", "Check-In", "Daily 30-second subjective check-in."),
    ("rules", "06 · Rules", "Decision rules R1–R5 with live state."),
    ("alerts", "07 · Alerts", "Alerts and the live SYS-LOG."),
    ("context", "Context", "Mission context: RIDGE hazards and habitat."),
    ("station", "08 · Station", "Station schematic."),
    ("system", "System", "Pipeline, outbox and exports."),
    ("references", "09 · References", "NASA data and space-agency partner resources."),
]

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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


def slugify(title):
    """Title -> URL slug ('Mi Sección' -> 'mi-seccion')."""
    import unicodedata
    text = unicodedata.normalize("NFKD", str(title or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "section"


class ApiError(Exception):
    """Structured API error: message + HTTP status + optional field errors."""

    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.fields = fields or {}


def _num(data, field, minimum, maximum, required=False):
    """Validate one numeric field. Returns float/None, raises ApiError."""
    value = data.get(field)
    if value is None:
        if required:
            raise ApiError(f"{field} is required", 400, {field: "required"})
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ApiError(f"{field} must be a number", 400, {field: "must be a number"})
    if not (minimum <= value <= maximum):
        raise ApiError(
            f"{field} must be between {minimum} and {maximum}",
            400, {field: f"out of range {minimum}-{maximum}"},
        )
    return value


def _int_1_5(data, field, required=False):
    value = data.get(field)
    if value is None:
        if required:
            raise ApiError(f"{field} (1-5) is required", 400, {field: "required"})
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ApiError(f"{field} must be an integer 1-5", 400, {field: "must be 1-5"})
    if not 1 <= value <= 5:
        raise ApiError(f"{field} must be between 1 and 5", 400, {field: "must be 1-5"})
    return value


def _text(data, field, required=False, max_len=500):
    value = data.get(field)
    if value is None:
        if required:
            raise ApiError(f"{field} is required", 400, {field: "required"})
        return None
    value = str(value).strip()
    if required and not value:
        raise ApiError(f"{field} is required", 400, {field: "required"})
    if len(value) > max_len:
        raise ApiError(f"{field} is too long (max {max_len} chars)", 400, {field: "too long"})
    return value or None


# ---------------------------------------------------------------- DB ----

def get_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS operators (
            crew_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'NOMINAL',
            baseline_hr_bpm REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sections (
            slug TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            built_in INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            astronaut_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            hr_bpm REAL,
            hrv_ms REAL,
            spo2 REAL,
            temp_c REAL,
            sleep_h REAL,
            bp_sys INTEGER,
            bp_dia INTEGER,
            glucose_mg_dl REAL,
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
    # Migrations for databases created by v1 (no bp/glucose columns).
    cols = {r[1] for r in conn.execute("PRAGMA table_info(readings)")}
    for col, ddl in (
        ("bp_sys", "ALTER TABLE readings ADD COLUMN bp_sys INTEGER"),
        ("bp_dia", "ALTER TABLE readings ADD COLUMN bp_dia INTEGER"),
        ("glucose_mg_dl", "ALTER TABLE readings ADD COLUMN glucose_mg_dl REAL"),
    ):
        if col not in cols:
            conn.execute(ddl)
    conn.commit()
    return conn


def ensure_core_sections(conn):
    for slug, title, content in CORE_SECTIONS:
        conn.execute(
            "INSERT OR IGNORE INTO sections (slug, title, content, built_in, created_at, updated_at)"
            " VALUES (?, ?, ?, 1, ?, ?)",
            (slug, title, content, now_iso(), now_iso()),
        )
    conn.commit()


def seed_operators(conn):
    for op in DEFAULT_OPERATORS:
        conn.execute(
            "INSERT OR IGNORE INTO operators (crew_id, name, role, status, baseline_hr_bpm, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (op["crew_id"], op["name"], op["role"], op["status"], op["baseline_hr_bpm"], now_iso(), now_iso()),
        )
    conn.commit()


# ------------------------------------------------------------- rules ----

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
    sd = math.sqrt(var)
    return {
        "n": len(values),
        "days": BASELINE_DAYS,
        "mean_hr_bpm": round(mean, 1),
        "sd_hr_bpm": round(sd, 1),
        "alert_hr_bpm": round(mean + 2 * sd, 1),  # mean + 2 SD
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
    """Rules R1-R5 (+ vitals). Returns status, rules fired, one action."""
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
    temp = reading.get("temp_c")
    bp_sys = reading.get("bp_sys")
    glucose = reading.get("glucose_mg_dl")
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

    # Blood pressure (challenge indicator)
    if bp_sys is not None and bp_sys >= BP_SYS_RED:
        rules.append("R3")
        status = "RED"
        reasons.append(f"Systolic blood pressure {bp_sys} mmHg is {BP_SYS_RED} or higher.")
    elif bp_sys is not None and bp_sys >= BP_SYS_AMBER:
        rules.append("R3")
        if status != "RED":
            status = "AMBER"
        reasons.append(f"Systolic blood pressure {bp_sys} mmHg is {BP_SYS_AMBER} or higher.")

    # Blood glucose (challenge indicator, mg/dL)
    if glucose is not None and (glucose < GLUCOSE_LOW or glucose > GLUCOSE_HIGH):
        rules.append("R3")
        if status != "RED":
            status = "AMBER"
        reasons.append(f"Blood glucose {glucose} mg/dL is outside the usual range {GLUCOSE_LOW}-{GLUCOSE_HIGH}.")

    # Temperature (challenge indicator)
    if temp is not None and temp >= TEMP_HIGH:
        rules.append("R3")
        if status != "RED":
            status = "AMBER"
        reasons.append(f"Body temperature {temp} C is {TEMP_HIGH} C or higher.")

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


def trends(conn, astronaut_id, days=7):
    """Daily aggregates for the charts: mean HR, mood, readings per day."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT substr(ts, 1, 10) AS day, AVG(hr_bpm) AS mean_hr, MIN(hr_bpm) AS min_hr,"
        " MAX(hr_bpm) AS max_hr, COUNT(*) AS n FROM readings"
        " WHERE astronaut_id = ? AND ts >= ? GROUP BY day ORDER BY day",
        (astronaut_id, since),
    ).fetchall()
    out = []
    for r in rows:
        mood = conn.execute(
            "SELECT AVG(mood) AS mean_mood FROM checkins WHERE astronaut_id = ? AND substr(ts, 1, 10) = ?",
            (astronaut_id, r["day"]),
        ).fetchone()
        out.append({
            "day": r["day"],
            "mean_hr_bpm": round(r["mean_hr"], 1) if r["mean_hr"] is not None else None,
            "min_hr_bpm": r["min_hr"],
            "max_hr_bpm": r["max_hr"],
            "mean_mood": round(mood["mean_mood"], 1) if mood["mean_mood"] is not None else None,
            "readings": r["n"],
        })
    return out


# ------------------------------------------------------------ handler ----

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

    def _send_error(self, err):
        payload = {"error": err.message}
        if err.fields:
            payload["fields"] = err.fields
        self._send_json(err.status, payload)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ApiError("request body too large", 413)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError("invalid JSON body", 400)
        if not isinstance(data, dict):
            raise ApiError("JSON body must be an object", 400)
        return data

    def _conn(self):
        conn = get_db(self.db_path)
        ensure_core_sections(conn)
        return conn

    def log_message(self, fmt, *args):  # keep the console readable
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # --- routing -----------------------------------------------------
    def _route(self, method):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        parts = [p for p in path.split("/") if p]

        if path in ("/", "/index.html") and method == "GET":
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

        if parts[:1] != ["api"]:
            self._send_json(404, {"error": "not found", "path": path})
            return

        conn = self._conn()
        try:
            self._api(conn, method, parts[1:], query)
        except ApiError as err:
            self._send_error(err)
        except Exception as err:  # never leak a stack trace to the client
            sys.stderr.write(f"API error on {method} {path}: {err!r}\n")
            self._send_json(500, {"error": "internal error"})
        finally:
            conn.close()

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")

    # --- API ---------------------------------------------------------
    def _api(self, conn, method, parts, query):
        def q(name, default=None):
            return query.get(name, [default])[0]

        # -- health ---------------------------------------------------
        if parts == ["health"] and method == "GET":
            counts = {
                "operators": conn.execute("SELECT COUNT(*) FROM operators").fetchone()[0],
                "sections": conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0],
                "readings": conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0],
                "checkins": conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0],
            }
            self._send_json(200, {
                "ok": True, "service": "astropulse", "version": VERSION,
                "time": now_iso(), "uptime_s": int(time.time() - STARTED_AT),
                "counts": counts,
            })
            return

        # -- operators ------------------------------------------------
        if parts[:1] == ["operators"]:
            if len(parts) == 1 and method == "GET":
                rows = conn.execute("SELECT * FROM operators ORDER BY crew_id").fetchall()
                self._send_json(200, [dict(r) for r in rows])
                return
            if len(parts) == 1 and method == "POST":
                data = self._read_json()
                crew_id = _text(data, "crew_id", required=True, max_len=20)
                if not SLUG_RE.match(crew_id.lower().replace("_", "-")) and not re.match(r"^[A-Za-z0-9_-]+$", crew_id):
                    raise ApiError("crew_id must be letters, digits, - or _", 400, {"crew_id": "bad format"})
                exists = conn.execute("SELECT 1 FROM operators WHERE crew_id = ?", (crew_id,)).fetchone()
                if exists:
                    raise ApiError(f"operator {crew_id} already exists", 409, {"crew_id": "duplicate"})
                status = _text(data, "status") or "NOMINAL"
                if status not in ("NOMINAL", "WATCH", "RED", "STALE"):
                    raise ApiError("status must be NOMINAL, WATCH, RED or STALE", 400, {"status": "invalid"})
                now = now_iso()
                conn.execute(
                    "INSERT INTO operators (crew_id, name, role, status, baseline_hr_bpm, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (crew_id, _text(data, "name", required=True, max_len=100),
                     _text(data, "role", required=True, max_len=100), status,
                     _num(data, "baseline_hr_bpm", 30, 220), now, now),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM operators WHERE crew_id = ?", (crew_id,)).fetchone()
                self._send_json(201, dict(row))
                return
            if len(parts) == 2 and method in ("GET", "PUT", "DELETE"):
                crew_id = parts[1]
                row = conn.execute("SELECT * FROM operators WHERE crew_id = ?", (crew_id,)).fetchone()
                if not row:
                    raise ApiError(f"operator {crew_id} not found", 404)
                if method == "GET":
                    self._send_json(200, dict(row))
                    return
                if method == "DELETE":
                    conn.execute("DELETE FROM operators WHERE crew_id = ?", (crew_id,))
                    conn.commit()
                    self._send_json(200, {"deleted": crew_id})
                    return
                data = self._read_json()
                status = data.get("status", row["status"])
                if status not in ("NOMINAL", "WATCH", "RED", "STALE"):
                    raise ApiError("status must be NOMINAL, WATCH, RED or STALE", 400, {"status": "invalid"})
                conn.execute(
                    "UPDATE operators SET name = ?, role = ?, status = ?, baseline_hr_bpm = ?, updated_at = ?"
                    " WHERE crew_id = ?",
                    (_text(data, "name") or row["name"], _text(data, "role") or row["role"],
                     status, _num(data, "baseline_hr_bpm", 30, 220) or row["baseline_hr_bpm"],
                     now_iso(), crew_id),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM operators WHERE crew_id = ?", (crew_id,)).fetchone()
                self._send_json(200, dict(row))
                return

        # -- crew overview (all operators + live status) --------------
        if parts == ["crew"] and method == "GET":
            rows = conn.execute("SELECT * FROM operators ORDER BY crew_id").fetchall()
            out = []
            for r in rows:
                op = dict(r)
                op["live"] = evaluate(conn, r["crew_id"])
                out.append(op)
            self._send_json(200, out)
            return

        # -- sections -------------------------------------------------
        if parts[:1] == ["sections"]:
            if len(parts) == 1 and method == "GET":
                rows = conn.execute("SELECT * FROM sections ORDER BY built_in DESC, slug").fetchall()
                self._send_json(200, [dict(r) for r in rows])
                return
            if len(parts) == 1 and method == "POST":
                data = self._read_json()
                title = _text(data, "title", required=True, max_len=120)
                slug = _text(data, "slug") or slugify(title)
                if not SLUG_RE.match(slug):
                    raise ApiError("slug must be lowercase letters, digits and dashes", 400, {"slug": "bad format"})
                exists = conn.execute("SELECT 1 FROM sections WHERE slug = ?", (slug,)).fetchone()
                if exists:
                    raise ApiError(f"section /{slug} already exists", 409, {"slug": "duplicate"})
                now = now_iso()
                conn.execute(
                    "INSERT INTO sections (slug, title, content, built_in, created_at, updated_at)"
                    " VALUES (?, ?, ?, 0, ?, ?)",
                    (slug, title, _text(data, "content", max_len=5000) or "", now, now),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM sections WHERE slug = ?", (slug,)).fetchone()
                self._send_json(201, dict(row))
                return
            if len(parts) == 2 and method in ("GET", "PUT", "DELETE"):
                slug = parts[1]
                row = conn.execute("SELECT * FROM sections WHERE slug = ?", (slug,)).fetchone()
                if not row:
                    raise ApiError(f"section /{slug} not found", 404)
                if method == "GET":
                    self._send_json(200, dict(row))
                    return
                if method == "DELETE":
                    if row["built_in"]:
                        raise ApiError("built-in sections cannot be deleted, only renamed", 400)
                    conn.execute("DELETE FROM sections WHERE slug = ?", (slug,))
                    conn.commit()
                    self._send_json(200, {"deleted": slug})
                    return
                data = self._read_json()
                conn.execute(
                    "UPDATE sections SET title = ?, content = ?, updated_at = ? WHERE slug = ?",
                    (_text(data, "title", max_len=120) or row["title"],
                     _text(data, "content", max_len=5000) if data.get("content") is not None else row["content"],
                     now_iso(), slug),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM sections WHERE slug = ?", (slug,)).fetchone()
                self._send_json(200, dict(row))
                return

        astronaut_id = q("astronaut_id", "APX-01")

        # -- status / baseline / trends / alerts ----------------------
        if parts == ["status"] and method == "GET":
            self._send_json(200, evaluate(conn, astronaut_id))
            return
        if parts == ["baseline"] and method == "GET":
            self._send_json(200, {"astronaut_id": astronaut_id, "baseline": baseline(conn, astronaut_id)})
            return
        if parts == ["trends"] and method == "GET":
            days = int(q("days", 7))
            days = max(1, min(days, 30))
            self._send_json(200, {"astronaut_id": astronaut_id, "days": days, "trend": trends(conn, astronaut_id, days)})
            return
        if parts == ["alerts"] and method == "GET":
            alerts = []
            for r in conn.execute("SELECT crew_id, name FROM operators ORDER BY crew_id").fetchall():
                ev = evaluate(conn, r["crew_id"])
                if ev["status"] in ("AMBER", "RED", "STALE"):
                    alerts.append({
                        "astronaut_id": r["crew_id"], "name": r["name"],
                        "status": ev["status"], "rules_fired": ev["rules_fired"],
                        "reason": ev["reason"], "recommended_action": ev["recommended_action"],
                        "latest_reading": ev["latest_reading"],
                    })
            severity = {"RED": 0, "AMBER": 1, "STALE": 2}
            alerts.sort(key=lambda a: severity.get(a["status"], 3))
            self._send_json(200, alerts)
            return

        # -- readings / checkins / events -----------------------------
        if parts == ["readings"] and method == "GET":
            limit = int(q("limit", 100))
            since = q("since")
            sql = "SELECT * FROM readings WHERE astronaut_id = ?"
            args = [astronaut_id]
            if since:
                sql += " AND ts >= ?"
                args.append(parse_ts(since))
            sql += " ORDER BY ts DESC LIMIT ?"
            args.append(max(1, min(limit, 500)))
            rows = conn.execute(sql, args).fetchall()
            self._send_json(200, [dict(r) for r in rows])
            return
        if parts == ["checkins"] and method == "GET":
            rows = conn.execute(
                "SELECT * FROM checkins WHERE astronaut_id = ? ORDER BY ts DESC LIMIT 50",
                (astronaut_id,),
            ).fetchall()
            self._send_json(200, [dict(r) for r in rows])
            return
        if parts == ["events"] and method == "GET":
            rows = conn.execute(
                "SELECT * FROM actions WHERE astronaut_id = ? ORDER BY ts DESC LIMIT 50",
                (astronaut_id,),
            ).fetchall()
            self._send_json(200, [dict(r) for r in rows])
            return

        # -- export ---------------------------------------------------
        if parts == ["export"] and method == "GET":
            dump = {}
            for table in ("operators", "sections", "readings", "checkins", "actions"):
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                dump[table] = [dict(r) for r in rows]
            dump["meta"] = {"service": "astropulse", "version": VERSION, "exported_at": now_iso()}
            self._send_json(200, dump)
            return

        # -- writes ---------------------------------------------------
        if method == "POST" and parts == ["readings"]:
            data = self._read_json()
            astronaut_id = _text(data, "astronaut_id") or "APX-01"
            hr = _num(data, "hr_bpm", 30, 220, required=True)
            cur = conn.execute(
                "INSERT INTO readings (astronaut_id, ts, hr_bpm, hrv_ms, spo2, temp_c, sleep_h,"
                " bp_sys, bp_dia, glucose_mg_dl, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (astronaut_id, parse_ts(data.get("ts")), hr,
                 _num(data, "hrv_ms", 0, 300), _num(data, "spo2", 70, 100),
                 _num(data, "temp_c", 34, 42), _num(data, "sleep_h", 0, 24),
                 _num(data, "bp_sys", 60, 250), _num(data, "bp_dia", 30, 160),
                 _num(data, "glucose_mg_dl", 40, 400),
                 _text(data, "source", max_len=40) or "manual", now_iso()),
            )
            conn.commit()
            self._send_json(201, {"id": cur.lastrowid, "status": evaluate(conn, astronaut_id)})
            return
        if method == "POST" and parts == ["checkin"]:
            data = self._read_json()
            astronaut_id = _text(data, "astronaut_id") or "APX-01"
            mood = _int_1_5(data, "mood", required=True)
            cur = conn.execute(
                "INSERT INTO checkins (astronaut_id, ts, mood, energy, stress, sleep_quality, note, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (astronaut_id, parse_ts(data.get("ts")), mood,
                 _int_1_5(data, "energy"), _int_1_5(data, "stress"),
                 _int_1_5(data, "sleep_quality"), _text(data, "note", max_len=500), now_iso()),
            )
            conn.commit()
            self._send_json(201, {"id": cur.lastrowid, "status": evaluate(conn, astronaut_id)})
            return
        if method == "POST" and parts == ["actions"]:
            data = self._read_json()
            astronaut_id = _text(data, "astronaut_id") or "APX-01"
            action = _text(data, "action", required=True, max_len=500)
            cur = conn.execute(
                "INSERT INTO actions (astronaut_id, ts, rule_id, action, status, note, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (astronaut_id, parse_ts(data.get("ts")), _text(data, "rule_id", max_len=20),
                 action, _text(data, "status", max_len=20) or "logged",
                 _text(data, "note", max_len=500), now_iso()),
            )
            conn.commit()
            self._send_json(201, {"id": cur.lastrowid})
            return
        if method == "POST" and parts == ["seed"]:
            data = self._read_json()
            astronaut_id = _text(data, "astronaut_id") or "APX-01"
            base_hr = _num(data, "base_hr_bpm", 30, 220) or 68
            seed_operators(conn)
            count = 0
            start = datetime.now(timezone.utc) - timedelta(days=7)
            for day in range(7):
                for hour in (8, 12, 18, 22):
                    ts = (start + timedelta(days=day, hours=hour)).isoformat()
                    hr = base_hr + ((day * 7 + hour) % 9) - 4  # 64-72, deterministic
                    conn.execute(
                        "INSERT INTO readings (astronaut_id, ts, hr_bpm, hrv_ms, spo2, temp_c, sleep_h,"
                        " bp_sys, bp_dia, glucose_mg_dl, source, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (astronaut_id, ts, hr, 42, 98, 36.6, 7.5, 118, 76, 94, "synthetic-seed", now_iso()),
                    )
                    count += 1
            conn.commit()
            self._send_json(201, {"inserted": count, "astronaut_id": astronaut_id,
                                  "operators_seeded": len(DEFAULT_OPERATORS),
                                  "note": "synthetic demo data"})
            return

        self._send_json(404, {"error": "not found", "path": "/" + "/".join(parts)})


def main():
    parser = argparse.ArgumentParser(description="AstroPulse backend v2 (stdlib only)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()

    Handler.db_path = Path(args.db)
    conn = get_db(Handler.db_path)
    ensure_core_sections(conn)
    seed_operators(conn)  # default synthetic crew (APX-01..APX-04), unless already there
    conn.close()  # create tables on start
    print(f"AstroPulse backend v{VERSION} running at http://{args.host}:{args.port}")
    print(f"Database: {Handler.db_path}")
    print("Frontend: http://127.0.0.1:8000/  (add --host 0.0.0.0 to share on your network)")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
