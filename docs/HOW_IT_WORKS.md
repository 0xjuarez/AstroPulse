# AstroPulse — How It Works

**Your heart, monitored beyond Earth.**

AstroPulse is health monitoring software for astronauts on long-duration
missions, built by team **Houston, Tenemos Tacos** for the NASA Space Apps
Challenge 2026 (Local Event: Tlaxcala City).

Challenge: *Create Health Monitoring Software for Astronauts on Space Missions*
(Intermediate).

---

## 1. The problem

On long missions, astronauts face radiation, isolation and confinement,
altered gravity, and a hostile closed environment. These cause immune
changes, bone loss, cardiovascular events, and behavioral health problems.
With up to a 20-minute one-way communication delay from Earth (Mars), an
astronaut cannot wait for Mission Control to notice something is wrong.
They must be able to detect changes in themselves, on board, and act.

## 2. The question it answers

> **Am I OK right now — for me?**

Not against population averages, but against the astronaut's **own 7-day
personal baseline**. AstroPulse combines heart rate (HR) + heart-rate
variability (HRV) with a one-tap mood check-in, and answers in plain
language: what changed, why, and what to do next.

## 3. The astronaut's flow (30 seconds a day)

1. **Look at the verdict.** One large status: GREEN (cleared for duty),
   AMBER (watch), RED (act now), or STALE (no fresh data — never GREEN
   on missing data).
2. **See what changed.** The console shows the live reading next to the
   astronaut's own usual range: heart rate, HRV, SpO2, temperature,
   sleep, blood pressure, blood glucose, mood.
3. **Do the daily check-in.** One tap each for mood, energy, stress, and
   sleep quality (1–5), plus an optional note. It takes about 30 seconds.
4. **Take one action.** The console gives a single recommended action:
   continue duties, rest and breathe, or stop strenuous activity and
   notify the flight surgeon (queued if the link to Earth is down).

## 4. How the decision is made — rules R1–R5

The rules are deterministic and published, not a black-box model. Anyone
can check them by hand.

| Rule | Condition | Result |
| --- | --- | --- |
| R1 | Resting HR above personal baseline + 2 SD | AMBER |
| R2 | R1 + mood ≤ 2/5 | RED |
| R3 | SpO2 < 95% (AMBER), < 92% (RED); systolic BP ≥ 130/140; glucose outside 70–140 mg/dL; temp ≥ 37.3 °C | AMBER / RED |
| R4 | No reading in the last 10 minutes | STALE — never GREEN on missing data |
| R5 | Mood ≤ 2/5 | AMBER |

The **personal baseline** is the mean ± standard deviation of the
astronaut's own resting heart rate over the last 7 days (at least 10
readings). No NASA-published clinical HR/mood alert threshold was found,
so AstroPulse uses the personal baseline instead of inventing one.

**Worked example:** baseline 68 bpm, SD 3.3, alert line 74.8 bpm.
A reading of 79 bpm fires R1 → AMBER. A mood check-in of 2/5 on top
fires R5 + R2 → RED, with the action "stop strenuous activity, rest,
and notify the flight surgeon (queued if offline)."

## 5. The six indicators (from the challenge brief)

| Indicator | Where it shows | What the astronaut is told |
| --- | --- | --- |
| Blood pressure | 02 · Indicators, console | At-a-glance color + what the numbers mean |
| Heart rate | 01 · Verdict, 04 · Charts | Live trace + 7-day trend vs. own baseline |
| Blood glucose | 02 · Indicators | In/out of the usual 70–140 mg/dL range |
| Body temperature | 02 · Indicators | Fever line at 37.3 °C |
| Daily sleep hours | 02 · Indicators, check-in | Sleep quality 1–5 + hours |
| Mood | Check-in, 01 · Verdict | 1–5, feeds rules R2/R5 |

The **03 · Body** page is a clickable human figure: brain, heart, lungs,
immune system, muscle/bone. Each part shows its function, its live status,
and what to watch — covering immune changes, bone loss, cardiovascular
events, and behavioral health.

## 6. The console, page by page

Every section is its own page with a clean URL (no `#`):

| Page | URL | What it is |
| --- | --- | --- |
| Overview | `/` | Live verdict, risk index, six indicators, index of all pages |
| Crew | `/crew` | Roster; click a crew member to load them into the console |
| 01 · Verdict | `/verdict` | Am I OK today — for me? |
| 02 · Indicators | `/indicators` | The six challenge indicators, color-coded |
| 03 · Body | `/body` | Clickable human figure |
| 04 · Charts | `/charts` | Live HR + ECG, 7-day trend with per-indicator selector |
| 05 · Guidance | `/guidance` | Treatment guidance + mission-routine prompts (06:30 measurements, 07:00 check-in, 12:30 re-check, 16:00 exercise, 21:30 sleep) |
| Check-In | `/checkinPanel` | Daily 30-second check-in |
| 06 · Rules | `/rules` | Rules R1–R5 with live ARMED/ACTIVE state |
| 07 · Alerts | `/alerts` | Alerts + live SYS-LOG |
| Context | `/context` | Mission context: RIDGE hazards and habitat |
| 08 · Station | `/station` | Station schematic |
| System | `/system` | Pipeline, outbox, exports |
| 09 · References | `/references` | NASA data and space-agency partner resources |

### Manage pages

