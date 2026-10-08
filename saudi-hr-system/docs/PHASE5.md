# Phase 5 - Leave Management

Leave type configuration, statutory rule versioning, allocation
pools (manual / generate / carry-forward), the leave request
workflow with day counting and attachment support, derived balances,
and company holidays.
Builds on Phase 1 (foundation), Phase 2 (employee master data),
Phase 3 (employee lifecycle), and Phase 4 (attendance, schedules,
shifts, overtime).

Status: complete. Backend 445 tests passing, frontend builds clean,
migration 0006 applied and verified on the test database
(`saudi_hr_test`). The dev database (`saudi_hr`) is intentionally NOT
migrated yet - `alembic upgrade head` on `saudi_hr` is an operator
action, deliberately not run during this phase.

## 1. Scope

- Leave types: per-company configuration (paid flag, approval
  requirements for requests and allocations, day counting mode,
  attachment/reason rules, min/max request days, default entitlement,
  carry-forward policy, allowance treatment, statutory flag, status).
- Statutory rules: versioned, non-overlapping effective windows per
  statutory key with a mandatory source citation and
  `requires_legal_verification` until an operator clears it. No Saudi
  statutory values are seeded or hardcoded anywhere (D2).
- Allocations: the entitlement pool per employee/type/period - manual
  create, bulk generate, carry-forward from a source period, approval
  workflow (submitted -> approved/rejected), hard delete only while
  unconsumed.
- Requests: draft -> submitted -> approved/rejected/cancelled with
  server-side day counting (working vs calendar days resolved through
  the Phase-4 schedule), overlap guards, optional single attachment,
  inline auto-approval when the type does not require approval.
- Balances: fully derived from allocations + consumptions + requests
  (D3 - there is deliberately NO `leave_balances` table).
- Company holidays (D1): a dedicated company-scoped table consumed by
  day counting; no statutory holiday dataset is shipped.
- Default `employee` role with self-service leave codes only is
  created for every company (D4).
- Frontend: five pages (Leave Requests, Leave Allocations, Leave
  Types, Leave Balances, Company Holidays) plus an Employee Detail
  "Leave" tab.

Out of scope (unchanged): payroll, GOSI, tax, notifications,
schedulers/recurring jobs, approval engine, self-service portal,
billing, public-holiday datasets. Phase 5 produces the
`leave_consumptions` inputs a later payroll phase may consume; it
does not compute payroll amounts.

## 2. Database (migration `0006_phase5_leave_management`)

Never modify 0001-0005. Frozen SHA-256 hashes (re-verified this
phase):

| Migration | SHA-256 |
|---|---|
| `0001_phase1` | `5fe83204197a9ffcba377181188a1141fcbaafbc0606490b92ce699150d53e30` |
| `0002_security_hardening` | `2a6bc5292832040757409f42f2ba26ef565539cb671ae11003020f4a458aef8d` |
| `0003_phase2_employee_master_data` | `d5aae7696cb5fc15a0c8ea0e2bd6599375a5c2fb8b596c61fc2eb5d18e5ba324` |
| `0004_phase3_employee_lifecycle` | `798a87c0d92312866a7fa8480d74fd670fa04a43453819eedf4d2f115ffc921a` |
| `0005_phase4_attendance` | `1d3c7d91996c73f6994603d917956753cc9f5261c6bc6eab5f033e380a6297e` |

File name is `0006_phase5_leave_management.py` but the revision
**id** is `0006_phase5_leave` (VARCHAR(32) limit in
`alembic_version.version_num`). `down_revision =
0005_phase4_attendance`. Downgrade to 0005 and re-upgrade were
exercised on `saudi_hr_test` (inside `test_leave_migrations_db.py`
and interactively).

### 2.1 Tables (6 new; all company-scoped, RLS enabled + forced)

- `leave_types` - code, names, description, `is_paid`,
  `requires_approval`, `allocation_requires_approval`,
  `day_counting_mode` (working_days|calendar_days),
  `requires_attachment` + `attachment_threshold_days`,
  `requires_reason`, `negative_balance_allowed`,
  `min_request_days`/`max_request_days`,
  `default_entitlement_days`, `carry_forward_enabled` +
  `carry_forward_max_days` + `carry_forward_expiry`
  (none|end_of_year|end_of_next_year), `allowance_treatment`
  (continue|deduct|prorate), `is_statutory` + `statutory_key`,
  `status` active|inactive, `sort_order`. Unique
  `uq_leave_type_company_code`; CHECKs cover status, day-counting
  mode, expiry enum, allowance enum, positive thresholds,
  `min <= max`, request-days range; index `ix_leave_type_company_status`.
