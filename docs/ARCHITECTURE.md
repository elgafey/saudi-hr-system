# Saudi HR Management System — Architecture

Status: Phase 1 implemented (foundation). Later phases are design-only below and
are not present in code until each module is built.

## 1. Goals and constraints

- Multi-company (multi-tenant) HR platform for Saudi businesses.
- Company = tenant. Isolation enforced in three layers (see §5).
- No dependency on Odoo: own PostgreSQL, own ORM, own auth.
- Bilingual (AR/EN) with RTL support; SAR, Asia/Riyadh, Sun–Thu default week.
- SaaS-ready: no hardcoded single-company assumptions; platform-admin is the only
  cross-company role. Billing/subscription is deliberately out of scope.

## 2. Stack

| Layer | Choice |
|---|---|
| API | FastAPI + Pydantic v2, Python 3.12 |
| DB | PostgreSQL 18 (existing local instance, dedicated role/database) |
| ORM | SQLAlchemy 2.0 (declarative), Alembic migrations |
| Auth | JWT access (15 min, in-memory on client) + rotating refresh cookie (14 days) |
| Passwords | Argon2id |
| RLS | PostgreSQL Row Level Security with `FORCE` on all tenant tables |
| Frontend | Vite + React + TypeScript + Tailwind (login scaffold in Phase 1) |
| Tests | pytest (offline unit/API tests + `db`-marked integration tests) |

Databases: `saudi_hr` (application), `saudi_hr_test` (disposable tests).
Never Odoo's database, config, ORM, or credentials.

## 3. Repository layout

```
saudi-hr-system/
  .env.example            # placeholders only; .env is git-ignored
  backend/
    alembic/              # env.py + versions/0001_phase1.py
    app/
      main.py             # app factory, CORS, exception handlers, /health
      cli.py              # create-platform-admin, apply-rls
      core/               # config, database, security, rls, deps, exceptions, pagination
      shared/             # Base, mixins, Phase 1 models
      auth/               # login/refresh/logout/me, refresh-token rotation
      companies/          # tenant CRUD + default-role seeding
      branches/           # branch CRUD
      users/              # user CRUD + role assignment
      roles/              # roles, role↔permission, permission catalog
      audit/              # audit log model/service/reader
      permissions/        # permission catalog + default roles (source of truth)
    tests/                # offline + db suites
  frontend/               # Vite/React login scaffold
  docs/                   # ARCHITECTURE.md, PHASE1_TEST_REPORT.md
```

## 4. Layered backend design

Request flow:

```
router (HTTP only) → schemas (validation) → service (business rules)
                   → deps/authorization (principal + permission checks)
                   → repository/session (SQLAlchemy, RLS context already set)
```

- No business logic in route handlers; routers delegate to services.
- `core/deps.py` builds a `Principal` (user id, company memberships, permission
  set) from the access token and sets the transaction-local RLS context before
  any query runs.
- `core/rls.py` is the single reusable RLS framework: registry → DDL → policies
  → context helpers. Every future module registers its tables there and gets
  isolation for free.

## 5. Multi-company isolation (three layers)

1. **Service layer** — every service validates `principal.can_access_company()`
   before reading or writing a row (fast, friendly 403/404).
2. **Authorization layer** — permission codes (`company.read`, `branch.create`,
   …) checked per endpoint; platform admin bypasses permission checks only.
3. **PostgreSQL RLS** — final guarantee, independent of application code:

   - `ENABLE ROW LEVEL SECURITY` **and `FORCE ROW LEVEL SECURITY`** on every
     company-scoped table (owner is subject too):
     `companies, branches, users, roles, role_permissions, user_roles, audit_logs`.
   - `permissions` (global catalog) and `refresh_tokens` (opaque-hash session
     data, no company dimension) are intentionally not company-scoped.
   - Policy shape:
     `USING (is_platform_admin() OR company_id = ANY(app.current_company_ids()) OR <narrow self-read>)`
     with a matching `WITH CHECK`.
   - Context GUCs set with `set_config(..., is_local=true)` → **transaction
     local only**, can never leak into a later request:
     `app.user_id`, `app.company_ids`, `app.is_platform_admin`.
   - **Deny by default**: no context + non-admin ⇒ sees zero tenant rows.
   - Helper functions are defensive (NULL/empty/`0`/garbage GUC values never
     raise; they collapse to an empty scope).
   - Bootstrap self-read: a user can read their own `users`/`user_roles` rows
     while memberships are being loaded; `WITH CHECK` keeps writes scoped.
   - Seeds/CLI elevate explicitly (`elevate_for_seed`) inside the same
     transaction and clear immediately after.

