# AstroPulse

**Your heart, monitored beyond Earth.**

**Live demo: https://astropulsex.netlify.app**

**Demo deck (7 slides): https://docs.google.com/presentation/d/13brLH5973es0B_X8-d88hQXZwqcSVHJ_/edit?usp=drivesdk&ouid=102482995816099942720&rtpof=true&sd=true**

AstroPulse is health monitoring software for astronauts on long-duration missions, built by team **Houston, Tenemos Tacos** for the **NASA Space Apps Challenge 2026** (Local Event: Tlaxcala City).

Challenge: *Create Health Monitoring Software for Astronauts on Space Missions* (Intermediate).

## The question it answers

> **Am I OK right now — for me?**

Not against population averages, but against the astronaut's own 7-day personal baseline. AstroPulse combines heart rate (HR) + heart-rate variability (HRV) with a one-tap mood check-in, and answers in plain language: what changed, why, and what to do next.

## What it does

- **Astronaut view:** live ECG, heart rate, HRV, SpO2, temperature, sleep, risk status **GREEN / AMBER / RED / STALE**, 5-minute HR chart and 7-day trend.
- **Daily check-in:** mood / energy / stress / sleep, 1–5, plus a note.
- **Mission Control:** 4 crew members at a glance, with their status and last action.
- **Rules R1–R5 (deterministic, checkable, no black-box AI):**

| Rule | Condition | Result |
| --- | --- | --- |
| R1 | Resting HR above personal baseline + 2 SD | AMBER |
| R2 | R1 + mood ≤ 2/5 | RED |
| R3 | SpO2 < 95% (AMBER), < 92% (RED); BP ≥ 130/140; glucose outside 70–140 mg/dL; temp ≥ 37.3 °C | AMBER / RED |
| R4 | No reading in the last 10 minutes | STALE — never GREEN on missing data |
| R5 | Mood ≤ 2/5 | AMBER |

- **Offline-first:** readings, check-ins and actions are stored locally first and queued for sync. The link to Earth can be delayed up to ~20 minutes one-way (Mars); the app keeps working and never pretends to be GREEN without fresh data.
- **Export:** records can be exported as JSON/CSV from the frontend.

## The console, page by page

Every section is its own page with a clean URL (no `#`), following the official challenge order:

| Page | URL |
| --- | --- |
| Overview | `/` |
| Crew | `/crew` |
| 01 · Verdict | `/verdict` |
| 02 · Indicators (blood pressure, heart rate, blood glucose, temperature, sleep, mood) | `/indicators` |
| 03 · Body (clickable human figure) | `/body` |
| 04 · Charts | `/charts` |
| 05 · Guidance | `/guidance` |
| Check-In | `/checkinPanel` |
| 06 · Rules | `/rules` |
| 07 · Alerts | `/alerts` |
| Context | `/context` |
| 08 · Station | `/station` |
| System | `/system` |
| 09 · References | `/references` |

### Manage pages

- **Manage Sections** (`/manage/sections`) — rename the built-in sections; create a custom section (title + text) that gets its own clean URL, nav entry and page; edit or remove custom sections.
- **Manage Operators** (`/manage/operators`) — add, edit or remove crew operators (name, role, crew ID, status, baseline HR); new operators appear in the crew strip and load into the console. Everything is stored in the browser (localStorage, offline-first) and included in the JSON export.

## Project structure

```
AstroPulse/
├── index.html          # Frontend (static, no login, works by opening the file)
├── _redirects          # Netlify: clean URLs (/* /index.html 200)
├── backend/
│   ├── server.py       # Backend v2: Python standard library only, SQLite
│   ├── README.md       # How to run the backend and use the API
│   ├── test_server.py  # 7 tests (run: python3 -m unittest discover -s backend -v)
│   └── requirements.txt
└── .gitignore
```

## Run it

### Frontend only (demo, no server)

Open `index.html` in a browser. It runs with simulated demo data, labelled as synthetic.

### With the backend (v2)

Requires Python 3.11+ only — no packages to install.

```bash
python3 backend/server.py
# open http://localhost:8000
```

