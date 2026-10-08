# Phase 1 Test Report

Date: 2026-10-06 (updated after security-hardening round)
Scope: Saudi HR System Phase 1 — foundation, auth, RBAC, companies, branches,
users, roles, permissions, audit, PostgreSQL RLS isolation, OpenAPI, login
scaffold — plus the approved security-hardening round (H1, H2, M1–M6).

Status: **COMPLETE — full suite executed against PostgreSQL 18.**

## Summary

| Classification | Count | Meaning |
|---|---:|---|
| **PASSED** | **120** | 98 Phase 1 tests + 22 hardening regression tests (55 offline + 65 DB-integration) |
| **PENDING** | **0** | Nothing skipped; database tests actually executed |
| **FAILED (code problem)** | **0** | — |
| Total collected | 120 | — |

Runner: `pytest -q` (backend). Result: `120 passed in ~28s`.

## Environment

- Python 3.12.9, Node 24.11.1, npm 11.6.2
- PostgreSQL 18.3 (`postgresql-x64-18`, port 5432); the separate Odoo
  PostgreSQL service was not touched.
- Created for this run: role `saudi_hr_user` (login + CREATEDB),
  databases `saudi_hr` (app) and `saudi_hr_test` (disposable), both owned by
  `saudi_hr_user`, UTF8. Application and pytest connect **only** as
  `saudi_hr_user`; destructive fixtures run **only** against `saudi_hr_test`.
- `backend/.env` (git-ignored) holds `DATABASE_URL` / `TEST_DATABASE_URL`.
- Lint: `ruff check .` → **All checks passed**.
- Frontend: `npm run build` (tsc strict + vite) → **built successfully**.

## 1. PASSED — offline suite (55 = 54 Phase 1 + 1 hardening)

### Security primitives (`test_security_unit.py`, 14)
- Argon2id hashing: not plaintext, verify ok/wrong, per-hash salting.
- JWT: roundtrip (`sub`, `type`), expired rejected, wrong `type` rejected,
  wrong signature rejected.
- CSRF: valid / missing header / missing cookie / mismatched — all correct.
- Refresh token: unique raw values, stable SHA-256 (64-hex) storage form.
- CSRF token uniqueness.

### Configuration hardening (`test_config_unit.py`, 7)
- Development defaults load; `secure_cookies` off in dev, on in production.
- Production rejects: missing `SECRET_KEY`, dev-default key, key < 32 chars,
  weak key (too few distinct chars), missing explicit `DATABASE_URL`.
- Valid production config passes.

### RLS framework (`test_rls_unit.py`, 9)
- Registry covers exactly the 7 company-scoped Phase 1 tables; `permissions`
  and `refresh_tokens` correctly excluded; no future/placeholder tables
  registered.
- Every policy renders `USING` + `WITH CHECK` with platform-admin bypass and
  `app.current_company_ids()`; `companies` uses `id` column; `users` carries
  the narrow self-read; `audit_logs` carries actor self-read.
- SQL helper functions exist and are exception-guarded; garbage-token guard
  (`^[0-9]{1,10}$`, excluding `0`) present.

### Schemas & catalog (`test_schemas_unit.py`, 8)
- Permission codes unique; default roles reference only existing permissions;
  all catalog entries have module.
- Validation: login identifier length, user password minimum, branch status
  pattern, company defaults (SA / SAR / Asia/Riyadh / sun-thu), pagination math.

### API surface without DB (`test_api_offline.py`, 16)
- `/health` ok (reports DB down cleanly, lists RLS tables).
- OpenAPI contains all 18 Phase 1 paths; **no Phase 2+ paths** (payroll,
  attendance, leave, payslip, gosi, employee) leak into the spec.
- 401 on all protected routers without/garbage token; stable
  `{"detail","code"}` error shape.
- Refresh: GET → 405; missing CSRF → 403; incorrect CSRF → 403; valid CSRF but
  no cookie → 401. Invalid login body → 422.

### Server smoke test (manual, executed)
- `uvicorn app.main:app` boots; `/health` returns ok with 7 RLS tables;
  `/openapi.json` serves 18 paths; `/api/v1/auth/me` → 401.

