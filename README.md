# Lumen — personal finance + AI-assisted stock investing

Three-tier monolithic app:

- **Frontend** — Vite + React 18 + TypeScript + Tailwind + shadcn/ui (port 5173)
- **Backend** — Flask 3 + Pydantic v2 + PyMongo (port 5000)
- **Database** — MongoDB 7 (port 27017)
- **ML** — XGBoost (stock signals) + TF-IDF + LogisticRegression (transaction categorization), loaded into the Flask process at startup

This guide takes a brand-new machine from `git clone` to a fully working dev environment. Time budget: ~30 min if everything goes smoothly.

---

## 0. Prerequisites

Install these once. Versions in parentheses are minimums; newer is fine.

| Tool | Why | Install |
|---|---|---|
| **Python 3.11** | Backend runtime | https://www.python.org/downloads/ — tick "Add to PATH" on Windows |
| **Node.js 20** + npm | Frontend dev server + build | https://nodejs.org/ |
| **Docker Desktop** | Local MongoDB (easiest) | https://www.docker.com/products/docker-desktop/ |
| **Git** | Clone | https://git-scm.com/ |

Optional but useful:

- **mongosh** — CLI for inspecting Mongo. Bundled with Docker Desktop's Mongo image, or install standalone from https://www.mongodb.com/try/download/shell.

You can also use **MongoDB Atlas** (free M0 tier) instead of Docker if you don't want a local container — see §3.b below.

Verify your install:

```bash
python --version    # 3.11.x
node --version      # v20.x
npm --version
docker --version
git --version
```

---

## 1. Clone

```bash
git clone <your-fork-or-this-repo-url> lumen
cd lumen
```

Repo layout (top level):

```
lumen/
├── backend/        # Flask app + ML modules + tests
├── frontend/       # Vite + React app
├── docker-compose.yml   # Local MongoDB
├── changes.md      # development log
└── .claude/        # thesis plan + AI-assistant instructions (read-only)
```

---

## 2. Backend setup

### 2.1 Create a virtual environment + install deps

From the **`backend/` directory**:

```bash
cd backend
python -m venv .venv
```

Activate the venv:

- **Windows (PowerShell):** `.venv\Scripts\Activate.ps1`
- **Windows (cmd):** `.venv\Scripts\activate.bat`
- **macOS / Linux:** `source .venv/bin/activate`

Then install:

```bash
pip install -r requirements.txt
```

This pulls Flask, PyMongo, Pydantic, XGBoost, scikit-learn, yfinance, pandas, NumPy, pytest etc. ~5 minutes on a cold cache.

### 2.2 Configure environment

Copy the template and fill it in:

```bash
cp .env.example .env       # macOS/Linux
copy .env.example .env     # Windows
```

Open `backend/.env` and set:

```
FLASK_ENV=development
FLASK_APP=run.py

# Local Docker (default for this guide):
MONGO_URI=mongodb://localhost:27017/finance_thesis

# Generate a real secret — do NOT keep the placeholder:
JWT_SECRET_KEY=<paste output of `python -c "import secrets; print(secrets.token_urlsafe(48))"`>

# Optional fallback when yfinance is throttled:
ALPHA_VANTAGE_KEY=

CORS_ORIGINS=http://localhost:5173
```

For **Atlas** instead of Docker, replace `MONGO_URI` with your `mongodb+srv://...` connection string.

---

## 3. Database

### 3.a — Local Docker (recommended)

From the **project root** (where `docker-compose.yml` lives):

```bash
docker compose up -d mongo
```

This pulls Mongo 7, starts it on `localhost:27017`, and persists data to a Docker volume named `mongo_data`. Verify:

```bash
docker ps           # finance_thesis_mongo should be Up
mongosh "mongodb://localhost:27017/finance_thesis"   # optional
```

To stop later: `docker compose down`. To wipe all data: `docker compose down -v`.

### 3.b — Atlas free tier (alternative)

1. Create a free M0 cluster at https://cloud.mongodb.com.
2. Add `0.0.0.0/0` to the IP allowlist (dev only — tighten for prod).
3. Create a database user with read/write on `finance_thesis`.
4. Copy the connection string into `backend/.env` as `MONGO_URI`.

The Flask app creates indexes idempotently on every startup — no manual schema setup needed.

---

## 4. ML model artifacts

Model `.joblib` files are gitignored (binary, ~50 MB each), so a fresh clone has none. You need to train them once before the signals + categorization features work.

From `backend/` with the venv active:

```bash
# 1. Seed historical OHLCV bars from yfinance for the 100 tracked tickers.
#    Takes ~10 minutes. Pulls 5 years of daily bars per ticker.
python -m scripts.seed_stock_data

# 2. Train the XGBoost stock-signal classifier on the seeded bars.
#    Takes ~1–2 minutes. Writes ml_models/v1/xgb_classifier.joblib + metrics.json.
python -m app.ml.signals.train_xgb

# 3. Train the TF-IDF + LogisticRegression categorization model.
#    Takes ~30 seconds. Writes ml_models/v1/tfidf_lr.joblib.
python -m app.ml.categorization.train_tfidf_lr
```

