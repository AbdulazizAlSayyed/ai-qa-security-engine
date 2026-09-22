# AI QA Engineer + AI Cybersecurity QA Engineer

A platform that runs **real** functional QA and **real** security tests against a
registered target application, normalises the evidence those tools produce, and
uses an LLM to explain, prioritise and recommend fixes for what the evidence
actually shows.

```
Target Application
       |
   QA Testing  +  Security Testing
       |
   Raw Test Evidence
       |
   Evidence Normalization
       |
   AI Analysis
       |
   Issue Detection -> Explanation -> Severity/Priority -> Recommendation
       |
   Retest -> PASS / FAIL
```

The AI never invents results. Tools execute, tools produce evidence, and every
finding references an evidence ID the backend can verify exists.

### What this is, and what it is not yet

Phases 0–10 are implemented and the pipeline above runs end to end for real.
What it executes today is a **generic smoke suite plus a passive security
baseline**, so it is honestly described as an *automated QA/security runner
with grounded AI analysis, recommendations, retesting and reporting*.

It is **not yet** an autonomous AI QA engineer. It does not know what an
application is supposed to do, does not discover an application's pages or
APIs by itself, and does not plan or execute functional test cases. Those
are future phases — see [Known limitations](#known-limitations).

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, React Router — `http://localhost:5173` |
| Backend | Python, FastAPI, Uvicorn, Pydantic — `http://127.0.0.1:8000` |
| Database | MongoDB (PyMongo's native async client) — `mongodb://localhost:27017`, database `ai_qa_security` |
| QA | Playwright |
| Security | OWASP ZAP (baseline/passive only), custom API probes, Semgrep (optional) |
| AI | OpenAI **or** Google Gemini, behind one `AIProvider` abstraction, selected by `AI_PROVIDER` |

Everything runs as **native local processes**. There is no Docker, no
PostgreSQL and no Next.js anywhere in this project.

## Prerequisites

- Python 3.12+
- Node.js 22+
- MongoDB 8 running as a local service on port 27017
- OWASP ZAP 2.17 (only for the security engine)
- An API key for whichever AI provider `AI_PROVIDER` names (only for the AI
  phases; everything else runs without one)

### One MongoDB on port 27017

`localhost` resolves to both `::1` and `127.0.0.1`. That is unambiguous only
while a single MongoDB owns port 27017. If another MongoDB — a container, a
WSL service — publishes `[::]:27017`, then `::1` and `127.0.0.1` are two
different servers and *the client's resolver*, not this project's
configuration, decides which one is reached. Different runtimes make
different choices, so a Python backend and a Node application can silently
end up on different databases.

Check before trusting anything:

```powershell
Get-NetTCPConnection -LocalPort 27017 -State Listen |
    ForEach-Object { "{0} pid={1}" -f $_.LocalAddress, $_.OwningProcess }
```

One line is healthy. More than one means the collision above. Either stop
the other listener, or pin the literal address in `backend/.env`
(`MONGODB_URI=mongodb://127.0.0.1:27017`).

`GET /health` reports `database.server_version`, and
`scripts/final_verification.py` names the exact server and host it reached,
so the instance in use is always checkable rather than assumed.

## Setup

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### Frontend

```powershell
cd frontend
npm install
Copy-Item .env.example .env
```

## Running

Two terminals, both from the repository root.

```powershell
# Terminal 1 - API on 127.0.0.1:8000. Always the venv's python, never the
# system one: a system interpreter has different packages installed.
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2 - UI on localhost:5173
cd frontend
npm run dev
```

Then open <http://localhost:5173>. Interactive API docs live at
<http://127.0.0.1:8000/docs>.

### OWASP ZAP (needed by the security engine)

```powershell
& "C:\path\to\ZAP_2.17.0\zap.bat" -daemon -host 127.0.0.1 -port 8090 -config "api.key=YOUR_KEY"
```

The quotes around `api.key=...` are **required**. `zap.bat` is a cmd script,
and an unquoted argument containing `=` is split, so ZAP either refuses to
start (`File not found '<key>'`) or starts with a key it never accepts and
answers every request with *API key incorrect or not supplied*. The daemon
takes 20–30 s to bind the port. Verify it, and set `ZAP_API_KEY` in
`backend/.env` to exactly the same value — **once**; a second `ZAP_API_KEY=`
line silently overrides the first.

```powershell
Invoke-RestMethod "http://127.0.0.1:8090/JSON/core/view/version/?apikey=YOUR_KEY"
```

Only the **baseline** profile is ever used: spider plus passive scanning.
Active scanning is deliberately never started.

## Verifying the chain

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json -Depth 5
```

A healthy response returns HTTP 200 with `database.status = "connected"`. If
MongoDB is down the same endpoint returns **HTTP 503** with `status =
"degraded"` and the reason in `database.error` — a live API over a dead
database is not a healthy service.

## Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

Three kinds of test live in this suite and they are kept distinguishable on
purpose. A fake test never counts as a real verification of anything.

| Kind | Marker | What it touches |
|---|---|---|
| Fake test | none | An engine or provider replaced via `app.dependency_overrides`. Nothing outside the process. Most of the suite. |
| Real local integration test | `integration` | The real MongoDB on the configured URI. |
| Real target E2E test | `playwright`, `security` | A real browser and/or a real OWASP ZAP against a running application. |

Run only one kind with `-m`, e.g. `pytest -m "playwright or security"`.

### Running against a scratch database

Every test respects `MONGODB_DATABASE`, so a run can be isolated from the
production database without editing anything:

```powershell
$env:MONGODB_DATABASE = 'ai_qa_security_test'
.\.venv\Scripts\python.exe -m pytest
Remove-Item Env:\MONGODB_DATABASE
```

`tests/test_config.py` separately asserts that the shipped default is still
`ai_qa_security`, so this override cannot quietly become permanent.

### The real target E2E tests

Three tests drive a real browser and a real ZAP against a running
application. `tests/conftest.py::e2e_web_target` supplies the target: it
uses an already registered, reachable one if there is one, and otherwise
registers one and removes it afterwards. The URLs come from the
environment — test-harness configuration, deliberately separate from the
application's own settings:

| Variable | Default |
|---|---|
| `E2E_TARGET_BASE_URL` | `http://localhost:3000` |
| `E2E_TARGET_API_URL` | `http://localhost:4000` |

They **skip**, with a reason naming what is missing, when nothing is
listening or ZAP is not running. That is honest: a machine with no
application running cannot answer the question. Nothing about any particular
application is encoded here or anywhere in the engines.

## Layout

```
backend/app/api/        HTTP routes and shared dependencies
backend/app/core/       settings, MongoDB lifecycle, logging
backend/app/models/     MongoDB document models
backend/app/schemas/    Pydantic request/response schemas
backend/app/services/   application services
backend/app/engines/    orchestrator, qa, security, ai, correlation,
                        remediation, retest
frontend/src/           React SPA
integrations/           Playwright, ZAP and Semgrep runner glue
test-targets/           per-target configuration and specs
reports/                generated output (git-ignored)
docs/                   design documentation
```

Target-specific knowledge belongs in `test-targets/<target>/`, never inside
the engines. Adding a second application should mean adding configuration,
not rewriting the QA or security engine.

That rule holds today because the engines are fully generic: nothing under
`app/engines/` contains a selector, page, credential or workflow belonging
to any application, and a test enforces it. `test-targets/` and
`integrations/` are therefore **still empty placeholders** — no
target-specific suite exists yet. The QA engine runs one generic smoke suite
against every target.

## Phases

Phases 0–10 are implemented. The verification column is deliberately
separate from the implementation column, because code existing and code
having been proven against a real target are different claims.

- **Implemented** — the code is written and wired up.
- **Automated tested** — covered by the test suite (mostly with fakes).
- **Real verified** — proven by an actual run against a real target, real
  browser, real scanner or real model, with the record still in the
  database.
- **Partial** — the mechanism is real, its coverage is not complete.

| Phase | Scope | Implemented | Automated tested | Real verified |
|---|---|---|---|---|
| 0 | Scaffolding: MongoDB + FastAPI + React, `/health` | Yes | Yes | Yes |
| 1 | Target registry | Yes | Yes | Yes |
| 2 | QA engine (Playwright) | Yes | Yes (fakes) | **Partial** — real Chromium runs, but only the generic smoke suite on `base_url` |
| 3 | Security engine (ZAP, authz probes, Semgrep) | Yes | Yes (fakes) | **Partial** — real ZAP baseline + API probes; authorization probes always skip; Semgrep optional |
| 4 | Collector + evidence normalization | Yes | Yes | Yes |
| 5 | AI analysis | Yes | Yes (fakes) | Yes for the configured provider — see below |
| 6 | Correlation + prioritization | Yes | Yes | Yes |
| 7 | Full dashboard | Yes | Yes | Yes |
| 8 | Recommendations | Yes | Yes (fakes) | Yes for the configured provider |
| 9 | Retest | Yes | Yes (fakes) | **Partial** — a real scoped security rescan returning FAIL; no real QA recheck and no real PASS observed yet |
| 10 | Reports | Yes | Yes | Yes — HTML + PDF, traceability audit, hashes, redaction |
| 12 | Target profiles + test accounts | Yes | Yes | Yes — configuration only; nothing authenticates yet |
| 11 | Polish + demo | Not started | — | — |

`backend/scripts/final_verification.py` reports the current state from the
database rather than from this table, and never calls a provider to
manufacture a result. Its AI items report `NOT CONFIGURED`, `CONFIGURED`,
`REAL VERIFIED` or `FAIL` for whichever provider `AI_PROVIDER` selects.

## Phase 12 — Target profiles & test accounts

A target is no longer just a name and two URLs. It carries a **profile**:
where it runs, who owns it, how it authenticates, and what this platform is
permitted to do to it. Alongside it, each target may have **test accounts**:
the identities a later phase will need in order to test authorization at all.

**Phase 12 does not execute authenticated testing.** Nothing signs in,
nothing reads an authentication profile, and no engine consumes a test
account yet. This is the configuration foundation those phases will build
on; the authorization and security workflows themselves come later.

### The profile

| Block | Fields |
|---|---|
| Identity | `name`, `description` |
| Application | `type` (`web_application` / `api` / `web_and_api`), `base_url`, `api_url`, `source_path` |
| Environment | `environment` (`local` / `development` / `staging` / `test` / `production`), `ownership_status` (`owned` / `authorized` / `third_party` / `unknown`) |
| Authentication | `enabled`, `method` (`none` / `form` / `basic` / `bearer` / `cookie` / `custom`), `login_url`, `username_field`, `password_field`, `token_location` |
| Security policy | `authorized_for_testing`, `allow_security_scanning`, `allow_authenticated_testing`, `allow_state_changing_requests` |

`username_field` and `password_field` are the **names of the inputs on the
login form**, so a later phase knows what to fill in. Neither holds a value.

### The authorization flag

`authorized_for_testing` defaults to **false**, and so does every capability.
Registering a target is not consenting to anything being done to it.

The flag **gates** the rest: with it false, no `allow_*` capability may be
true, and the API rejects any attempt — on create or on update. This is a
technical safety control, not a legal statement. Its purpose is that a
capability cannot be acquired one field at a time.

Three more rules hold, all failing closed:

- **Production is treated conservatively.** `allow_security_scanning` and
  `allow_state_changing_requests` cannot be enabled when
  `environment = production`, and moving an existing target to production
  while it holds either is refused.
- **Authenticated testing needs authentication.**
  `allow_authenticated_testing` requires `authentication.enabled`, since
  otherwise there is no configured way to authenticate.
- **A patch is judged on the document it would produce**, not on the fields
  it mentions. Clearing `authorized_for_testing` while a capability stays
  enabled is refused, and nothing is written.

### Test accounts

An account belongs to exactly one target and is always addressed through it
(`/targets/{target_id}/test-accounts/{account_id}`). An account reached
through the wrong target answers **404** rather than being returned, so an
identity registered for one application cannot be used against another.

| Field | Notes |
|---|---|
| `name` | Unique within the target |
| `role` | `admin` / `user` / `readonly` / `anonymous` / `custom` — metadata, not an authorization rule |
| `purpose` | Free text, e.g. `authorization_test_user`. No engine matches on it |
| `username` | The identity's username |
| `credential_reference` | The **name** of an environment variable |
| `credential_available` | Read-only: whether that variable is currently set |
| `enabled`, `description`, timestamps | |

An `anonymous` account represents an unauthenticated visitor and therefore
carries neither a username nor a credential reference.

Deleting a target that still has accounts is **refused with 409**, naming how
many are in the way. Cascading would destroy identities without being asked;
orphaning would leave records pointing at nothing.

### Secret handling

**No password is ever stored, logged, returned or displayed.** That is
enforced structurally rather than by remembering to redact:

- There is **no field** a credential could go into. `extra="forbid"` turns
  `password`, `secret`, `token` or `cookie` in a request body into a 422.
- `credential_reference` accepts only an environment-variable **name**
  (`^[A-Z][A-Z0-9_]*$`). A pasted password does not match that shape and is
  rejected with an explanation.
- Free-text fields reject obvious spellings like `password=…`.
- The value is read from the environment of the machine running the backend,
  at the moment something needs it. It never enters MongoDB, an API response,
  the browser or a report. The API reports only whether the variable is set.

Set the values in your shell or service configuration, never in a file that
is committed:

```powershell
$env:E2E_ADMIN_PASSWORD = '...'   # the value lives here, and only here
```

Then reference the **name** from the account:

```json
{
  "name": "Admin test account",
  "role": "admin",
  "username": "admin@test.local",
  "credential_reference": "E2E_ADMIN_PASSWORD",
  "purpose": "authorization_test_user"
}
```

### Backward compatibility

Targets registered in Phases 1–10 are **never rewritten**. Their documents
stay exactly as they were written, and the missing profile fields are filled
in on read with the safe defaults above — so an old target answers every
question a new one does, keeps its id, and remains referenced by all its
existing assessments, runs, evidence and reports.

## Known limitations

These are current, factual gaps. Nothing below is implemented yet.

**QA coverage is shallow.** The QA engine runs five generic smoke checks —
reachability, page title, DOM availability, console-error collection,
network-failure collection — against the target's `base_url` only. It does
not navigate, fill forms, or exercise any functional flow, so functional
bugs are not detected.

**No application discovery.** Nothing crawls a target to build a map of its
pages, routes, forms or controls. ZAP's traditional spider does not follow a
client-rendered SPA, and no AJAX spider is configured.

**No API discovery.** Successful API traffic is not recorded; the browser
listeners capture only failed requests. There is no OpenAPI import, and the
API probes examine the registered `api_url` root only.

**Authorization probing is a placeholder.** `authorization_probes` always
returns `skipped` with its reason. Phase 12 gives the registry somewhere to
record authentication configuration and test identities, but no engine reads
them yet, so the probe still has nothing authorised to act with. It never
claims to have run.

**No requirements engine.** The platform has no concept of what an
application is *supposed* to do. Nothing is stored about requirements, user
stories or acceptance criteria, so no finding can be traced to a
requirement.

**No AI test planner and no generic executor.** The AI only analyses
evidence that already exists and drafts advisory recommendations. It cannot
plan test cases, and there is no deterministic executor with a generic
action vocabulary to run them. By design the AI never calls a tool, reaches
a target, or writes a file.

**Retest is only partly proven.** A real scoped security rescan has been
observed returning `FAIL` against an unchanged target. A real QA recheck has
not run, and a real `PASS` verdict has not yet been observed, because that
needs a target whose defect has actually been fixed.

**AI providers.** `AI_PROVIDER` selects `openai` or `gemini`. Each needs its
own key and model; without them, analysis fails with a clear configuration
error and nothing else breaks. In this repository's development environment
only Gemini has been configured and verified for real — the OpenAI path is
implemented and unit-tested but has not been verified against the live API.

**Semgrep is optional.** It only runs when the binary is installed and the
target has a `source_path`; otherwise the component reports `skipped`.

**Security testing is non-destructive by design.** ZAP baseline only, never
an active scan, and the API probes send only `GET`, `HEAD` and `OPTIONS`.
This is a safety boundary, and it also means input-validation and
state-changing behaviour cannot currently be tested.

## Authorized use

This platform performs security testing. It is only ever pointed at
applications owned by the author or covered by explicit written authorization
to test. Scanning defaults to passive/light, and nothing here implements
destructive or uncontrolled exploitation.