- `leave_statutory_rules` - `statutory_key`, `jurisdiction`
  (server-set), monotonic `version` per
  `(company_id, statutory_key)` (`uq_leave_statutory_rule_version`),
  `[effective_from, effective_to)` window (NULL = open),
  `rule_json`, mandatory non-empty `source_reference`
  (`ck_leave_statutory_rule_source` - a citation/URL/internal policy
  reference), `source_date`, `requires_legal_verification` (DB
  default **true**), `notes`, `status` active|inactive. gist EXCLUDE
  `exq_leave_statutory_rule_no_overlap`
  `(company_id WITH =, statutory_key WITH =, daterange(effective_from,
  effective_to, '[)') WITH &&)` so adjacent versions (v1 ends where
  v2 starts) are legal.
- `leave_allocations` - `employee_id`, `leave_type_id`,
  `[period_start, period_end]` (inclusive), `allocated_days`,
  `used_days`, `source` (manual|generate|carry_forward|statutory),
  optional `carried_from_id` (partial unique
  `uq_leave_allocation_carried_from` where NOT NULL), `status`
  (submitted|approved|rejected|revoked), reason/decision metadata.
  CHECKs: period order, `allocated_days > 0`, `used_days >= 0`,
  status/source enums. gist EXCLUDE
  `exq_leave_allocation_no_overlap`
  `(employee_id WITH =, leave_type_id WITH =, daterange(period_start,
  period_end, '[]') WITH &&)` with **no WHERE clause** - every
  status blocks its window (the service mirrors this). Indexes:
  `ix_leave_allocation_employee_type`,
  `ix_leave_allocation_company_status`.
- `leave_requests` - `employee_id`, `leave_type_id`,
  `[start_date, end_date]` (inclusive), optional
  `start_time`/`end_time`, computed `days`, `reason`, single-file
  attachment columns (`attachment_path/name/mime/size/uploaded_by`),
  `status` (draft|submitted|approved|rejected|cancelled),
  `count_details` JSON snapshot, submitted/decided/cancelled
  metadata. CHECKs: date order, day bounds, status enum,
  times both-or-neither (`ck_leave_request_times_both_or_neither`)
  and only on a single day (`ck_leave_request_times_single_day`).
  gist EXCLUDE `exq_leave_request_no_overlap`
  `(employee_id WITH =, daterange(start_date, end_date, '[]') WITH &&
  ) WHERE status IN ('submitted','approved')` - drafts may coexist;
  rejected/cancelled history does not block. Indexes:
  `ix_leave_request_company_start`, `ix_leave_request_employee_start`,
  `ix_leave_request_company_status`, `ix_leave_request_company_type`.
- `leave_consumptions` - FIFO draw-down rows linking a request to the
  allocation period(s) it consumed (`days`, CHECK `> 0`). Indexes:
  `ix_leave_consumption_allocation`, `ix_leave_consumption_request`.
- `company_holidays` - company-scoped `date`, names, `status`
  active|inactive, `notes`; unique `uq_company_holiday_company_date`,
  CHECK `ck_company_holiday_status`.

EXCLUDE constraints use `btree_gist` (installed by frozen migration
0004; intentionally left in place, cluster-level object).

### 2.2 Permissions (25 new; 94 total)

Frozen `PHASE5_PERMISSIONS` tuple inside migration 0006:

- `leave_type.view/create/update/delete`
- `leave_allocation.view/create/update/delete/submit/approve/reject/carry_forward`
- `leave_request.view/create/update/delete/submit/approve/reject/cancel`
- `leave_balance.view`
- `leave_holiday.view/create/update/delete`

(Statutory rule endpoints deliberately reuse the `leave_type.*` code
family - no separate statutory codes.)