## 6. Authentication

- `POST /api/v1/auth/login` with `{"identifier","password"}`. Phase 1 resolves
  `identifier` as email only; employee-number login arrives in Phase 2 via
  `users.employee_id → employees.id` **without changing this API**.
- Access token: short-lived JWT, held in frontend memory only (never
  localStorage), sent as `Authorization: Bearer`.
- Refresh token: opaque 256-bit value, stored **hashed** (SHA-256) with a
  `family_id`. HttpOnly cookie, `SameSite=Lax`, `Secure` in production, path
  limited to `/api/v1/auth`, POST-only endpoints.
- Rotation: every refresh mints a new token and revokes the old one; reusing a
  revoked token revokes the **entire family** (reuse detection).
- CSRF: explicit double-submit — `hr_csrf_token` cookie (JS-readable, path `/`)
  must match the `X-CSRF-Token` header on refresh/logout. Missing, incorrect,
  and valid values are all tested.
- Logout revokes the family and clears both cookies.
- Password change revokes all of the user's refresh tokens.
- Failed and successful logins are audited; errors never reveal whether an
  account exists.

## 7. RBAC

- `users ↔ user_roles ↔ roles ↔ role_permissions → permissions`.
- `user_roles` and `role_permissions` are company-scoped rows; permissions are a
  global catalog keyed by stable codes (`module.action`).
- Permission checks: `require_permission("branch.create")` per endpoint;
  platform admin implicitly holds all codes.
- Default roles seeded for every new company:
  `company_admin` (all except `company.create`), `hr_manager`, `hr_officer`,
  `auditor` (read-only + audit).
- Platform admin: `users.is_platform_admin`, only role able to create companies
  and change company status; grants checked in service layer (non-admins cannot
  self-elevate).

## 8. Audit

- Append-only `audit_logs`: actor, action, entity, record id, old/new JSON
  (truncated-safe serialization), IP, timestamp, company.
- Written by services for every mutation and by auth for login outcomes.
- Readable only with `audit.read`; RLS scopes rows to the caller's companies
  plus their own actions (platform admin sees all).

## 9. Phase 1 data model (implemented)

```
companies 1──n branches
companies 1──n users            (users.company_id, nullable)
companies 1──n roles
companies 1──n user_roles ──n users, roles
companies 1──n role_permissions ──n roles, permissions
users 1──n refresh_tokens (family_id, token_hash, revoked/replaced)
users/nullable 1──n audit_logs (actor), companies 1──n audit_logs
permissions (global catalog: code, name, module)
```

`users.employee_id` exists only as a nullable placeholder; the FK to
`employees` is added in Phase 2. No employee/attendance/payroll tables and no
fake placeholder tables exist.

## 10. Future ERD (Phase 2+, design only — not in code)

