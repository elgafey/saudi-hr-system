# Phase 6 - Payroll & Salary Management

Salary component catalog, employee salary assignments, payroll
periods with a single workflow state machine, deterministic payroll
calculation (runs, run lines, payslips), payroll adjustments,
installment deductions, payroll statutory rules with mandatory source
citations, and the accounting export.
Builds on Phase 1 (foundation), Phase 2 (employee master data),
Phase 3 (employee lifecycle), Phase 4 (attendance, schedules, shifts,
overtime), and Phase 5 (leave management).

Status: complete. Backend **652 tests passing** (445 frozen + 207 new
Phase-6 tests), `ruff check` clean, `alembic check` clean, frontend
builds clean (`tsc -b && vite build`), i18n EN/AR symmetric at 693
keys per locale, migration 0007 applied and round-trip verified
(downgrade to 0006 and re-upgrade) on the test database
(`saudi_hr_test`). The dev database (`saudi_hr`) is still at head
`0004_phase3_employee_lifecycle` - it was NOT migrated during this
phase (or any earlier phase run here); `alembic upgrade head` on
`saudi_hr` is an operator action, deliberately not run.

## 1. Scope

- Salary components: per-company catalog (code, EN/AR names, category
  `earning|deduction|employer_contribution`, calculation basis
  `fixed|percent_of_basic|engine_derived`, default amount/rate,
  statutory flag + key, status, sort order).
- Salary assignments: the payroll source of truth for pay - one open
  `[effective_from, effective_to)` window per employee (half-open,
  NULL = open), basic salary, currency, reason. Creating a new window
  auto-closes the current open row (history is never overwritten).
  A `POST /salary-assignments/seed` helper creates initial assignments
  from employment contracts (existing windows are skipped).
- Payroll periods: monthly-style windows with ONE workflow state
  machine - `draft -> calculated -> reviewed -> approved -> paid ->
  locked` (D2 amendment: the state lives on the period, never on the
  run).
- Payroll runs: calculation artifact per period with a monotonic
  `run_number` per company, `active|void|superseded` status ONLY,
  `input_snapshot` + `inputs_hash` + `engine_version` (currently
  `1.0.0`), company totals and warnings. Exactly one `active` run per
  period (partial unique index); recalculation replaces the active
  artifact's lines in place.
- Run lines ARE the payslips: `payroll_run_lines` holds the per-
  employee snapshot (basic, earnings/deductions/employer totals, net
  pay, worked/overtime minutes, leave/absent days, warnings) and
  `payslip_lines` holds the itemized component lines. The payslip API
  reads a run line (`GET /payslips/{run_line_id}`).
- Adjustments: company-entered earning/deduction corrections against
  an OPEN period only (draft/calculated/reviewed) - approved
  adjustments are included in the next calculation. Decisions
  (`approve|reject|void`) require an explicit permission each.
- Deductions: effective-dated installment rules (fixed amount per
  period, optional total with a `remaining_amount` balance) consumed
  EXACTLY ONCE at `APPROVE` in deterministic order - calculation never
  mutates remaining amounts.
- Payroll statutory rules: versioned, non-overlapping effective
  windows per statutory key with a mandatory `source_reference`,
  `source_date` and `requires_legal_verification` (DB default true).
  No Saudi statutory/legal values are seeded or hardcoded anywhere
  (D4); the company enters its own cited rules.
- Frontend: six nav-gated pages (Payroll Periods, Payroll Run detail,
  Salary Components, Salary Assignments, Payroll Adjustments, Payroll
  Deductions, Payroll Statutory Rules) plus an Employee Detail
  "Compensation" tab.

Out of scope (unchanged): GOSI/tax filing, payslip PDF rendering,
notifications, schedulers, bank file formats, accounting postings,
self-service payslip portal, Phase 7. `AccountingExport` is a
structured JSON payload only - posting is a later concern.

## 2. Database (migration `0007_phase6_payroll`)

Never modify 0001-0006. Frozen SHA-256 hashes (re-verified this
phase, byte-identical):