Role backfill (with GUC elevation for the 0002 guard): company_admin
(all 25), hr_manager (20 - all except `leave_type.delete`,
`leave_allocation.delete`, `leave_allocation.reject`,
`leave_request.delete`, `leave_holiday.delete`), hr_officer (11 -
`leave_type.view`, `leave_allocation.view/create/submit`,
`leave_request.view/create/update/submit/cancel`,
`leave_balance.view`, `leave_holiday.view`), auditor (the five view
codes only), employee (EXACTLY `leave_request.create/update/submit/
cancel` - nothing else). The exact expected sets are hardcoded in
`tests/test_leave_migrations_db.py::EXPECTED_LEAVE_GRANTS` and
asserted per role in `test_leave_security_db.py`.

D4: the migration creates an `Employee (Self Service)` role with
`code = employee` for every existing company (and grants it the four
codes above), so every default company ships with a working
self-service leave role.

### 2.3 RLS / tenant isolation

Six new tables join the frozen registry: **28 tables / 28
policies** total, each `ENABLE ROW LEVEL SECURITY` + `FORCE ROW
LEVEL SECURITY` with the standard `tenant_isolation` policy on
`company_id`, registered from `main.py`, `cli.py`, the migration
itself, the RLS module (`app/core/rls_phase5.py`), and the test
helpers. Cross-company references (type/allocation/request/holiday
lookups) resolve to `*_NOT_FOUND` rather than leaking existence.
Raw-SQL insert probes as `saudi_hr_user` are rejected by RLS (covered
in `test_leave_security_db.py` and the updated isolation tests).

## 3. API endpoints (all under `/api/v1`)

Leave types (`leave_type.*`):

- `GET/POST /leave-types` (list: `company_id`, `status`,
  `statutory_key`, `q`, paging)
- `GET/PATCH/DELETE /leave-types/{leave_type_id}`

Statutory rules (reuses `leave_type.*` codes):

- `GET/POST /leave-statutory-rules` (list: `company_id`,
  `statutory_key`, `as_of`, `status`, paging)
- `GET /leave-statutory-rules/{rule_id}`
- `POST /leave-statutory-rules/{rule_id}/deactivate` (optional
  reason)

Allocations (`leave_allocation.*`):

- `GET/POST /leave-allocations` (list: `company_id`, `employee_id`,
  `leave_type_id`, `status`, `period_from`/`period_to`, paging)
- `POST /leave-allocations/generate` - bulk allocate to active
  employees (optional `employee_ids`; `BULK_LIMIT = 500` employees
  per call)
- `POST /leave-allocations/carry-forward` - company + target period;
  carries unused days from eligible source allocations of every
  active type with `carry_forward_enabled`
- `GET/PATCH/DELETE /leave-allocations/{allocation_id}`
- `POST /leave-allocations/{allocation_id}/approve|reject`

Requests (router authenticates, service authorizes - self-scoped):

- `GET/POST /leave-requests` (list: `company_id`, `employee_id`,
  `leave_type_id`, `status`, `date_from`/`date_to`, `q`, paging)
- `POST /leave-requests/preview` - day count, balance projection and
  conflict probes without persisting
- `GET/PATCH/DELETE /leave-requests/{request_id}` (PATCH/DELETE only
  in `draft`)
- `POST /leave-requests/{request_id}/submit|approve|reject|cancel`
- `POST/GET/DELETE /leave-requests/{request_id}/attachment` -
  single optional file (validated like employee documents)

Balances (`leave_balance.view` / self):

- `GET /leave-balances?employee_id=...` (requires `employee_id`;
  optional `leave_type_id`, `as_of`, `period_start`/`period_end`)
- `GET /leave-balances/me` - any authenticated user, own balances

Company holidays (`leave_holiday.*`):

- `GET/POST /company-holidays` (list: `company_id`, `year`,
  `status`, paging)
- `GET/PATCH/DELETE /company-holidays/{holiday_id}`

## 4. Business rules

### Day counting (`app/leave/day_counting.py`)

- Two modes per type: `working_days` (default) counts days whose
  resolved schedule has any working time; `calendar_days` counts
  every date in the inclusive span.
- Resolution goes through the Phase-4 `resolve_employee_schedule`
  (assignment -> schedule day -> shift/breaks). **A date with NO
  resolved schedule still counts** in both modes (it has no working
  time but also no rule that excludes it); a PARTIAL-day request
  (times provided) whose date has no schedule raises
  `LEAVE_NO_SCHEDULE` because the minutes cannot be apportioned.
- Overnight working windows are handled in offset space and clipped
  to the day; unpaid breaks reduce the working minutes of the day.
