# Construction platform integrations

Pushes Lumia crew check-ins into the GC's system so crews file once. Procore
is implemented; Autodesk Construction Cloud and Buildertrend slot in behind
the same interface.

## How it fits together

```
check-in saved ──► outbox.submit_checkin()   (off-thread, never blocks the crew)
                        │
                        ├─ is the connector configured?
                        ├─ is this job mapped to a project?
                        ├─ already sent?  (idempotency)
                        └─ enqueue ──► integration_outbox
                                            │
              scheduler, every 5 min ──► outbox.process()
                                            │
                                   connector.push_daily_log()
```

A Lumia check-in becomes a `DailyLog` (platform-neutral) once. Each connector
maps that to its own API. Adding a platform is one file in `integrations/`;
the registry finds it automatically and nothing else changes.

Failure handling is deliberate:

- **Nothing is pushed inline.** A slow or broken GC API cannot slow down or
  fail a crew member's submission.
- **Retryable vs terminal.** 429 and 5xx back off (5, 15, 60, 240 min) and give
  up after 5 attempts. A 422 or a bad mapping fails immediately rather than
  hammering the GC's API.
- **Idempotent.** A check-in already marked `sent` is never queued again, and
  each note carries a `[lumia:checkin:<id>]` marker so a duplicate is visible
  to a human.
- **Dry-run by default.** A new mapping authenticates and builds the payload
  but does not write, so you can validate against a live account without
  putting anything in front of a GC.

## Database

```sql
create table if not exists integration_job_map (
  job_id      text not null,
  platform    text not null,
  project_ref text not null,
  enabled     boolean not null default true,
  dry_run     boolean not null default true,
  created_at  timestamptz not null default now(),
  primary key (job_id, platform)
);

create table if not exists integration_outbox (
  id              bigserial primary key,
  platform        text not null,
  job_ref         text,
  project_ref     text,
  source_id       text,
  payload         jsonb not null,
  status          text not null default 'pending',   -- pending | sent | failed
  attempts        int  not null default 0,
  last_error      text,
  remote_id       text,
  next_attempt_at timestamptz not null default now(),
  created_at      timestamptz not null default now()
);

create index if not exists integration_outbox_due_idx
  on integration_outbox (status, next_attempt_at);
create index if not exists integration_outbox_source_idx
  on integration_outbox (platform, source_id) where status = 'sent';
```

## Procore setup

You need three values. Only an account admin can get them:

1. Sign in at <https://developers.procore.com> with your Procore account.
2. Create an app. For unattended server-to-server pushes ask for a **Data
   Management Service Account** (client-credentials); a normal user-auth app
   needs a human to re-consent and will stall the scheduler.
3. Install the app on your company and grant it write access to Daily Log on
   the projects you care about.
4. Collect `PROCORE_CLIENT_ID`, `PROCORE_CLIENT_SECRET`, `PROCORE_COMPANY_ID`.

Set them in Railway → Variables. Set `PROCORE_SANDBOX=true` first and point at
a sandbox project until you've confirmed a note lands where you expect.

> **Confirm before go-live.** `DAILY_LOG_PATH` and `_build_payload()` in
> `integrations/procore.py` encode Procore's daily-log endpoint and field
> names. Procore exposes several daily-log sub-resources and the right one
> depends on which log type you want entries to land in — verify both against
> <https://developers.procore.com> in the sandbox. They're isolated in one
> place precisely so this is a small edit. Auth, hosts and the company header
> are standard and are not in doubt.

## Turning it on for a job

```bash
# 1. map a Lumia job to a Procore project — dry-run by default
curl -X POST https://<host>/api/integrations/map \
  -H 'Content-Type: application/json' \
  -d '{"job_id":"42","platform":"procore","project_ref":"555"}'

# 2. file a test check-in, then drain without waiting for the schedule
curl -X POST https://<host>/api/integrations/drain

# 3. check what happened
curl https://<host>/api/integrations/status

# 4. once the dry run looks right, arm it
curl -X POST https://<host>/api/integrations/map \
  -H 'Content-Type: application/json' \
  -d '{"job_id":"42","platform":"procore","project_ref":"555","dry_run":false}'
```

`project_ref` is Procore's project id, from the project URL in Procore.

## Adding a platform

Create `integrations/<name>.py` with a `Connector` subclass implementing
`is_configured()` and `push_daily_log()`. Raise `ConnectorError(..., retryable=)`
so the outbox can tell a transient fault from a permanent one. The registry
picks it up — no central list to edit, no changes to the check-in path.

## Tests

```bash
python -m unittest discover -s tests
```

Every network call is mocked; the suite covers auth caching, the
retryable/terminal split, idempotency, backoff, and that one poisoned outbox
row cannot stop the rest of the queue draining.