| Migration | SHA-256 |
|---|---|
| `0001_phase1` | `5fe83204197a9ffcba377181188a1141fcbaafbc0606490b92ce699150d53e30` |
| `0002_security_hardening` | `2a6bc5292832040757409f42f2ba26ef565539cb671ae11003020f4a458aef8d` |
| `0003_phase2_employee_master_data` | `d5aae7696cb5fc15a0c8ea0e2bd6599375a5c2fb8b596c61fc2eb5d18e5ba324` |
| `0004_phase3_employee_lifecycle` | `798a87c0d92312866a7fa8480d74fd670fa04a43453819eedf4d2f115ffc921a` |
| `0005_phase4_attendance` | `1d3c7d91996c73f6994603d917956753cc9f5261c6bc6eab5f033e380a6297e` |
| `0006_phase5_leave` | `5681ca44c38eed5e08328d8297034dd795202d31c28d22286b160101cf31db7e` |
| `0007_phase6_payroll` | `dd3b88005771d1883fd3f12f01945e87af3a007788ca0776fd83b7ef1c4b9bd0` |

File name is `0007_phase6_payroll.py` and the revision **id** is
`0007_phase6_payroll`. `down_revision = 0006_phase5_leave`. Downgrade
to 0006 and re-upgrade were exercised on `saudi_hr_test` (inside
`test_payroll_migrations_db.py` and interactively).

### 2.1 Tables (10 new; all company-scoped, RLS enabled + forced)

- `salary_components` (17 cols) - code, `name_ar`/`name_en`,
  `category` (`earning|deduction|employer_contribution`),
  `calculation_basis` (`fixed|percent_of_basic|engine_derived`),
  `default_amount`/`default_rate` (NUMERIC), `is_statutory` +
  `statutory_key`, `status` active|inactive, `sort_order`. Unique
  `uq_salary_component_company_code`; CHECKs cover category, basis,
  status, non-negative amounts; index `ix_salary_component_company_status`.
- `employee_salary_assignments` (11 cols) - `employee_id`,
  `[effective_from, effective_to)` half-open window (NULL = open),
  `basic_salary` NUMERIC > 0, `currency`, `reason`. Partial unique
  `uq_salary_assignment_open` (`WHERE effective_to IS NULL`), gist
  EXCLUDE `exq_salary_assignment_no_overlap`
  `(employee_id WITH =, daterange(effective_from, effective_to, '[)')
  WITH &&)`; indexes `ix_salary_assignment_employee_from`,
  `ix_salary_assignment_company_from`.
- `salary_assignment_components` (8 cols) - optional per-assignment
  component overrides (`assignment_id`, `component_id`, `amount`,
  `rate`); unique `uq_salary_assignment_component`. Populated by the
  seed flow where contract data carries component values; otherwise
  components fall back to the catalog defaults.
- `payroll_periods` (21 cols) - `name`, `[period_start, period_end]`,
  `currency`, `status` (`draft|calculated|reviewed|approved|paid|
  locked`), `*_at`/`*_by` audit columns for each transition
  (calculated/reviewed/approved/paid/locked), `notes`. Unique
  `uq_payroll_period_company_range`, gist EXCLUDE
  `exq_payroll_period_no_overlap`
  `(company_id WITH =, daterange(period_start, period_end, '[)') WITH
  &&)`; indexes `ix_payroll_period_company_status`,
  `ix_payroll_period_company_start`; CHECKs cover status enum and
  date order.
- `payroll_runs` (22 cols) - `period_id`, `run_number`, `status`
  (`active|void|superseded` ONLY - it is NOT a workflow machine),
  `input_snapshot` JSON, `inputs_hash` (lowercase SHA-256 hex),
  `engine_version`, `employee_count`, `gross_total`,
  `deductions_total`, `employer_total`, `net_total` (all NUMERIC >= 0
  with CHECKs), `warnings` JSON, void metadata. Unique
  `uq_payroll_run_company_number`, partial unique
  `uq_payroll_run_active` (`WHERE status = 'active'`); index
  `ix_payroll_run_company_period`.
- `payroll_run_lines` (19 cols) - per-employee snapshot: `basic_snapshot`,
  `currency`, `earnings_total`/`deductions_total`/`employer_total`/
  `net_pay`, `worked_minutes`, `overtime_minutes`, `paid_leave_days`,
  `unpaid_leave_days`, `absent_days`, `late_minutes`, per-line
  `warnings` JSON. Unique `uq_payroll_run_line_employee`
  `(run_id, employee_id)`; CHECKs on non-negative totals.