- `MAX_SPAN_DAYS = 366`: a single request may span at most one
  calendar year of days (`LEAVE_REQUEST_INVALID_DAYS`).
- Half-day/`start_time`+`end_time` requests must be both-or-neither
  and within a single date (`LEAVE_REQUEST_INVALID_TIMES`).
- Company holidays on the requested dates are excluded from
  `working_days` counts.
- The counted result is snapshotted into `leave_requests.days` and
  `count_details` at create/update/submit time.

### Balance engine (`app/leave/balance.py`, single shared engine)

- Derived only (D3): `allocated` = SUM of counted allocations'
  `allocated_days`; `used` = SUM of **all** consumptions on counted
  allocations (rejected/revoked allocations contribute 0); `pending`
  = days of submitted requests (excluded from `remaining`);
  `remaining` = allocated - used - pending.
- Allocation periods are counted when they overlap the query period
  and are ordered `period_start, id` (FIFO).
- `ensure_balance` runs at request submit/approve; consumption draws
  down allocations FIFO via `consume_fifo` (oldest period first).
  `negative_balance_allowed` types may go below zero; others raise
  `LEAVE_INSUFFICIENT_BALANCE`.
- Cancelling an approved request releases its consumptions back to
  the allocations.

### Request workflow

- Transitions (`_transition_guard`): PATCH and DELETE only in
  `draft`; submit from `draft`; approve/reject from `submitted`;
  cancel from `draft`/`submitted`/`approved`. Wrong transitions raise
  `LEAVE_REQUEST_STATE_INVALID`.
- Submit re-validates everything (active type, reason, attachment,
  day limits, overlap, balance) and takes the row lock
  (FOR UPDATE); approve/reject/cancel also lock, so concurrent
  decisions resolve to a single winner.
- If `leave_type.requires_approval` is FALSE the submit handler
  auto-approves inline (`_approve_core(auto=True)`, audit mode
  `"auto"` vs `"manual"`), so employees get instant approval without
  any approver permission.
- Overlap: pre-check + gist-constraint backstop -> 
  `LEAVE_REQUEST_OVERLAP` (only submitted/approved block).
- Approve blocks while the employee has an OPEN attendance record on
  the leave dates (`LEAVE_ATTENDANCE_OPEN_CONFLICT`); cancel of an
  approved request blocks when ANY attendance record exists on those
  dates (`LEAVE_ATTENDANCE_RECORD_EXISTS`); approved overtime on a
  full-fraction counted date also blocks approval
  (`LEAVE_OVERTIME_CONFLICT`).
- Reject requires a non-empty reason (`LEAVE_DECISION_REASON_REQUIRED`);
  cancel/approve reasons are optional.

### Allocations

- Create lands in `approved` when the type has
  `allocation_requires_approval = false` (default), otherwise
  `submitted`. There is no draft state; `POST .../submit` is an
  idempotent no-op on `submitted` rows (design decision - the state
  machine enters `submitted` directly at creation).
- Update requires `approved` with `used_days = 0`; approve/reject
  only from `submitted`; reject requires a reason. Delete is allowed
  in any status but is refused once consumed
  (`LEAVE_ALLOCATION_IN_USE`).
- Overlap pre-check + gist EXCLUDE backstop (ALL statuses block) ->
  `LEAVE_ALLOCATION_OVERLAP`.
- Carry-forward eligibility is configuration, not law:
  `carry_forward_expiry = none` (any prior period), `end_of_year`
  (source must end in the previous calendar year), `end_of_next_year`
  (source must end within 366 days before the target starts).
  Sources are capped at `carry_forward_max_days`; every generated row
  records `carried_from_id` (partial unique index guarantees one
  carry per source).
- Bulk generate/carry-forward are limited to `BULK_LIMIT = 500`
  employees per call.

### Statutory rules

- Windows are half-open `[effective_from, effective_to)` with
  NULL = open-ended; adjacent versions are legal, overlaps rejected
  (`STATUTORY_RULE_OVERLAP` on the service pre-check, gist EXCLUDE as
  backstop). Creating a version for an already-covered window bumps
  `version` per `(company, key)` uniqueness.
- `source_reference` is mandatory and non-empty at the DB level
  (`ck_leave_statutory_rule_source`,
  `STATUTORY_RULE_SOURCE_REQUIRED`); `requires_legal_verification`
  defaults to true and stays until an operator clears it - no
  statutory day values are seeded or implied (D2).