```bash
python3 -m unittest discover -s backend -v   # 7 tests, all passing
```

The backend stores operators, sections, readings, check-ins and actions in SQLite, computes the 7-day personal baseline, and evaluates rules R1–R5 plus the vital-sign checks. API highlights: `GET /api/crew` (all operators + live status), `GET /api/alerts`, `GET /api/trends`, `GET /api/export`, CRUD for `/api/operators` and `/api/sections`, `POST /api/readings` (all six challenge indicators, validated), `POST /api/checkin`, `POST /api/seed` (synthetic demo data). See [`backend/README.md`](backend/README.md) for the full API and `curl` examples.

### Live demo (public link for the submission)

- **Netlify: https://astropulsex.netlify.app** — connected to GitHub, every push to `main` redeploys it.
- Mirror on GitHub Pages: `https://0xjuarez.github.io/AstroPulse/` — enable in Settings → Pages → Deploy from a branch → Branch: `main`, Folder: `/ (root)`.
- **Demo deck (7 slides, public):** https://docs.google.com/presentation/d/13brLH5973es0B_X8-d88hQXZwqcSVHJ_/edit?usp=drivesdk&ouid=102482995816099942720&rtpof=true&sd=true

## NASA data that makes this possible

- **NASA Human Research Program / RIDGE** — Radiation, Isolation & Confinement, Distance from Earth, Gravity fields, Hostile/Closed Environments. Bone loss ~1–1.5%/month on long missions; communication delay up to 20 min one-way to Mars. https://www.nasa.gov/humans-in-space/the-human-body-in-space
- **NASA Open Science Data Repository (OSDR)** — GeneLab + Ames Life Sciences Data Archive (ALSDA), physiological and behavioural data. https://science.nasa.gov/biological-physical/data/osdr/
- **Inspiration4 / Jones et al., Nature 2024** — heart rate and HRV changed significantly across mission phases (HR F=37.10, p<0.0001; HRV F=5.64, p=0.0046), mood/alertness surveyed; n=4, 3 days — it supports measuring HR/HRV + mood together, it does not prove a clinical alert threshold. https://pubmed.ncbi.nlm.nih.gov/38862026/
- **NASA HRP — 5 Hazards of Human Spaceflight** — https://www.nasa.gov/?p=553281
- **NASA HRP — Risks of Human Spaceflight** — https://www.nasa.gov/hrp/risks/
- **GeneLab OSD-288 via OSDR** — mouse transcriptome data (radiation + microgravity), used as a reference for the evidence section; it is mouse data, not human heart-rate data.
- **Canadian Space Agency — radiation and astronaut health** — https://www.asc-csa.gc.ca/eng/sciences/osm/radiation.asp/
- **Canadian Space Agency — why science experiments are conducted in space** — https://www.asc-csa.gc.ca/eng/iss/science/why-do-we-conduct-science-experiments-in-space.asp
- **Canadian Space Agency — MOSFET radiation monitoring system and Matroshka-R** — http://www.asc-csa.gc.ca/eng/sciences/osm/mosfet.asp

No NASA-published clinical HR/mood alert threshold was found, so AstroPulse uses each astronaut's personal baseline instead of inventing one. NASA does not endorse any non-US government entity; data is used under each website's own data-use parameters.

## Team

- Jesús Alejandro Juárez Contreras — Team Owner
- Arturo Miruelo Gonzalez
- Octavio Ramirez Parra

## Honest limits

- Prototype with synthetic demo data, calibrated to NASA research. Not a medical device, does not diagnose, does not replace a flight surgeon, not endorsed by NASA.
- The frontend demo runs standalone with simulated data. The backend in `backend/` is real: it stores readings/check-ins, computes the personal baseline and evaluates rules R1–R5, and serves the frontend — it does not connect to a real wearable yet. That is the next step.
- All code, text and visuals in this repository are original work by the team, except the NASA data sources linked above. The cover image of the demo deck was AI-generated and is labelled as such in the deck. No NASA branding was generated or used.

## License

MIT — see `LICENSE`.