- `payslip_lines` (14 cols) - itemized lines: `run_line_id`,
  `component_id` (nullable for engine-derived lines), `line_type`
  (`earning|deduction|employer_contribution`), `label_ar`/`label_en`,
  `unit` (`amount|minutes|days|percent`), `quantity`/`rate`/`amount`
  NUMERIC, `sort_order`. Index `ix_payslip_line_run_line`.
- `payroll_deduction_rules` (15 cols) - `employee_id`, `name`,
  `amount` (> 0), optional `total_amount` + `remaining_amount`
  (installment balance), `[effective_from, effective_to)`,
  `status` (`active|completed|cancelled`), `reason`. CHECKs on amount,
  status and date order; indexes `ix_payroll_deduction_employee`,
  `ix_payroll_deduction_company_status`.
- `payroll_adjustments` (19 cols) - `employee_id`, `period_id`,
  optional `original_run_id` (corrections reference the originating
  run), `component_id`, `amount` (> 0), `direction`
  (`earning|deduction`), `reason` (required), `status`
  (`draft|pending|approved|rejected|void`), decision/void metadata.
  CHECKs on amount, direction, status; indexes
  `ix_payroll_adjustment_company_status`, `ix_payroll_adjustment_period`.
- `payroll_statutory_rules` (16 cols) - mirrors the Phase-5 leave
  pattern: `statutory_key`, server-set `jurisdiction`, monotonic
  `version` per `(company_id, statutory_key)` (unique
  `uq_payroll_statutory_rule_version`), half-open window (NULL = open),
  `rule_json`, mandatory non-empty `source_reference`, `source_date`,
  `requires_legal_verification` (DB default **true**), `notes`,
  `status` active|inactive. gist EXCLUDE
  `exq_payroll_statutory_rule_no_overlap`
  `(company_id WITH =, statutory_key WITH =, daterange(effective_from,
  effective_to, '[)') WITH &&)`; index
  `ix_payroll_statutory_rule_company_key`.

EXCLUDE constraints use `btree_gist` (installed by frozen migration
0004). All money columns are NUMERIC - no floats anywhere (D3).

### 2.2 Permissions (28 new; 122 total)

Frozen `PHASE6_PERMISSIONS` tuple inside migration 0007 (asserted to
equal `PAYROLL_CODES` in the catalog by tests):

- `salary_component.view/create/update/deactivate`
- `salary_assignment.view/create/update`
- `payroll_period.view/create/update`
- `payroll_run.view/calculate/review/approve/mark_paid/lock`
- `payroll_adjustment.view/create/approve/reject/void`
- `payroll_deduction.view/create/update`
- `payroll_statutory_rule.view/create/deactivate`
- `payroll_export.execute`

Role backfill: company_admin **28/28**, hr_manager **28/28**,
hr_officer **19** (all except `salary_component.deactivate`,
`payroll_run.approve/mark_paid/lock`,
`payroll_adjustment.approve/reject/void`,
`payroll_statutory_rule.create/deactivate`), auditor **8** (the
seven `.view` codes plus `payroll_export.execute`), employee **0**
(payroll never self-serves). Exact expected sets are asserted per
role in `tests/test_payroll_security_db.py` and
`tests/test_payroll_migrations_db.py`.

### 2.3 RLS / tenant isolation

Ten new tables join the frozen registry: **38 tables / 38 policies**
total (verified on `saudi_hr_test`), each `ENABLE ROW LEVEL SECURITY`
+ `FORCE ROW LEVEL SECURITY` with the standard `tenant_isolation`
policy on `company_id`, registered from `main.py`, `cli.py`, the
migration, `app/core/rls_phase6.py`, and the test helpers. Cross-
company references resolve to `*_NOT_FOUND`; raw-SQL probes as
`saudi_hr_user` are rejected (covered in `test_payroll_rls_db.py`
and `test_payroll_security_db.py`).

## 3. API endpoints (all under `/api/v1`)

Salary components (`salary_component.*`):

- `GET/POST /salary-components` (list: `company_id`, `category`,
  `status`, `q`, paging)