- Deactivation (`POST .../deactivate`) sets `status = inactive` with
  an optional reason; already-inactive rules return 409.

### Leave types / holidays / attachments

- Deleting a type that is referenced fails with
  `LEAVE_TYPE_IN_USE`; using an inactive type fails with
  `LEAVE_TYPE_INACTIVE`.
- Attachment rules are type-driven: `requires_attachment` (always)
  or a `attachment_threshold_days` threshold -> upload required
  before submit (`LEAVE_REQUEST_ATTACHMENT_REQUIRED`); reason rule ->
  `LEAVE_REQUEST_REASON_REQUIRED`. Uploads validate size/MIME like
  employee documents and are allowed while `draft`/`submitted`.
- Holidays are unique per `(company, date)` (`HOLIDAY_EXISTS`) and
  factor into day counting.

### Authorization model

- Roleless (service-level) routes: every `/leave-requests*` route -
  the router only authenticates; the service checks self
  (employee_id == own linked employee) or the equivalent view/verb
  permission. Self-fallback also applies to list filters.
- Permission-gated routes: `/leave-types`, `/leave-statutory-rules`,
  `/leave-allocations`, `/leave-balances`, `/company-holidays`.
- No hardcoded role names anywhere in backend or frontend - only
  permission codes (`can(...)` / `require_permission(...)`).

### Error codes (33 new, stable, translated by frontend `error.<CODE>`)

`LEAVE_TYPE_NOT_FOUND`, `LEAVE_TYPE_CODE_EXISTS`,
`LEAVE_TYPE_IN_USE`, `LEAVE_TYPE_INACTIVE`,
`LEAVE_TYPE_INVALID_RANGE`, `STATUTORY_RULE_NOT_FOUND`,
`STATUTORY_RULE_OVERLAP`, `STATUTORY_RULE_SOURCE_REQUIRED`,
`STATUTORY_RULE_INVALID_DATE_RANGE`, `LEAVE_ALLOCATION_NOT_FOUND`,
`LEAVE_ALLOCATION_OVERLAP`, `LEAVE_ALLOCATION_INVALID_DAYS`,
`LEAVE_ALLOCATION_STATE_INVALID`, `LEAVE_ALLOCATION_IN_USE`,
`LEAVE_CARRY_FORWARD_INVALID`, `LEAVE_REQUEST_NOT_FOUND`,
`LEAVE_REQUEST_OVERLAP`, `LEAVE_REQUEST_INVALID_RANGE`,
`LEAVE_REQUEST_INVALID_TIMES`, `LEAVE_REQUEST_INVALID_DAYS`,
`LEAVE_REQUEST_STATE_INVALID`,
`LEAVE_REQUEST_ATTACHMENT_REQUIRED`,
`LEAVE_REQUEST_REASON_REQUIRED`, `LEAVE_DECISION_REASON_REQUIRED`,
`LEAVE_INSUFFICIENT_BALANCE`, `LEAVE_ONLY_NON_WORKING_DAYS`,
`LEAVE_NO_SCHEDULE`, `LEAVE_EMPLOYEE_NOT_ACTIVE`,
`LEAVE_ATTENDANCE_OPEN_CONFLICT`, `LEAVE_ATTENDANCE_RECORD_EXISTS`,
`LEAVE_OVERTIME_CONFLICT`, `HOLIDAY_NOT_FOUND`, `HOLIDAY_EXISTS`.

## 5. Audit logging

21 distinct Phase-5 audit actions (all through the frozen
`record_audit` helper with ip/actor/company):

- `leave_type.create/update/delete`
- `leave_statutory_rule.create/deactivate`
- `leave_allocation.create/update/delete/approve/reject/carry_forward`
  (bulk generate audits `leave_allocation.create` per row plus a
  summary row)
- `leave_request.create/update/delete/submit/approve/reject/cancel`
  (attachment upload/remove audit as `leave_request.update` with
  `{"fields": ["attachment"]}` / `["attachment_removed"]`)
- `leave_holiday.create/update/delete`

Auto-approved requests audit `leave_request.approve` with the reason
`"auto"` and the auto flag; reject/cancel record the reason and the
full before/after snapshots. Audit-log visibility remains
`audit.read`.

## 6. Frontend

