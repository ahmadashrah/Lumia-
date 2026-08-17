# Lumia

Operations and sales platform for Ashrah Painting. Two Flask apps that ship as
one deployment:

- **Lumia** (`lumia_app.py`) — the ops app. Crew daily check-ins, jobs,
  employees, estimates, quotes, contracts, client reporting, owner dashboard.
- **Lio** (`lio_app.py` + `lio/`) — the sales/marketing agent. Outbound
  drafting, market research, competitive intel, campaigns, a file-backed CRM.

Lio runs as a sibling Flask app mounted into Lumia at `/lio/*` via
`DispatcherMiddleware` (`lumia_app.py:23421`), so a single gunicorn process
serves both. The dashboard's Lio tab just iframes `/lio/`.

---

## Running it locally

Requires Python 3.11+ and git.

```bash
git clone https://github.com/ahmadashrah/Lumia-.git
cd Lumia-
git checkout main

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python lumia_app.py              # http://localhost:5000
```

**You do not need any credentials to start.** Every one of the ~78 environment
variables has a fallback, and the ones that don't are read lazily. With an
empty environment the app boots all 226 routes; login pages, the dashboard
shell and `/lio/health` all render. Features whose keys are missing fail when
you use them, not at startup.

To configure anything, copy the template and fill in only what you need:

```bash
cp .env.example .env
```

`.env` is gitignored. `lio_app.py` loads it via python-dotenv; for `lumia_app.py`
export the vars or run under a loader. In production these live in
Railway → Variables, not in a file.

What needs a key to work:

| Feature | Needs |
|---|---|
| Check-ins, jobs, employees persisting | `SUPABASE_URL` + `SUPABASE_KEY` |
| Lumia chat, Lio agents, estimates | `ANTHROPIC_API_KEY` |
| Image generation, voice transcription | `GEMINI_API_KEY` |
| Contract extraction | `OPENAI_API_KEY` |
| Daily reports, escalations | `ZOHO_PASSWORD` |
| Cold outreach send | `LIO_SMTP_PASSWORD` |
| SMS | `TWILIO_*` |

Running Lio standalone on its own port is sometimes easier when working on
agents:

```bash
python lio_app.py                # http://localhost:5050
```

---

## Layout

```
lumia_app.py              ops app — routes, templates, business logic
lio_app.py                Lio's Flask entrypoint and JSON API
lio/
  core/
    engine.py             Anthropic wrapper: generate(system, user)
    prompts.py            composes the system prompt for a capability
    crm.py                file-backed contact store (atomic writes)
    mailer.py             outbound SMTP
    imap_client.py        inbox reading
    inbox_sync.py         inbox -> CRM status updates
    gemini.py             Gemini wrapper (images)
    logger.py             per-run JSON logs -> logs/lio/<date>/
  capabilities/           one module per agent
  prompts/                one markdown system prompt per agent
  missions/active.md      shared mission context injected into every agent
  data/                   CRM contacts, research, outreach drafts
ashrah_backfill.py        crew tracking, Excel log, report sending
lumia_estimates.py        estimating engine
static/ templates/        assets and the public site
scripts/                  one-off and batch jobs
```

---

## How a Lio agent works

Every capability shares one path. `lio/capabilities/content.py` is the whole
pattern:

```python
from ._runner import run as _run

def run(payload: dict) -> dict:
    return _run("content", payload, max_tokens=2000)
```

`_runner.run()` builds the system prompt, JSON-dumps your payload as the user
message, calls the model and writes a run log. The system prompt is assembled
by `lio/core/prompts.py` in this order:

```
prompts/base.md  +  prompts/ashrah_facts.md  +  missions/active.md  +  prompts/<name>.md
```

So `base.md` carries voice and rules, `ashrah_facts.md` carries company facts,
`missions/active.md` carries whatever campaign is currently running, and the
capability file carries the task.

### Adding one

Three steps, no framework changes:

1. Write `lio/prompts/<name>.md` — the task-specific system prompt.
2. Create `lio/capabilities/<name>.py` — the five lines above with `<name>`.
3. Register it in the `CAPABILITIES` dict in `lio_app.py:24` and add it to the
   import on line 18.

Then call it:

```bash
curl -X POST localhost:5050/api/run \
  -H 'Content-Type: application/json' \
  -d '{"capability":"<name>","payload":{"topic":"..."}}'
```

Capabilities that need real logic instead of one prompt — `research`
(Semantic Scholar → PDF → model) and `market_intel` (web search, cost
tracking, CRM upsert) — skip `_runner` and implement `run()` themselves.

### Current limits

Worth knowing before building on this:

- **Four of the seven capabilities are single-shot.** `content`, `outbound`,
  `campaign` and `competitive` are one prompt in, one blob of text out. There
  is no tool-use loop in `engine.py`, so an agent cannot read the CRM, look up
  a job, act on a result or revise its own draft. Adding that loop is the
  prerequisite for agents that *do* things rather than draft them.
- **Registration is manual.** Every new capability needs `lio_app.py` edited
  in two places. Fine for seven, friction at thirty.
- **`claude-opus-4-7` is pinned in five places**, including hardcoded as
  `GENERATION_MODEL` in `lio/core/engine.py:6`. Confirm that model ID is
  current before building on it.

---

## Deploying

Railway, via nixpacks. `Procfile`:

```
web: gunicorn lumia_app:app --bind 0.0.0.0:$PORT --workers 3 --threads 2 --timeout 300
```

One process serves Lumia and Lio both. `nixpacks.toml` pins the native libs
PyMuPDF needs for PDF work. Config comes from Railway → Variables.

A background scheduler (APScheduler) starts in-process: daily reports 18:00,
escalations 20:00, tender reminders 08:00, attention digest 07:00, Zoho scan
every 15 minutes, all Winnipeg time.

---

## Branches

`main` is the live line of development — deploy from it and branch from it.

The GitHub default branch is currently set to `claude/keen-antonelli`, which is
75 commits behind `main` and does not reflect production. Worth repointing the
default in the repo settings so clones land on `main`.