## 2. PASSED — DB-integration suite (65 = 44 Phase 1 + 21 hardening)

All of the following ran against `saudi_hr_test` with real Alembic migration
`0001_phase1` and real RLS.

### Auth flow (`test_auth_db.py`, 11)
login success (token + HttpOnly refresh cookie path `/api/v1/auth` + readable
CSRF cookie) · wrong password 401 · unknown identifier 401 · inactive user 401
· `/me` context (company ids + permissions) · refresh rotation (cookie changes)
· **refresh reuse detection revokes whole family** · logout 204 then refresh 401
· access token required for `/me` · change-password success invalidates old
password + sessions · change-password wrong current 401.

### CRUD + RBAC (`test_crud_rbac_db.py`, 11)
platform admin creates company + 4 default roles seeded with expected
permissions (incl. `company.create` excluded for `company_admin`) · non-admin
cannot create company 403 · branch CRUD · duplicate branch code 409 · same code
allowed across companies · user create with role assignment · duplicate email
409 · non-admin cannot grant `is_platform_admin` 403 · permission catalog
requires `permission.read` · role permission update roundtrip + unknown
permission 404 · auditor (no write perms) gets 403 on branch/company create but
can read audit.

### Multi-company isolation (`test_isolation_db.py`, 16)
- **DB-level (psycopg2, bypassing app services):** no-context ⇒ 0 rows
  (deny-by-default) · admin bypass sees all · member context sees only its
  company · cross-company INSERT fails with *row-level security* violation ·
  GUC helper functions never raise on NULL/empty/`0`/garbage/oversized values ·
  admin GUC accepts only literal `true` · **elevated context does not leak
  across commit** · self-read scoping on `users`.
- **Schema assertions:** FORCE RLS verified on all 7 tables via
  `pg_class.relforcerowsecurity` · policies present via `pg_policies`.
- **API-level:** user/branch/role listings scoped per company · cross-company
  detail access 404 · audit rows scoped · seed elevation does not leak into
  subsequent request contexts.

### Audit (`test_audit_db.py`, 6)
login success audited with actor/IP · failed logins audited (known + unknown
identifier) · mutation audit carries old/new JSON · pagination (pages disjoint,
totals) · filter by action · actor/record/company fields populated.

## 3. Bugs found and fixed during the DB run

Three genuine issues surfaced on the first full DB run (2 test failures +
isolation-run errors); all were fixed and the complete suite re-run:

1. **Test fixture (`tests/conftest.py`)** — `db_schema` dropped tables via
   `Base.metadata`, but on isolated runs the model modules were never imported
   (0 tables) so the drop loop no-opped and leftover tables collided with the
   Alembic upgrade. Fixed: import model modules explicitly and drop through the
   active connection.
2. **Implementation (`app/roles/service.py`)** — `set_role_permissions`
   deleted and re-inserted overlapping `role_permissions` in one flush; the
   INSERT could emit before the DELETE → unique-constraint violation on any
   update that keeps existing permissions. Fixed: flush deletions first.
3. **Test data (`tests/test_audit_db.py`)** — `test_audit_filter_by_action`
   created a branch with `name="F"` (below `min_length=2` → 422), so no audit
   row existed; the test also didn't assert the create succeeded. Fixed: valid
   name + explicit `assert status_code == 201` (assertion strengthened, not
   weakened).

Additionally, `alembic check` detected **migration↔model drift** (7 items) and
was corrected by aligning the pre-ship migration to the models:

- `audit_logs.old_value/new_value` model type `String` → `Text` (JSON payloads).
- `branches.manager_id` index added to migration.
- `refresh_tokens.family_id` length `VARCHAR(36)` → `VARCHAR(64)`.
- `refresh_tokens.token_hash` unique **constraint** → unique **index**
  `ix_refresh_tokens_token_hash` (matches model).
- `refresh_tokens.replaced_by_id` index added to migration.

After the fix: `alembic check` → **No new upgrade operations detected.**

