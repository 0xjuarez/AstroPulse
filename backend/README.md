# AstroPulse backend — basic

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

The server creates `backend/astropulse.db` (SQLite) on first run. That file is gitignored — it is local data, not code.

## API

Base URL: `http://localhost:8000`

| Method | Endpoint | What it does |
| --- | --- | --- |
| GET | `/` | Serves the AstroPulse frontend (`index.html`) |
| GET | `/api/health` | `{"ok": true, ...}` |
| GET | `/api/status?astronaut_id=crew-01` | GREEN / AMBER / RED / STALE, baseline, rules fired, recommended action |
| GET | `/api/baseline?astronaut_id=crew-01` | 7-day personal baseline: mean HR, SD, alert line (mean + 2 SD) |
| GET | `/api/readings?astronaut_id=crew-01&limit=100` | Recent readings, newest first |
| GET | `/api/checkins?astronaut_id=crew-01` | Recent mood check-ins |
| GET | `/api/events?astronaut_id=crew-01` | Logged actions |
| POST | `/api/readings` | `{"astronaut_id","hr_bpm","hrv_ms","spo2","temp_c","sleep_h","source"}` — returns the new status |
| POST | `/api/checkin` | `{"astronaut_id","mood":1-5,"energy","stress","sleep_quality","note"}` — returns the new status |
| POST | `/api/actions` | `{"astronaut_id","rule_id","action","note"}` |
| POST | `/api/seed` | Demo only: inserts 7 days of **synthetic** baseline readings for one astronaut |

## Try it

```bash
# 1. Check the server
curl http://localhost:8000/api/health

# 2. Seed 7 days of synthetic baseline data (demo only)
curl -X POST http://localhost:8000/api/seed \
  -H 'Content-Type: application/json' \
  -d '{"astronaut_id":"crew-01","base_hr_bpm":68}'

# 3. Log a reading (today: heart up)
curl -X POST http://localhost:8000/api/readings \
  -H 'Content-Type: application/json' \
  -d '{"astronaut_id":"crew-01","hr_bpm":79,"hrv_ms":38,"spo2":98}'

# 4. Log a low mood check-in
curl -X POST http://localhost:8000/api/checkin \
  -H 'Content-Type: application/json' \
  -d '{"astronaut_id":"crew-01","mood":2,"energy":2,"stress":4,"sleep_quality":2}'

# 5. Ask: am I OK right now — for me?
curl "http://localhost:8000/api/status?astronaut_id=crew-01"
```

Step 5 should return **RED** (rule R2: HR above baseline + 2 SD, plus mood 2/5), with a recommended action.

## Rules (R1–R5)

Implemented in `evaluate()` in `server.py`. See the table in the main `README.md`. The backend never returns GREEN when there is no recent reading (R4, stale after 10 minutes).

## Notes for the team

- The frontend (`index.html`) currently runs standalone with simulated data in the browser. Connecting it to this API is the next step — the API already returns the same status/baseline shape the frontend displays.
- Do not commit `astropulse.db` or any real health data. For the demo, use `/api/seed` (synthetic) only.