- `GET/PATCH /salary-components/{component_id}`
- `POST /salary-components/{component_id}/deactivate`

Salary assignments (`salary_assignment.*`):

- `GET/POST /salary-assignments` (list: `company_id`, `employee_id`,
  `as_of`, paging)
- `POST /salary-assignments/seed?company_id=` - create initial
  assignments from employment contracts (idempotent skip)
- `GET/PATCH /salary-assignments/{assignment_id}`

Payroll periods (workflow - `payroll_period.*` / `payroll_run.*`):

- `GET/POST /payroll-periods` (list: `company_id`, `status`, paging)
- `GET/PATCH /payroll-periods/{period_id}` (PATCH: `name`, `notes`)
- `POST /payroll-periods/{period_id}/calculate` (`payroll_run.calculate`)
  -> returns the run
- `POST /payroll-periods/{period_id}/review|approve|mark-paid|lock`

Payroll runs (`payroll_run.view` / `payroll_export.execute`):

- `GET /payroll-runs` (list: `company_id`, `period_id`, paging)
- `GET /payroll-runs/{run_id}`
- `GET /payroll-runs/{run_id}/lines` (paged run lines)
- `POST /payroll-runs/{run_id}/recalculate`
  (`payroll_run.calculate`)
- `GET /payroll-runs/{run_id}/export` (`payroll_export.execute`) -
  structured accounting payload
- `GET /payslips/{run_line_id}` - full itemized payslip

Adjustments (`payroll_adjustment.*`):

- `GET/POST /payroll-adjustments` (list: `company_id`, `period_id`,
  `employee_id`, `status`, paging)
- `GET /payroll-adjustments/{adjustment_id}`
- `POST /payroll-adjustments/{adjustment_id}/approve|reject|void`

Deductions (`payroll_deduction.*`):

- `GET/POST /payroll-deductions` (list: `company_id`, `employee_id`,
  `status`, paging)
- `GET/PATCH /payroll-deductions/{deduction_id}`

Payroll statutory rules (`payroll_statutory_rule.*`):

- `GET/POST /payroll-statutory-rules` (list: `company_id`,
  `statutory_key`, `as_of`, `status`, paging)
- `GET /payroll-statutory-rules/{rule_id}`
- `POST /payroll-statutory-rules/{rule_id}/deactivate`

## 4. Business rules

### Single workflow state machine (D2 amendment)

- `payroll_periods.status` is the ONLY workflow machine:
  `draft -> calculated -> reviewed -> approved -> paid -> locked`
  (`PERIOD_TRANSITIONS` in `service.py` guards every action; wrong
  transitions raise `PAYROLL_PERIOD_STATE_INVALID`).
- `payroll_runs.status` is a lifecycle flag only:
  `active|void|superseded`. Runs never carry workflow state, and
  recalculation keeps the workflow on the period - there is no second
  state machine and no duplicated transition logic.
- Calculate/recalculate is allowed from `draft`, `calculated`,
  `reviewed` only, always returns the period to `calculated`
  (approved Phase 6 rule), and replaces the active run's lines in
  place; the period row itself is immutable after `calculated`
  except via the workflow actions (name/notes edits before calculate).
- Corrections to `approved`/`paid`/`locked` periods are refused
  (`PAYROLL_IMMUTABLE`); an adjustment may only target an OPEN period
  (`draft|calculated|reviewed`), so corrections are posted to the
  NEXT open period and can reference `original_run_id`.

### Calculation engine (`app/payroll/engine.py`, version `1.0.0`)

- Money is Decimal end-to-end (D3): every payslip line is quantized
  to `0.01` with `ROUND_HALF_UP` (the only rounding in payroll) and
  period totals are the SUMS of those rounded lines - no intermediate
  rounding, no floats anywhere (verified: zero `float(` in payroll
  code).
- Proration: calendar-day by default - a partial-month basic
  segment = `monthly * days_in_window / calendar_days_of_month`;
  Daily Rate = Monthly / calendar days (unpaid leave uses the
  configurable `daily_divisor`, default `30`, taken from the payroll
  statutory rule, never hardcoded per country).