## 4. PostgreSQL / RLS verification (direct psql)

On `saudi_hr_test` (and equivalent state on `saudi_hr`):

- `FORCE ROW LEVEL SECURITY` = true, `ROW LEVEL SECURITY` = true on exactly the
  7 scoped tables: `audit_logs, branches, companies, role_permissions, roles,
  user_roles, users`.
- `permissions`, `refresh_tokens`, `alembic_version` correctly **not**
  company-scoped.
- 7 policies present (`pg_policies`, one per scoped table).
- GUC helpers exist in schema `app`: `app.current_company_ids`,
  `app.current_user_id`, `app.is_platform_admin`.
- Permission catalog seeded: `permissions = 16`.
- Behavior verified in-suite: deny-by-default with no context, platform-admin
  bypass, cross-company INSERT blocked by RLS, no GUC context leak across
  commit, audit rows company-scoped.

## 5. Migration status

- `saudi_hr`: `alembic current` → `0002_security_hardening (head)`;
  full `downgrade base` → `upgrade head` cycle validated earlier for
  `0001_phase1`, and the `0002 → 0001 → 0002` cycle validated on
  `saudi_hr_test`.
- `saudi_hr_test`: at `0002_security_hardening (head)` (fixture re-runs
  migrations every suite run, which also exercises `0002` each time).
- `alembic check` → clean (no drift between models and migrations).
- `0001_phase1` was **not modified** in the hardening round; all schema
  changes landed in the new `0002_security_hardening` revision.

## 6. Other checks

- **Ruff:** `ruff check .` → All checks passed.
- **Frontend:** `npm run build` → built successfully (tsc strict + vite).
- **OpenAPI:** 18 paths, no Phase 2 leakage (offline tests).

## 7. Frontend (build-verified only)

- Login scaffold: in-memory access token (never localStorage), refresh via
  `POST /auth/refresh` with `X-CSRF-Token` read from cookie on boot and on 401,
  `/me` → dashboard, logout, AR/EN i18n with RTL toggle, dev proxy →
  `127.0.0.1:8000`.
- Browser-level E2E (login through UI against a live API) is **not** part of
  Phase 1; it needs a running API with a seeded account.

## 8. How to run

```
cd backend
.\.venv\Scripts\python.exe -m pytest -q      # full suite (uses saudi_hr_test only)
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m alembic check  # set TEST_DATABASE_URL to test db first
cd ..\frontend && npm run build
```

Optional manual API run:

