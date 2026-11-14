# AstroPulse

**Your heart, monitored beyond Earth.**

**Live demo: https://astropulsex.netlify.app**

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
| R3 | SpO2 < 95% (AMBER), < 92% (RED) | AMBER / RED |
| R4 | No reading in the last 10 minutes | STALE — never GREEN on missing data |
| R5 | Mood ≤ 2/5 | AMBER |

- **Offline-first:** readings, check-ins and actions are stored locally first and queued for sync. The link to Earth can be delayed up to ~20 minutes one-way (Mars); the app keeps working and never pretends to be GREEN without fresh data.
- **Export:** records can be exported as JSON/CSV from the frontend.

## Project structure

```
AstroPulse/
├── index.html          # Frontend (static, no login, works by opening the file)
├── backend/
│   ├── server.py       # Basic backend: Python standard library only, SQLite
│   ├── README.md       # How to run the backend and use the API
│   └── requirements.txt
└── docs/
    └── demo-slides/    # 7-slide demo deck (upload the .pptx via the GitHub web UI)
```

## Run it

### Frontend only (demo, no server)

Open `index.html` in a browser. It runs with simulated demo data, labelled as synthetic.

### With the basic backend

Requires Python 3.11+ only — no packages to install.

```bash
python3 backend/server.py
# open http://localhost:8000
```

See [`backend/README.md`](backend/README.md) for the API (`/api/status`, `/api/readings`, `/api/checkin`, `/api/seed`) and `curl` examples.

### Live demo (public link for the submission)

- **Netlify: https://astropulsex.netlify.app** — deploy the repo (or drag `index.html` via Netlify Drop); connected to GitHub, every push to `main` redeploys it.
- Mirror on GitHub Pages: `https://0xjuarez.github.io/AstroPulse/` — enable in Settings → Pages → Deploy from a branch → Branch: `main`, Folder: `/ (root)`.

## NASA data that makes this possible

- **NASA Human Research Program / RIDGE** — Radiation, Isolation & Confinement, Distance from Earth, Gravity fields, Hostile/Closed Environments. Bone loss ~1–1.5%/month on long missions; communication delay up to 20 min one-way to Mars. https://www.nasa.gov/humans-in-space/the-human-body-in-space
- **NASA Open Science Data Repository (OSDR)** — GeneLab + Ames Life Sciences Data Archive (ALSDA), physiological and behavioural data. https://science.nasa.gov/biological-physical/data/osdr/
- **Inspiration4 / Jones et al., Nature 2024** — heart rate and HRV changed significantly across mission phases (HR F=37.10, p<0.0001; HRV F=5.64, p=0.0046), mood/alertness surveyed; n=4, 3 days — it supports measuring HR/HRV + mood together, it does not prove a clinical alert threshold. https://pubmed.ncbi.nlm.nih.gov/38862026/
- **GeneLab OSD-288 via OSDR** — mouse transcriptome data (radiation + microgravity), used as a reference for the evidence section; it is mouse data, not human heart-rate data.

No NASA-published clinical HR/mood alert threshold was found, so AstroPulse uses each astronaut's personal baseline instead of inventing one.

## Team

- Jesús Alejandro Juárez Contreras — Team Owner
- Arturo Miruelo Gonzalez
- Octavio Ramirez Parra

## Honest limits

- Prototype with synthetic demo data, calibrated to NASA research. Not a medical device, does not diagnose, does not replace a flight surgeon, not endorsed by NASA.
- The frontend demo runs standalone with simulated data. The backend in `backend/` is basic and real: it stores readings/check-ins, computes the personal baseline and evaluates rules R1–R5, and serves the frontend — it does not connect to a real wearable yet. That is the next step.
- All code, text and visuals in this repository are original work by the team, except the NASA data sources linked above. The cover image of the demo deck was AI-generated and is labelled as such in the deck. No NASA branding was generated or used.

## License

MIT — see `LICENSE`.