If `seed_stock_data` fails partway (network blip, yfinance rate limit), just re-run it — it skips tickers it already has and resumes.

After training, `backend/ml_models/v1/` should contain:

```
xgb_classifier.joblib
tfidf_lr.joblib
metrics.json
```

---

## 5. Run the backend

From `backend/` with the venv active:

```bash
flask --app run.py run --debug --port 5000
```

You should see:

```
* Running on http://127.0.0.1:5000
* Debug mode: on
```

Sanity-check from another terminal:

```bash
curl http://localhost:5000/api/health
# {"status":"ok"}
```

The Flask process loads the ML models from `ml_models/v1/` into memory at startup and starts an in-process APScheduler (daily stock-data refresh, daily net-worth snapshot, planned-payment materialiser). All collections + indexes are auto-created on first run.

---

## 6. Frontend setup

In a **second terminal**, from the project root:

```bash
cd frontend
npm install
```

`node_modules/` is heavy (~500 MB) — install takes 1–3 minutes.

Copy the env template:

```bash
cp .env.example .env       # macOS/Linux
copy .env.example .env     # Windows
```

The default `VITE_API_BASE_URL=http://localhost:5000/api` matches the backend; only change it if you ran Flask on a different port.

Start the dev server:

```bash
npm run dev
```

You should see:

```
VITE v5.x  ready in xxx ms
➜  Local:   http://localhost:5173/
```

Open http://localhost:5173/ — the landing page should appear. Click **Get started** and register. Registration auto-creates Cash + Paper Portfolio (with $10,000 of virtual cash) accounts plus the 14 default categories.

---

## 7. Run the tests (recommended sanity check)

### Backend

From `backend/` with the venv active:

```bash
pytest -q
```

Expected: **385 passed**. Tests use `mongomock` so they don't touch your real Mongo.

### Frontend

From `frontend/`:

```bash
npm run typecheck    # TypeScript: should be clean
npm run build        # Production build: should finish with no errors
```

---

## 8. Daily workflow (after the one-time setup is done)

You need three terminals open:

| Terminal | Directory | Command |
|---|---|---|
| 1 | project root | `docker compose up -d mongo` (only once a day) |
| 2 | `backend/` | `flask --app run.py run --debug --port 5000` |
| 3 | `frontend/` | `npm run dev` |

When you're done:

```bash
# Stop dev servers with Ctrl-C in their terminals.
docker compose down     # optional — keeps the data volume
```

---

## 9. Updating after a `git pull`

```bash
# Backend deps may have changed
cd backend && source .venv/bin/activate && pip install -r requirements.txt

# Frontend deps may have changed
cd ../frontend && npm install

# DB indexes — auto-applied on next backend startup, no action needed.

# ML model schema may have changed — if you see model-load errors at
# backend startup, re-run §4 to retrain:
cd ../backend
python -m scripts.seed_stock_data
python -m app.ml.signals.train_xgb
python -m app.ml.categorization.train_tfidf_lr
```

---

## 10. Troubleshooting

**`ModuleNotFoundError` when running pytest** — venv isn't active. Re-run the activate step in §2.1.

**`pymongo.errors.ServerSelectionTimeoutError`** — Mongo isn't running. `docker compose up -d mongo`, then check `docker ps`.

**Frontend shows 401s in the console** — the backend isn't running, or `VITE_API_BASE_URL` doesn't match the Flask port. Confirm both are on default ports.

**`yfinance` throws "rate limited"** during `seed_stock_data` — back off 5 minutes and re-run. The script resumes from where it left off (per-ticker idempotent on `(ticker, date)` unique index).

**`xgboost` install fails on macOS arm64** — install libomp first: `brew install libomp`, then retry `pip install -r requirements.txt`.

**Mongo data is wrong / I want to start over** — `docker compose down -v` wipes the volume. Restart with `docker compose up -d mongo` and re-register.

---

## 11. Optional: VS Code launch configs

Drop these into `.vscode/launch.json` if you want one-click debug:

```jsonc
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Backend (Flask debug)",
      "type": "debugpy",
      "request": "launch",
      "module": "flask",
      "args": ["--app", "run.py", "run", "--debug", "--port", "5000"],
      "cwd": "${workspaceFolder}/backend",
      "env": { "FLASK_ENV": "development" },
      "console": "integratedTerminal"
    },
    {
      "name": "Frontend (Vite)",
      "type": "node",
      "request": "launch",
      "runtimeExecutable": "npm",
      "runtimeArgs": ["run", "dev"],
      "cwd": "${workspaceFolder}/frontend",
      "console": "integratedTerminal"
    }
  ]
}
```

---

## 12. Where to look next

- **`backend/app/api/`** — every HTTP endpoint, one blueprint per resource.
- **`backend/app/services/`** — all business logic; no Flask imports allowed here.
- **`frontend/src/pages/`** — one file per route.

---
