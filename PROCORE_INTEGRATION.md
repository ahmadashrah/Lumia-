# Procore Integration

Lumia talks to Procore in both directions:

| Direction | What moves |
|---|---|
| **Lumia → Procore** | Every employee check-in is posted to the Daily Log of the linked Procore project — a **Manpower log** (who was on site, for how long) and a **Notes log** (the written summary, quality self-scores, tomorrow's plan and photo links). |
| **Procore → Lumia** | Procore projects can be browsed from the owner dashboard and imported as Lumia jobs, and are the list you pick from when linking a site. |

Files: `procore_client.py` (API client), `procore_integration.py` (routes + sync),
`test_procore.py` (offline test suite).

---

## 1. Create the Procore app

In the [Procore Developer Portal](https://developers.procore.com), create an app and
add the **Data Connection** / REST API component. You then choose one of two auth modes.

**A. Owner approval (authorization code)** — an owner clicks *Connect Procore* in the
dashboard and approves Lumia. Best when one person's Procore permissions should govern
what Lumia can write.

Add this redirect URI to the app:

```
https://<your-lumia-domain>/procore/callback
```

**B. Service account (client credentials)** — the app runs headless with a Developer
Managed Service Account (DMSA), which a Procore company admin installs and grants
project permissions to. No one has to reconnect it. Leave `PROCORE_REDIRECT_URI` unset
(or set `PROCORE_GRANT_TYPE=client_credentials`) and Lumia uses this mode.

Either way the service account or user needs, on each synced project:
**Daily Log — Standard** (to create manpower and notes entries) and **Project — Read**.

## 2. Environment variables

| Variable | Required | Description |
|---|---|---|
| `PROCORE_CLIENT_ID` | yes | App client ID |
| `PROCORE_CLIENT_SECRET` | yes | App client secret |
| `PROCORE_COMPANY_ID` | yes | Procore company ID (sent as the `Procore-Company-Id` header) |
| `PROCORE_REDIRECT_URI` | mode A | `https://<domain>/procore/callback` — omit for mode B |
| `PROCORE_ENV` | no | `production` (default) or `sandbox` |
| `PROCORE_GRANT_TYPE` | no | Force `client_credentials` |
| `PROCORE_AUTO_SYNC` | no | `false` turns off the push-on-submit (default on) |
| `PROCORE_DEFAULT_HOURS` | no | Hours recorded per check-in on the manpower log (default `8`) |
| `PROCORE_API_BASE_URL` / `PROCORE_AUTH_BASE_URL` | no | Override the endpoints if Procore moves them |

`PROCORE_ENV=sandbox` points at `login-sandbox.procore.com` / `sandbox.procore.com`;
production is `login.procore.com` / `api.procore.com`.

## 3. Supabase tables

Run this once in the Supabase SQL editor. Without it the integration still works, but
links and tokens live only in memory and are lost on restart.

```sql
create table if not exists procore_tokens (
  id            text primary key default 'default',
  access_token  text,
  refresh_token text,
  expires_at    bigint,
  token_type    text,
  scope         text,
  updated_at    timestamptz default now()
);

create table if not exists procore_links (
  id                   uuid primary key,
  site_keyword         text not null unique,
  procore_project_id   bigint not null,
  procore_project_name text,
  procore_company_id   text,
  created_at           timestamptz default now()
);

create table if not exists procore_sync_log (
  id                  uuid primary key,
  checkin_id          text,
  procore_project_id  bigint,
  status              text,          -- synced | partial | unlinked | error
  detail              text,
  manpower_log_id     bigint,
  notes_log_id        bigint,
  created_at          timestamptz default now()
);

create index if not exists procore_sync_log_checkin_idx on procore_sync_log (checkin_id);
```

`procore_tokens` holds live credentials — leave RLS enabled and reach it only with the
service key the app already uses.

## 4. Connect and link

1. Sign in to `/owner` and open the **Procore** tab.
2. In mode A, click **Connect Procore** and approve. Mode B is connected already.
3. Click **Load Procore Projects**, enter a **site address keyword**, pick the project,
   and **Save Link**.

The keyword works exactly like the client-report keyword: a check-in whose site address
contains it syncs to that project. `23 falcon` matches "23 Falcon Ridge Dr, Winnipeg".
When several keywords match, the longest one wins.

## 5. What happens then

* On submit, a check-in is pushed to Procore in a background thread — the employee never
  waits on it, and a Procore outage cannot fail a check-in.
* At **6:15 PM Winnipeg time** a catch-up sweep re-pushes the day's check-ins, so a site
  linked later in the day, or a push that failed on a network blip, still lands.
* Each attempt is recorded in `procore_sync_log` and shown under **Recent Sync Activity**.
* A check-in already synced is skipped rather than duplicated; **Push Check-Ins to
  Procore** re-runs the day safely.

Failure handling: a 401 refreshes the token once and retries; 429 and 5xx back off and
retry up to three times, honouring `Retry-After`. If only one of the two log entries is
rejected, the other is kept and the row is marked `partial` with the reason.

## 6. Testing

```bash
python -m unittest test_procore -v
```

27 tests covering the OAuth flows, token refresh and rotation, retry behaviour, the
check-in → daily-log mapping, deduplication and the dashboard API. Procore itself is
stubbed with `httpx.MockTransport`, so no network or credentials are needed.

## 7. Endpoints Lumia uses

| Purpose | Call |
|---|---|
| Token / refresh | `POST {auth}/oauth/token` |
| Companies | `GET /rest/v1.0/companies` |
| Projects | `GET /rest/v1.0/projects?company_id=…` |
| Manpower log | `POST /rest/v1.0/projects/{id}/manpower_logs` |
| Notes log | `POST /rest/v1.0/projects/{id}/notes_logs` |

Payload shapes live in `procore_client.py`; if Procore renames a Daily Log field, that
file is the only place to change.