- `api.ts`: Phase-5 types (leave type, statutory rule, allocation,
  request, balance line, preview, holiday) and helpers for every
  endpoint above, including attachment upload (multipart) and
  download (Content-Disposition filename parsing).
- `pages/LeaveRequestsPage.tsx`: filters (employee via debounced
  `SearchSelect`, leave type, status, date range), create/edit of
  drafts (employee, type, dates, optional times, reason), a
  Preview button calling `/leave-requests/preview` (counted days,
  counting mode, remaining balance, negative/attendance/overtime
  warnings), status-driven submit/approve/reject/cancel/delete
  actions gated by `leave_request.*` codes, and per-row attachment
  upload/download/remove (visible while draft/submitted).
- `pages/LeaveAllocationsPage.tsx`: filters (employee, type,
  status), manual create/edit (approved rows with no usage),
  bulk generate form (empty employee selection = all active
  employees, hint text), carry-forward form (target period),
  approve/reject/delete actions; status/source badges.
- `pages/LeaveTypesPage.tsx`: full leave-type configuration form
  (all booleans, enums, thresholds, carry-forward policy, statutory
  key) + list with server-side status/statutory-key filters, plus a
  statutory-rules section (list, create with source reference +
  `rule_json` textarea + legal-verification checkbox, deactivate).
- `pages/LeaveBalancesPage.tsx`: employee picker, leave-type and
  `as_of` filters, allocated/used/pending/remaining table
  (`GET /leave-balances` requires `employee_id` by design; 422
  otherwise).
- `pages/LeaveHolidaysPage.tsx`: year/status filters + CRUD for
  company holidays.