```
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.cli create-platform-admin --email admin@example.com --full-name "Admin"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## 9. Security hardening round (approved items H1, H2, M1–M6)

All 8 approved items implemented, regression-tested, and verified. No
existing test was skipped, weakened, or deleted (98 → 120, +22 new).

### H1 — per-company permission scoping (authorization)
- `Principal` now carries `permissions_by_company` alongside the union
  `permissions` (kept for `/me` back-compat) with `has_permission(code,
  company_id)` and `permitted_company_ids(code)` (`app/core/deps.py`).
- Route dependencies remain coarse gates; services perform strict
  company-scoped checks and scope list endpoints to companies where the code
  is granted: `users`, `roles`, `branches`, `companies` services and the
  `audit-logs` router (explicit `company_id` requires `audit.read` there;
  unfiltered listing limited to permitted companies + own actor rows).

### H2 — `company.update` / `company.read` / `company.create` enforced
- `PATCH /companies/{id}` now requires `company.update` (was completely
  unenforced); `GET /companies/{id}` requires `company.read`; list scoping
  uses `company.read`; `create_company` checks `company.create` alongside the
  router's platform-admin gate. No catalog entries were removed.

### M1 — database-level self-escalation guard (migration `0002`)
- `app.guard_users_security()` trigger on `users` (BEFORE INSERT/UPDATE):
  non-admin GUC context cannot change `is_platform_admin`/`company_id`/
  `email`/`employee_id` on any row, cannot change its own `is_active`, cannot
  change another account's `password_hash`, and cannot insert platform
  admins. App layer additionally rejects self-deactivation with 403 (clean
  error instead of a DB fault).

### M2 — atomic refresh-token claim
- Rotation claim is a single conditional `UPDATE ... RETURNING` (row-locked);
  exactly one concurrent request can rotate a token. Reuse of a consumed
  token revokes the whole family, audits, and commits before returning 401.

### M3 — session-security audit events
- New audit actions: `auth.refresh_reuse_detected`, `auth.logout`,
  `auth.password_change_failed` (committed before the error response).
  Raw tokens, passwords, and CSRF values are never persisted; only opaque
  family identifiers.

### M4 — deactivation revokes sessions, durably
- `PATCH /users/{id}` with `is_active: false` revokes all active refresh
  tokens in the same transaction and commits before the response is produced;
  reactivation never revokes/un-revokes; an inactive account's refresh
  rotation also persists its family revocation before failing.

### M5 — uniform login errors, timing parity, PostgreSQL-backed lockout
- All login failures (unknown user, wrong password, inactive, locked) return
  an identical `401 {"detail": "Invalid credentials"}`; a dummy Argon2 verify
  runs for unknown accounts; audit `record_id` truncated to the 64-char
  column. Lockout sourced from `audit_logs`: ≥5 failures per identifier or
  ≥10 per IP within 15 minutes blocks with `auth.login_blocked` (blocked
  attempts never extend the window).

### M6 — documentation endpoints follow environment
- `ENVIRONMENT=production` disables `/docs`, `/redoc`, and `/openapi.json`
  (dev/test unchanged).

### Hardening regression tests (+22)
- `test_permission_scoping_db.py` (3): cross-company strict denial + list
  filtering + audit scoping; `company.update` enforcement for auditor and
  hr_manager; zero-permission role gets no data access (and 200-empty
  `/companies`).
- `test_users_rls_hardening_db.py` (6): direct-SQL self-escalation,
  self-reactivation, cross-user password reset, and platform-admin INSERT all
  blocked by the trigger; platform-admin/self password paths still work; API
  self-deactivation 403.
- `test_refresh_concurrency_db.py` (2): two threads racing the same refresh
  token → exactly one winner, one rejection, whole family revoked; sequential
  reuse rejection.
- `test_security_events_audit_db.py` (4): reuse/logout/failed-password-change
  audited with actor+company and without token material; failed logins record
  identifier without the attempted password.
- `test_user_deactivation_db.py` (3): deactivation kills sessions (DB +
  API), reactivation allows a fresh login but never resurrects old sessions,
  deactivation durable before the response.
- `test_login_security_db.py` (3): identical failure bodies; identifier
  lockout after 5 failures with correct-password rejection and window
  expiry recovery; IP lockout (10 failures) with blocked-not-failed
  accounting.
- `test_production_docs_unit.py` (1): docs/redoc/openapi 404 in production
  while `/health` keeps working; restored to dev afterwards (settings cache
  cleared).

### Hardening verification (psql + suite)
- Both databases at `0002_security_hardening (head)`; `0001_phase1`
  unchanged; `alembic check` clean; `0002` downgrade→upgrade cycle validated
  on `saudi_hr_test`.
- 7/7 tables keep `relrowsecurity=true` and `relforcerowsecurity=true`, 7
  policies present, 4 `app` GUC functions + `app.guard_users_security`,
  trigger `trg_users_security_guard` present on `users`, `permissions = 16`.
- Live probes as app role `saudi_hr_user` (superuser probes bypass RLS and
  are not valid evidence): member context reads 0 rows of another company;
  cross-company INSERT fails with *row-level security policy* violation;
  member-context `UPDATE users SET is_platform_admin=true` fails with
  *security-sensitive columns require platform administrator context*.
  All probe data rolled back (0 leftovers).

## 10. Known remaining issues

- None affecting Phase 1 acceptance. Notes:
  - Two benign warnings in test output (starlette TestClient deprecation;
    short HMAC key used by one negative JWT test on purpose).
  - `.env` holds a generated local password; change it (and the `postgres`
    password) for anything beyond this local dev run.
  - Browser E2E against a live API deferred (see §7).