- Overtime: computed ONLY from the company's payroll statutory rule
  (`overtime_rate_percent`, `days_per_month`, `hours_per_day` read
  from `rule_json`) - the engine contains NO hardcoded 30/8/50%
  values. Missing/unverified rule while OT minutes exist emits a
  `STATUTORY_RULE_MISSING`/unverified WARNING and blocks approval.
- Inputs snapshot: `build_inputs(...)` collects Phase 4/5/6 data
  (attendance, overtime, leave, salary assignments, adjustments,
  deduction rules, statutory rules) into `input_snapshot`; the engine
  also emits `warnings` (open attendance, missing rules, missing
  salary assignment) and `blocking_warnings` are checked at APPROVE.
- OPEN attendance in the period blocks calculation
  (`PAYROLL_ATTENDANCE_OPEN`); no salary assignment for an employee
  in the period blocks that employee's line
  (`PAYROLL_NO_SALARY_ASSIGNMENT`).
- Approved adjustments are included in the calculation (direction
  adds/subtracts from net); DEDUCTIONS ARE NOT - installment
  deductions are consumed EXACTLY ONCE at APPROVE
  (`_consume_deduction_rules`, deterministic `(effective_from, id)`
  order, row-locked, `remaining_amount` floored at `0.00`, row flips
  to `completed` when exhausted).

### Input-hash approval protection

- Every calculate stores `inputs_hash = sha256(canonical snapshot)`;
  APPROVE re-builds the CURRENT inputs and compares
  (`PAYROLL_INPUTS_CHANGED` on mismatch - attendance, overtime,
  leave, salaries, deductions, adjustments or statutory rules changed
  after calculation). Covered by
  `test_calculate_creates_run_lines_and_hash`,
  `test_inputs_changed_blocks_approve`, and five snapshot-hash engine
  unit tests (determinism, key-order independence, content
  sensitivity, engine-version sensitivity, lowercase hex format).

### Approve guards

- Only `reviewed` periods can be approved; requires an active run
  with `inputs_hash`; rebuild-hash mismatch -> `PAYROLL_INPUTS_CHANGED`;
  blocking warnings (missing/unverified statutory rules) ->
  `PAYROLL_STATUTORY_RULE_UNVERIFIED`; then deductions are consumed
  and the period moves to `approved`. Rows are fetched `FOR UPDATE`,
  so concurrent approvals resolve to a single winner.

### Salary assignments

- One OPEN window per employee (`uq_salary_assignment_open` + service
  pre-check); creating a new window closes the current open row in
  the same transaction (the gist EXCLUDE sees the updated range only
  after the close, handled by ordering the UPDATE before the INSERT).
- Historical windows are immutable
  (`test_assignment_historical_immutable`); overlap of half-open
  windows -> `PAYROLL_ASSIGNMENT_OVERLAP` (service pre-check +
  constraint backstop).
- `POST /seed` creates assignments from `employee_contracts.basic_salary`
  for active employees lacking an open window (audit
  `salary_assignment.seed`).

### Adjustments / deductions / statutory rules

- Adjustment lifecycle: `draft/pending -> approved|rejected`, `void`
  from `draft|pending|approved`; each verb has its own permission
  (`approve|reject|void`) and audits its own action. Amount > 0,
  reason required, target period must be open.
- Deduction rules: create (`active`), update amount/window/status;
  the remaining balance is only decremented by APPROVE-time
  consumption, never by calculation.
- Payroll statutory rules mirror Phase 5: half-open windows, version
  bump per `(company, key)`, mandatory non-empty `source_reference`
  at DB level (`PAYROLL_STATUTORY_RULE_SOURCE_REQUIRED`),
  `requires_legal_verification` defaults true, overlap ->
  `PAYROLL_STATUTORY_RULE_OVERLAP` (pre-check + EXCLUDE backstop),
  deactivation sets `status = inactive`. No official values ship with
  the product - only what the operator cites (D4).

### Authorization model

- Roleless in code: no route or frontend branch ever references a
  role name - only permission codes (`require_permission(...)` /
  `can(...)`) (verified by audit; the only role-name occurrences are
  the permission GRANT data in `app/permissions/catalog.py` and the
  migration backfill, as in previous phases).