- `components/LeavePanel.tsx` + Employee Detail "Leave" tab:
  balances (via `leave_balance.view`, or `/leave-balances/me` for a
  user's own record) and the employee's recent requests with
  self-service submit/cancel; tab visible with
  `leave_request.view || leave_balance.view`.
- `App.tsx`: routes `/leave-requests`, `/leave-allocations`,
  `/leave-types`, `/leave-balances`, `/leave-holidays` with nav
  entries gated by `leave_request.view|create`,
  `leave_allocation.view`, `leave_type.view`, `leave_balance.view`,
  `leave_holiday.view` (permission codes only - no role names
  anywhere in the frontend).
- `i18n.ts`: full EN + AR key sets (nav, page vocabulary, both
  workflow status maps, source/day-counting/expiry/allowance enums,
  statutory vocabulary, all 33 error codes) - **541 keys per
  locale**, 415 statically used, verified symmetric by an automated
  key audit. Arabic cells render with `dir="rtl"`; document direction
  follows the locale toggle.

## 7. Design refinements (decided during implementation)

(a) `used` counts ALL consumptions on counted allocations (not just
those of a specific request); (b) `exq_leave_allocation_no_overlap`
has NO WHERE clause - every allocation status blocks its window;
(c) allocation submit is idempotent (no-op while `submitted`);
(d) dates with NO resolved schedule still COUNT toward
working/calendar days; only a partial-day request without a schedule
raises `LEAVE_NO_SCHEDULE`; (e) statutory endpoints reuse the
`leave_type.*` permission codes; (f) request authorization uses a
self-scoping helper - the verb alone for own requests, verb +
`leave_request.view` for others, with a list self-fallback via
`leave_request.create`, and `/leave-balances` requires an
`employee_id` query parameter (422 without) while `/leave-balances/me`
is for any authenticated user; (g) `MAX_SPAN_DAYS = 366` and
`BULK_LIMIT = 500`; (h) approval blocks OPEN attendance only, cancel
blocks ANY attendance record, overtime conflicts block only on
full-fraction counted dates; (i) auto-approval happens inline inside
submit when `requires_approval = false` (audit `mode: "auto"` vs
`"manual"`); (j) every overlap uses a service pre-check plus the gist
IntegrityError backstop mapped to `LEAVE_REQUEST_OVERLAP` /
`LEAVE_ALLOCATION_OVERLAP`; (k) request/allocation periods are
INCLUSIVE `'[]'` ranges while statutory windows are half-open
`[from, to)` with NULL-open ends; (l) deleting a referenced type is
409 `LEAVE_TYPE_IN_USE`, and using an inactive type is 409
`LEAVE_TYPE_INACTIVE`.

## 8. Tests

76 new tests in 10 files (total 445 = 369 frozen + 76):

| File | Tests | Focus |
|---|---|---|
| `test_leave_types_db.py` + `test_leave_allocations_db.py` | 18 | type CRUD/validation, allocation CRUD, overlap constraint (all statuses), generate, carry-forward eligibility, in-use guards, audits |
| `test_leave_requests_db.py` | 9 | request CRUD, transitions, overlap guards, attachment rules, delete draft only, audits |
| `test_leave_balance_db.py` | 8 | derived allocated/used/pending/remaining, FIFO consumption, negative-balance rules, release on cancel |
| `test_leave_daycount_db.py` | 6 | working vs calendar days, no-schedule counting, partial-day no-schedule error, holidays, span cap |
| `test_leave_approvals_db.py` | 6 | approve/reject/cancel with attendance + overtime conflict guards, auto-approve inline path |
| `test_leave_security_db.py` | 7 | permission matrix per role (incl. exact 4-code employee set), self-scoped request access, raw RLS insert probes |
| `test_leave_concurrency_db.py` | 3 | overlapping-submit race (single winner), double-approve race (FOR UPDATE), overlapping-allocation-create race |
| `test_leave_migrations_db.py` | 8 | head chain -> `0006_phase5_leave`, 94 permissions, exact 25-code grants per role, constraints/indexes present, downgrade to 0005 + re-upgrade roundtrip |
| `test_leave_schemas_unit.py` | 11 | pydantic validation (enums, bounds, date/times pairing), pagination shapes |

Adapted (no test-count change): `conftest.py` (phase5 table hide +
TRUNCATE list), `test_rls_unit.py` (28 tables/policies),
`test_isolation_db.py` (22 -> 28 tables), `test_api_offline.py`
(phase 5, Phase-5 OpenAPI paths), `test_phase2_migrations_db.py` /
`test_phase3_migrations_db.py` (head chain -> `0006_phase5_leave`,
94 permissions).

## 9. Verification results

- `pytest -q`: **445 passed** (0 failed).
- `ruff check .`: clean (no noqa suppressions added).
- `npm run build` (tsc -b + vite): clean.
- `alembic check`: clean on `saudi_hr_test` ("No new upgrade
  operations detected").
- Migration 0006 downgrade to `0005` then upgrade to `head` on
  `saudi_hr_test`: success (exercised in the migration tests).
- Frozen SHA-256 hashes of 0001-0005 re-verified byte-identical
  after the phase.
- psql as `saudi_hr_user`: 28 tables RLS enabled + forced, 28
  policies, 94 permissions (25 Phase-5), EXCLUDE/partial-unique
  indexes present.
- i18n key audit: 415 statically used keys, 541 EN keys = 541 AR
  keys, 0 missing.
- Permission audit: exact expected code sets per role asserted in
  tests (company_admin 25/25, hr_manager 20, hr_officer 11, auditor
  5, employee exactly 4); no role names referenced in backend routes
  or frontend code.
- Git: 0 commits, nothing staged (unchanged by this phase).

## 10. Known limitations / deferred items

- **Dev database not migrated**: `saudi_hr` is still at head 0005.
  `alembic upgrade head` must be run by the operator before using
  Phase-5 features locally (deliberately not run here).
- **Decisions use native prompts**: approve/reject/cancel and
  deactivate reasons use `window.prompt`/`window.confirm` rather
  than modal forms (same approach as Phase 4 overtime).
- **Generate form has no employee picker**: the API accepts
  `employee_ids`, but the UI always generates for ALL active
  employees (hint text explains this); per-employee selection is a
  client-side follow-up.
- **Single attachment per request** (by design); no multi-file or
  replacement while `approved`.
- **`rule_json` edited as raw JSON text** in the statutory rules
  form (validated client-side and by pydantic); no structured rule
  builder.
- **No automation**: carry-forward, carry-forward expiry and
  `requires_legal_verification` clearing are operator-driven; no
  scheduler ships in this phase (per scope).
- **No statutory or public-holiday seed data** (D1/D2): holidays and
  statutory citations are entered per company; nothing implies
  Saudi statutory entitlements.
- **Balances are point-in-time**: no historical balance ledger -
  `as_of` filters current allocations/consumptions by period, it
  does not replay history.
- **No leave calendar view**: lists are server-side filtered tables
  only; no month grid or team-coverage view.