```
employees (company_id, employee_no UNIQUE per company, user_id→users,
           first/last name AR+EN, national_id, iqama_no, iqama_expiry,
           passport_no, dob, gender, marital_status, nationality,
           mobile, email, hire_date, termination_date, status)
departments (company_id, code, name, manager_id→employees)
job_titles  (company_id, code, title, grade)
contracts   (company_id, employee_id, type: fixed|unlimited|probation,
             start/end, salary_base, allowances JSON, probation_end,
             notice_days, status, signed_at)
attendance_days / attendance_entries (company_id, employee_id, date,
             clock_in, clock_out, source: device|manual|import,
             work_minutes, overtime_minutes, status)
leave_types (company_id, code, name, paid, unit, carry_over rules)
leave_requests (company_id, employee_id, type, start, end, days,
             status: draft→pending_manager→pending_hr→approved|rejected,
             approver_ids, reason, attachments)
leave_balances (company_id, employee_id, type, year, entitlement,
             taken, carried, adjustment)
payroll_periods (company_id, year, month, status:
             open→calculated→review→approved→locked)
payroll_runs    (company_id, period_id, status, inputs snapshot JSON,
             totals, locked_at, locked_by)
payroll_lines   (company_id, run_id, employee_id, earnings JSON,
             deductions JSON, gosi_employee, gosi_employer, net)
payslips        (company_id, run_id, employee_id, number UNIQUE,
             issued_at, pdf_path, immutable after issue)
adjustments / reversals (company_id, run_id, reason, actor, approved_by)
gosi_records    (company_id, employee_id, month, base, employee_share,
             employer_share, submission_status)
notifications   (company_id, user_id, channel: email|in_app, title,
             body, read_at) + notification_channels abstraction
portal_accounts (company_id, subject: employee|external, user_id→users,
             kind: employee_portal|manager_portal)
files / file_links (company_id, owner_kind, owner_id, path, checksum)
```

Cross-company rules for future phases (to be enforced with the same three
layers): every table above carries `company_id` and registers in
`core/rls.py`; shared/head-office views are explicit platform-admin features,
never implicit joins across tenants.

## 11. Future cross-company test matrix (documented, implemented per module)

| Module | Must-verify isolation cases (on landing) |
|---|---|
| Employees | A-admin cannot list/read/update B employees; employee numbers unique only per company; reports never cross tenants; RLS insert of B row under A context fails |
| Departments/Job titles | scoped CRUD; manager refs cannot point at another company's employee |
| Contracts | no cross-company reads; salary data invisible to B; contract of A employee rejected when posted with B context |
| Attendance | entries scoped; device/import rows can't leak; manager approvals restricted to their subtree within one company |
| Leave | balances/requests scoped; approver workflow never crosses tenants; carry-over jobs process one company at a time |
| Payroll | periods/runs/lines/payslips scoped; A run cannot include B employee (insert WITH CHECK fails); locked runs immutable |
| GOSI | submissions scoped per company; monthly aggregates never mix tenants |
| Notifications | delivery jobs pick rows under explicit company context only |
| Portals | portal user sees only its company; manager portal scoped to subtree |
| Files | storage paths tenant-partitioned; no cross-tenant download by id guessing |
| Cross-module | every new table: deny-by-default empty context, FORCE RLS, seed elevation non-leak (reuse the Phase 1 isolation suite as the template) |

## 12. Security baseline

- Argon2id hashing; secrets never logged; `.env` git-ignored.
- Production startup fails on missing/dev-default/weak `SECRET_KEY` and on
  implicit `DATABASE_URL`.
- Error responses use a stable `{detail, code}` shape; no stack traces.
- CORS restricted to configured origins with credentials.
- Refresh tokens stored hashed; cookies HttpOnly/SameSite/Lax/Secure-in-prod.
- SQL is always parameterized; dynamic SQL exists only in migration/DDL paths.

## 13. Deployment

- Phase 1: local execution (uvicorn + local PostgreSQL 18). No Docker/Redis
  required yet.
- Target: Docker Compose (api + postgres + frontend), health-gated.
- Backups: daily `pg_dump` + nightly file-storage snapshot to an external
  target (chosen: backups; implementation in a later phase).
- Kubernetes explicitly deferred.

## 14. Phase roadmap

1. **Phase 1 (this)**: foundation, auth, RBAC, companies, branches, users,
   roles, permissions, audit, RLS, tests, OpenAPI, login scaffold.
2. Phase 2: employees + contracts + departments/job titles + employee-number
   login.
3. Phase 3: attendance + leave.
4. Phase 4: payroll engine + payslips + immutability (Approved→Locked,
   Adjustment/Reversal only) + GOSI.
5. Phase 5: notifications, portal accounts, reports.
6. Phase 6: hardening, backups, deployment finalization.

Each phase: explain → file list → implement → tests → fix → report → approval.