- `list` endpoints scope by company (403 on mismatch), detail
  endpoints 404 cross-company, export requires
  `payroll_export.execute`.

### Error codes (28 new, stable, translated by frontend `error.<CODE>`)

`SALARY_COMPONENT_NOT_FOUND`, `SALARY_COMPONENT_CODE_EXISTS`,
`SALARY_COMPONENT_IN_USE`, `SALARY_ASSIGNMENT_NOT_FOUND`,
`SALARY_ASSIGNMENT_OVERLAP`, `SALARY_ASSIGNMENT_INVALID_DATE_RANGE`,
`PAYROLL_PERIOD_NOT_FOUND`, `PAYROLL_PERIOD_EXISTS`,
`PAYROLL_PERIOD_INVALID_RANGE`, `PAYROLL_PERIOD_STATE_INVALID`,
`PAYROLL_RUN_NOT_FOUND`, `PAYROLL_ATTENDANCE_OPEN`,
`PAYROLL_INPUTS_CHANGED`, `PAYROLL_STATUTORY_RULE_UNVERIFIED`,
`PAYROLL_RECONCILIATION_FAILED`, `PAYROLL_NOT_CALCULATED`,
`PAYROLL_IMMUTABLE`, `PAYROLL_ADJUSTMENT_NOT_FOUND`,
`PAYROLL_ADJUSTMENT_STATE_INVALID`, `PAYROLL_ADJUSTMENT_INVALID_TARGET`,
`PAYROLL_DEDUCTION_NOT_FOUND`, `PAYROLL_DEDUCTION_STATE_INVALID`,
`PAYROLL_STATUTORY_RULE_NOT_FOUND`, `PAYROLL_STATUTORY_RULE_OVERLAP`,
`PAYROLL_STATUTORY_RULE_SOURCE_REQUIRED`,
`PAYROLL_STATUTORY_RULE_INVALID_DATE_RANGE`,
`PAYROLL_STATUTORY_RULE_INVALID_VALUE`,
`PAYROLL_NO_SALARY_ASSIGNMENT`.

## 5. Audit logging

21 distinct Phase-6 audit actions (all through the frozen
`record_audit` helper with ip/actor/company):

- `salary_component.create/update/deactivate`
- `salary_assignment.create/update/seed`
- `payroll_period.create/update/calculate/review/approve/mark_paid/lock`
- `payroll_adjustment.create/approve/reject/void`
- `payroll_deduction.create/update`
- `payroll_statutory_rule.create/deactivate`

The `payroll_period.approve` audit snapshots `run_id`,
`inputs_hash` and `net_total`. Audit-log visibility remains
`audit.read`.

## 6. Frontend

- `api.ts`: Phase-6 types (component, assignment, period, run, run
  line, payslip, accounting export, adjustment, deduction, statutory
  rule) and helpers for every endpoint above.
- `pages/SalaryComponentsPage.tsx`: category/status filters,
  create/edit form (code, EN/AR names, category, basis, default
  amount/rate, statutory key, sort order), deactivate with confirm.
- `pages/SalaryAssignmentsPage.tsx`: employee filter, create/edit
  (basic salary, window, reason), "Seed from contracts" with a
  `{created}/{skipped}` result notice.
- `pages/PayrollPeriodsPage.tsx`: status filter, create/edit
  (name, start, end, notes), status-driven workflow actions
  (Calculate -> navigates to the run, Review, Approve, Mark paid,
  Lock), "View run" resolving the period's active run.
- `pages/PayrollRunDetailPage.tsx`: totals grid (gross/deductions/
  employer/net/employee count), `engine_version` + `inputs_hash`
  badges, JSON-rendered warnings, run-lines table, per-employee
  payslip detail (`GET /payslips/{run_line_id}`), recalculate with
  confirm, export (JSON Blob download) - gated by
  `payroll_run.calculate` / `payroll_export.execute`.
- `pages/PayrollAdjustmentsPage.tsx`: status filter, create
  (employee, period, direction, amount, reason), approve/reject/void
  with a `decision_reason` prompt - each verb gated by its own
  permission.
- `pages/PayrollDeductionsPage.tsx`: status filter, create (employee,
  name, amount, total, window, reason), edit amount/window, cancel.