- **Manage Sections** (`/manage/sections`) — rename built-in sections;
  create a custom section (title + text) that gets its own clean URL,
  nav entry, and page; edit or remove custom sections.
- **Manage Operators** (`/manage/operators`) — add, edit, or remove crew
  operators (name, role, crew ID, status, baseline HR). New operators
  appear in the crew strip and load into the console like the originals.

## 7. Architecture

```
Sensors / manual entry
        │
        ▼
┌─────────────────┐
│ 1. Ingest       │  validate ranges, timestamp
├─────────────────┤
│ 2. Signal       │  HR, HRV, SpO2, temp, sleep, BP, glucose
├─────────────────┤
│ 3. Risk engine  │  deterministic rules R1–R5 (+ vitals)
├─────────────────┤
│ 4. Local store  │  append-only SQLite (backend) / localStorage (frontend)
├─────────────────┤
│ 5. Downlink sync│  store-and-forward outbox: LIVE / STALE / OFFLINE
└─────────────────┘
        │
        ▼
  Console (verdict, charts, alerts, SYS-LOG)
```

**Two modes, same logic:**

- **Frontend only** — open `index.html`. Everything runs in the browser
  with synthetic demo data (labelled as such). Rules, baseline, outbox,
  and exports all work without a server.
- **With the backend** — `python3 backend/server.py`, then open
  http://localhost:8000. Python standard library only, SQLite. The
  backend stores operators, sections, readings, check-ins, and actions,
  computes the 7-day baseline, and evaluates the same rules.

### Backend API (v2)

| Method | Endpoint | What it does |
| --- | --- | --- |
| GET | `/api/health` | Service status, version, uptime, table counts |
| GET | `/api/crew` | All operators, each with live evaluated status |
| GET | `/api/alerts` | Active AMBER / RED / STALE alerts, worst first |
| GET | `/api/status?astronaut_id=APX-01` | GREEN / AMBER / RED / STALE, baseline, rules fired, action |
| GET | `/api/baseline?astronaut_id=APX-01` | 7-day baseline: mean HR, SD, alert line (mean + 2 SD) |
| GET | `/api/trends?astronaut_id=APX-01&days=7` | Daily aggregates for the charts |
| GET | `/api/readings?astronaut_id=APX-01&limit=100` | Recent readings, newest first |
| GET | `/api/export` | Full JSON dump |
| GET/POST/PUT/DELETE | `/api/operators`, `/api/operators/:id` | Crew CRUD |
| GET/POST/PUT/DELETE | `/api/sections`, `/api/sections/:slug` | Section CRUD |
| POST | `/api/readings` | All six indicators, validated |
| POST | `/api/checkin` | Mood/energy/stress/sleep 1–5 |
| POST | `/api/seed` | Demo only: synthetic baseline data |

All six indicators are validated on write (HR 30–220, SpO2 70–100%,
temp 34–42 °C, sleep 0–24 h, BP 60–250/30–160 mmHg, glucose
40–400 mg/dL, mood 1–5). Out-of-range values return `400` naming the
field. Tests: `python3 -m unittest discover -s backend -v` (7 tests).

## 8. Offline-first

Readings, check-ins, and actions are stored locally first and queued for
sync. When the link to Earth is down (or delayed up to ~20 minutes
one-way), the app keeps working: the console shows STALE instead of
pretending everything is fine, alerts and check-ins queue in the outbox,
and everything syncs when the link returns. Demo controls: NORMAL DAY,
BAD DAY (HR up + mood down), CUT LINK TO EARTH.

## 9. Mission Control view

Four crew members at a glance, with status and last action. Clicking a
crew member loads them as the console subject, so a flight surgeon or
commander can check anyone's verdict, baseline, and trend.

## 10. How to run it

```bash
git clone https://github.com/0xjuarez/AstroPulse.git
cd AstroPulse

# Frontend only (demo, no server):
# open index.html in a browser.

# With the backend (Python 3.11+, no packages to install):
python3 backend/server.py
# open http://localhost:8000

# Tests:
python3 -m unittest discover -s backend -v
```

Live demo: https://astropulsex.netlify.app
Demo deck (7 slides): see the submission Demo link.

## 11. NASA data that makes this possible

- NASA Human Research Program / RIDGE — the five hazards of human
  spaceflight (radiation, isolation & confinement, distance from Earth,
  gravity fields, hostile/closed environments).
- NASA Open Science Data Repository (OSDR) — GeneLab + Ames Life Sciences
  Data Archive.
- Inspiration4 / Jones et al., Nature 2024 — heart rate and HRV changed
  significantly across mission phases; mood/alertness surveyed.
- NASA HRP — 5 Hazards and Risks of Human Spaceflight.
- Canadian Space Agency — radiation monitoring (MOSFET / Matroshka-R) and
  science in space.

Full list with links: `/references` in the console, and `README.md`.

## 12. Honest limits

- Prototype with synthetic demo data, calibrated to published NASA
  research. Not a medical device, does not diagnose, does not replace a
  flight surgeon, not endorsed by NASA.
- The frontend demo runs standalone with simulated data. The backend is
  real (stores data, computes baselines, evaluates rules) but does not
  connect to a real wearable yet — that is the next step.
- The cover image of the demo deck was AI-generated and is labelled as
  such in the deck. No NASA branding was generated or used.

## License

MIT — see `LICENSE`.
