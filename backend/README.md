# AstroPulse backend v2

Python standard library only. No `pip install` needed. Python 3.11+.

## Run

```bash
python3 backend/server.py
# Frontend + API at http://localhost:8000
```

Options:

```bash
python3 backend/server.py --port 8000 --host 127.0.0.1 --db backend/astropulse.db
```

Use `--host 0.0.0.0` only to share it on your own local network.

The server creates `backend/astropulse.db` (SQLite) on first run. That file is gitignored — it is local data, not code. A database created by v1 is migrated automatically (blood pressure and glucose columns are added).

## Tests

```bash
python3 -m unittest discover -s backend -v
```

The tests start the real server on an ephemeral port with a fresh temporary database and exercise health, seed, the RED status scenario (R1+R5+R2), input validation, operators CRUD, sections CRUD, trends, alerts and export.

## API

Base URL: `http://localhost:8000`. Every error is JSON: `{"error": "...", "fields": {...}}`.

### Health & overview

| Method | Endpoint | What it does |
| --- | --- | --- |
| GET | `/` | Serves the AstroPulse frontend (`index.html`) |
| GET | `/api/health` | `{"ok": true, "version": "2.0.0", "uptime_s": ..., "counts": {...}}` |
| GET | `/api/crew` | All operators, each with its live evaluated status |
| GET | `/api/alerts` | Active AMBER / RED / STALE alerts across the crew, worst first |
| GET | `/api/export` | Full JSON dump: operators, sections, readings, checkins, actions |

### Operators (crew)

| Method | Endpoint | What it does |
| --- | --- | --- |
| GET | `/api/operators` | List all operators |
| POST | `/api/operators` | `{"crew_id","name","role","status","baseline_hr_bpm"}` — 409 on duplicate crew_id |
| GET | `/api/operators/APX-01` | One operator |
| PUT | `/api/operators/APX-01` | Update name, role, status, baseline HR |
| DELETE | `/api/operators/APX-01` | Remove an operator |

Status must be `NOMINAL`, `WATCH`, `RED` or `STALE`. `/api/seed` loads the 4 default synthetic crew members (APX-01 … APX-04).

### Sections

| Method | Endpoint | What it does |
| --- | --- | --- |
| GET | `/api/sections` | List all sections (built-in first) |
| POST | `/api/sections` | `{"title","content","slug?"}` — slug is generated from the title (`"Mi Sección"` → `mi-seccion`); 409 on duplicate slug |
| GET | `/api/sections/verdict` | One section |
| PUT | `/api/sections/mi-seccion` | Rename a section or edit its content |
| DELETE | `/api/sections/mi-seccion` | Remove a custom section (built-in sections cannot be deleted, only renamed) |

### Health data

| Method | Endpoint | What it does |
| --- | --- | --- |
| GET | `/api/status?astronaut_id=APX-01` | GREEN / AMBER / RED / STALE, baseline, rules fired, recommended action |
| GET | `/api/baseline?astronaut_id=APX-01` | 7-day personal baseline: mean HR, SD, alert line (mean + 2 SD) |
| GET | `/api/trends?astronaut_id=APX-01&days=7` | Daily aggregates for the charts: mean/min/max HR, mean mood, readings per day |
| GET | `/api/readings?astronaut_id=APX-01&limit=100&since=...` | Recent readings, newest first |
| GET | `/api/checkins?astronaut_id=APX-01` | Recent mood check-ins |
| GET | `/api/events?astronaut_id=APX-01` | Logged actions |
| POST | `/api/readings` | `{"astronaut_id","hr_bpm","hrv_ms","spo2","temp_c","sleep_h","bp_sys","bp_dia","glucose_mg_dl","source"}` — returns the new status |
| POST | `/api/checkin` | `{"astronaut_id","mood":1-5,"energy","stress","sleep_quality","note"}` — returns the new status |
| POST | `/api/actions` | `{"astronaut_id","rule_id","action","note"}` |
| POST | `/api/seed` | Demo only: 4 synthetic operators + 7 days of **synthetic** baseline readings for one astronaut |

## Validation

All six challenge indicators are validated on write:

| Field | Range |
| --- | --- |
| `hr_bpm` | 30–220 (required for readings) |
| `spo2` | 70–100 % |
| `temp_c` | 34–42 °C |
| `sleep_h` | 0–24 h |
| `bp_sys` / `bp_dia` | 60–250 / 30–160 mmHg |
| `glucose_mg_dl` | 40–400 mg/dL |
| `mood` / `energy` / `stress` / `sleep_quality` | 1–5 |

Out-of-range values return `400` with the offending field named. Request bodies over 64 KB are rejected (`413`).

## Try it

```bash
# 1. Check the server
curl http://localhost:8000/api/health

# 2. Seed 7 days of synthetic baseline data (demo only)
curl -X POST http://localhost:8000/api/seed \
  -H 'Content-Type: application/json' \
  -d '{"astronaut_id":"APX-01","base_hr_bpm":68}'

# 3. Log a reading (today: heart up, plus blood pressure and glucose)
curl -X POST http://localhost:8000/api/readings \
  -H 'Content-Type: application/json' \
  -d '{"astronaut_id":"APX-01","hr_bpm":79,"hrv_ms":38,"spo2":98,"bp_sys":118,"bp_dia":76,"glucose_mg_dl":94}'

# 4. Log a low mood check-in
curl -X POST http://localhost:8000/api/checkin \
  -H 'Content-Type: application/json' \
  -d '{"astronaut_id":"APX-01","mood":2,"energy":2,"stress":4,"sleep_quality":2}'

# 5. Ask: am I OK right now — for me?
curl "http://localhost:8000/api/status?astronaut_id=APX-01"

# 6. Who needs attention right now?
curl http://localhost:8000/api/alerts

# 7. Add an operator and a custom section
curl -X POST http://localhost:8000/api/operators \
  -H 'Content-Type: application/json' \
  -d '{"crew_id":"APX-05","name":"S. Park","role":"Medic","status":"NOMINAL","baseline_hr_bpm":66}'
curl -X POST http://localhost:8000/api/sections \
  -H 'Content-Type: application/json' \
  -d '{"title":"Mi Sección","content":"Notas de la misión."}'
```

Step 5 should return **RED** (rule R2: HR above baseline + 2 SD, plus mood 2/5), with a recommended action.

## Rules (R1–R5, plus vitals)

Implemented in `evaluate()` in `server.py`. See the table in the main `README.md`. The backend never returns GREEN when there is no recent reading (R4, stale after 10 minutes). Blood pressure ≥130/140, glucose outside 70–140 mg/dL and temperature ≥37.3 °C also raise the status, under the same R3 family as SpO2.

## Notes for the team

- The frontend (`index.html`) currently runs standalone with simulated data in the browser. Connecting it to this API is the next step — the API already returns the same status/baseline shape the frontend displays, plus operators and sections matching the Manage pages (localStorage today).
- Do not commit `astropulse.db` or any real health data. For the demo, use `/api/seed` (synthetic) only.