- `pages/PayrollStatutoryRulesPage.tsx`: key/status filters, create
  (statutory key, window, source reference + date, `rule_json`
  textarea validated as JSON, notes, legal-verification checkbox),
  deactivate; a notice states the app stores cited values only and
  gives no legal advice.
- `components/CompensationPanel.tsx` + Employee Detail "Compensation"
  tab: the employee's salary assignments with create/edit and the
  seed action; tab visible with `salary_assignment.view`.
- `App.tsx`: routes `/salary-components`, `/salary-assignments`,
  `/payroll-periods`, `/payroll-runs/:id`, `/payroll-adjustments`,
  `/payroll-deductions`, `/payroll-statutory-rules`, with nav entries
  gated by `payroll_period.view`, `salary_component.view`,
  `salary_assignment.view`, `payroll_adjustment.view`,
  `payroll_deduction.view`, `payroll_statutory_rule.view` (permission
  codes only - no role names anywhere in the frontend).
- `i18n.ts`: full EN + AR key sets (nav, page vocabulary, period/run/
  adjustment/deduction status maps, component category/basis enums,
  statutory vocabulary, all 28 error codes) - **693 keys per
  locale**, 536 statically used, verified symmetric by the automated
  key audit. Document direction follows the locale toggle.

## 7. Design refinements (decided during implementation)

(a) the workflow state lives ONLY on `payroll_periods.status` while
runs carry `active|void|superseded` - no second state machine;
(b) recalculation reuses the ACTIVE run (replacing its lines) instead
of superseding it, keeping `uq_payroll_run_active` meaningful and
`run_number` monotonic; (c) calculation includes only APPROVED
adjustments, while INSTALLMENT DEDUCTIONS are consumed exactly once
at APPROVE (never during calculation) - so a recalculation can never
double-spend a deduction; (d) APPROVE rebuilds the input snapshot and
compares hashes (`PAYROLL_INPUTS_CHANGED`) rather than locking inputs
at calculate time; (e) adjustments may only target OPEN periods, so
approved/paid/locked periods are effectively immutable
(`PAYROLL_IMMUTABLE`) and corrections flow to the next open period
(optionally referencing `original_run_id`); (f) `daily_divisor`
defaults to `30` but is read from the company's payroll statutory
rule (`DEFAULT_DAILY_DIVISOR` is a configuration default, not a legal
assertion) and overtime percentages come ONLY from cited rules -
nothing is hardcoded per country; (g) `salary_assignment_components`
stores optional per-assignment overrides while the catalog defaults
apply otherwise; (h) statutory endpoint permission codes are the
dedicated `payroll_statutory_rule.*` family (unlike Phase 5, which
reused `leave_type.*`); (i) every overlap uses a service pre-check
plus the gist EXCLUDE IntegrityError backstop mapped to the matching
error code; (j) adjustment decisions require three SEPARATE
permissions (`approve`, `reject`, `void`).

## 8. Tests

207 new tests in 6 files (total 652 = 445 frozen + 207):

| File | Tests | Focus |
|---|---|---|
| `test_payroll_engine_unit.py` | 71 | pure engine: proration, daily divisor, OT from cited rule, percent/fixed/engine-derived components, ROUND_HALF_UP line rounding and sum-of-lines totals, snapshot hash determinism/order-independence/versioning, warnings |
| `test_payroll_db.py` | 60 | component/assignment/period CRUD + validation, overlap guards, calculate -> run/lines/hash, review/approve/mark-paid/lock guards, immutability, input-hash mismatch, deduction consumption at approve, adjustments, statutory rules, payslip read, export, audits |
| `test_payroll_security_db.py` | 11 | exact permission matrix per role (28/28/19/8/0), cross-company 403/404, export permission, raw RLS insert probe, statutory verification blocking |
| `test_payroll_concurrency_db.py` | 5 | concurrent calculates -> single active run (run_number 1); concurrent approvals -> one winner + deduction consumed exactly once (remaining 700); period-create race; assignment-create overlap race; adjustment-approve race |
| `test_payroll_rls_db.py` | 52 | all 10 payroll tables x 5 (no-context zero rows, member scoping, cross-company insert blocked by RLS, update/delete rowcount 0, platform bypass) + forced-RLS and tenant-policy-clause structural tests |
| `test_payroll_migrations_db.py` | 8 | frozen SHA-256 pins for 0001-0007, chain head `0007_phase6_payroll`, 122 permissions with `PHASE6_PERMISSIONS` == catalog, exact 28-code role grants, EXCLUDE/partial-unique constraints + `requires_legal_verification` default, forced RLS, downgrade to 0006 -> re-upgrade roundtrip (permissions delete/restore asserted) |

Adapted (no test-count change): `conftest.py` (phase6 table hide +
TRUNCATE list), `test_rls_unit.py` (38 tables/policies),
`test_isolation_db.py` (28 -> 38 tables), `test_api_offline.py`
(phase 6, Phase-6 OpenAPI paths), `test_phase2_migrations_db.py` /
`test_phase3_migrations_db.py` / `test_leave_migrations_db.py` (head
chain -> `0007_phase6_payroll`, 122 permissions).

## 9. Verification results

- `pytest -q`: **652 passed** (0 failed, 207 Phase-6).
- `ruff check .`: clean (no noqa suppressions added; `ruff format`
  never run as a gate).
- `npm run build` (`tsc -b` + `vite build`): clean (only the
  pre-existing >500 kB chunk-size notice).
- `alembic check` on `saudi_hr_test`: clean ("No new upgrade
  operations detected").
- Migration round-trip on `saudi_hr_test`: `0007 -> 0006_phase5_leave
  -> 0007` succeeded interactively; DB left at head `0007_phase6_payroll`.
- Frozen SHA-256 hashes of 0001-0007 re-verified byte-identical after
  the phase (table in section 2).
- `saudi_hr` (dev DB) verified at alembic head
  `0004_phase3_employee_lifecycle` - it was NOT upgraded to 0005,
  0006 or 0007 at any point in this phase.
- psql audit on `saudi_hr_test`: 38 tables RLS enabled + forced, 38
  policies, 122 permissions (28 Phase-6), EXCLUDE/partial-unique
  indexes present.
- i18n key audit: 536 statically used keys, 693 EN keys = 693 AR
  keys, 0 missing, 0 asymmetric.
- Permission audit: exact expected code sets per role asserted in
  tests; no role names referenced in routes, services or frontend
  code (only in the permission GRANT data of `catalog.py`, as in
  Phases 1-5).
- Constraint audits: zero `float(` in payroll code; zero
  `eval`/`exec` (only `re.compile`); no executable DB-stored
  formulas (`rule_json` holds data values only); no Phase-7
  references (`phase7`/`0008_`) anywhere; no hardcoded Saudi
  statutory/legal values (overtime rates and divisors come from
  cited `rule_json`).
- Git: 0 commits, nothing staged (unchanged by this phase).

## 10. Known limitations / deferred items

- **Dev database not migrated**: `saudi_hr` is still at head 0004.
  `alembic upgrade head` must be run by the operator before using
  Phase 4-6 features locally (deliberately not run here).
- **Decisions use native prompts**: adjustment approve/reject/void
  reasons, destructive confirms and seed confirmations use
  `window.prompt`/`window.confirm` rather than modal forms (same
  approach as Phases 4-5).
- **No payslip PDF / print view**: the payslip is an HTML detail
  panel with itemized lines; PDF rendering is out of scope.
- **`rule_json` edited as raw JSON text** in the payroll statutory
  rules form (validated client-side and by pydantic); no structured
  rule builder, and no UI for per-assignment component overrides
  (`salary_assignment_components` is API/populated only).
- **Seed action is company-wide**: it processes ALL active employees
  of the company in one call (skipping existing windows); there is no
  per-employee selector.
- **No automation**: deduction consumption happens inside the approve
  transaction (not by a scheduler); there is no recurring period
  generator, no recalculation watcher and no hash-drift notification.
- **No statutory seed data or legal advice**: overtime percentages,
  daily divisors and any other statutory figures must be entered per
  company with a source citation (`requires_legal_verification`
  defaults true) - the product ships no Saudi values.
- **Accounting export is JSON only**: a structured payload
  (`AccountingExport`) for a downstream integrator; no ledger
  postings, bank files or ERP connectors.
