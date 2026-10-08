# Phase 8 - Employee Salary Advances

Employee salary advances end-to-end: the ESS apply flow (draft ->
submitted), the manager snapshot approval, HR disbursement that links a
Phase 6 payroll deduction rule, repayment collected through the frozen
payroll installment drawdown, and settlement (manual early settle or
automatic at read time when the rule finishes). Fully additive - two
new tables, a new `/salary-advances` API, one new page, and permission
codes only. Builds on Phase 1 (foundation), Phase 2 (employee master
data), Phase 3 (employee lifecycle), Phase 4 (attendance), Phase 5
(leave), Phase 6 (payroll), and Phase 7 (ESS requests & approvals).

Status: complete. Backend **749 tests passing** (697 frozen + 52 new
Phase-8 tests), `ruff check` clean, `alembic check` clean, frontend
builds clean (`tsc -b && vite build`), i18n EN/AR symmetric at 848
keys per locale (641 statically used), migration 0009 applied and
round-trip verified (downgrade to 0008 and re-upgrade) on the test
database (`saudi_hr_test`). The dev database (`saudi_hr`) is still at
head `0004_phase3_employee_lifecycle` - it was NOT migrated during this
phase (or any earlier phase run here); `alembic upgrade head` on
`saudi_hr` is an operator action, deliberately not run.

## 1. Scope

- Apply flow: an employee (or an HR actor on their behalf) creates a
  salary advance as a `draft` with `amount > 0`, a non-empty `reason`
  and a `requested_date`; drafts are editable, then `submit`ed.
- Approval: the approver is a SNAPSHOT of `employees.manager_id` taken
  at SUBMIT (NULL when the employee is their own manager); assigned
  approvers decide with `salary_advance.approve`/`reject`, `manage`
  holders decide any row in their companies. Rejection requires a
  reason.
- Disbursement: HR (`salary_advance.disburse`) pays out an `approved`
  advance; the service creates a Phase 6 `payroll_deduction_rules` row
  through the FROZEN `create_payroll_deduction` service (name
  `Salary advance #{id}`, installment per period, total = amount) and
  links it via `deduction_rule_id`.
- Repayment: NO new engine - the frozen Phase 6 payroll calculate
  includes the linked rule when it is `active`, within its effective
  window and still has remaining balance; each approved payroll period
  collects one installment until the rule completes.
- Settlement: manual settle (`salary_advance.settle`) closes the
  advance early (cancelling an still-`active` rule, reason required)
  or confirms a finished rule; the APPROVED implementation decision
  adds AUTO-SETTLEMENT AT READ TIME - any list/detail/inbox read
  reconciles a `disbursed` advance whose rule already `completed` or
  `cancelled`, stamping `settled_by = NULL`, a `system` event and a
  NULL-actor audit row.
- Frontend: one new `/advances` page (create form, status filter,
  decision-inbox toggle, list, detail panel with the full action set
  and event timeline) and a permission-gated nav entry; full EN/AR
  translations including all 7 new error codes.

Explicitly out of scope (approved Q2 decisions + standing rules):
a single-active-disbursed lock (an employee may hold several open
advances), cancelling an `approved`/`disbursed` advance after the
decision, an Employee-detail AdvancesPanel, interest/fees/statutory
values, any formula engine (installments are entered, never computed),
notifications, PDF/print, and Phase 9+ functionality.

## 2. Database (migration `0009_phase8_salary_advances`)

Never modify 0001-0008. Frozen SHA-256 hashes (re-verified this
phase, byte-identical):

| Migration | SHA-256 |
|---|---|
| `0001_phase1` | `5fe83204197a9ffcba377181188a1141fcbaafbc0606490b92ce699150d53e30` |
| `0002_security_hardening` | `2a6bc5292832040757409f42f2ba26ef565539cb671ae11003020f4a458aef8d` |
| `0003_phase2_employee_master_data` | `d5aae7696cb5fc15a0c8ea0e2bd6599375a5c2fb8b596c61fc2eb5d18e5ba324` |
| `0004_phase3_employee_lifecycle` | `798a87c0d92312866a7fa8480d74fd670fa04a43453819eedf4d2f115ffc921a` |
| `0005_phase4_attendance` | `1d3c7d91996c73f6994603d917956753cc9f5261c6bc6eabf5f033e380a6297e` |
| `0006_phase5_leave` | `5681ca44c38eed5e08328d8297034dd795202d31c28d22286b160101cf31db7e` |
| `0007_phase6_payroll` | `dd3b88005771d1883fd3f12f01945e87af3a007788ca0776fd83b7ef1c4b9bd0` |
| `0008_phase7_ess` | `dbbaa5fc2efd5185eaf71d6bbe2649dc05ad3dfef5632570eb8c0886a9378c73` |
| `0009_phase8_salary_advances` | `00994a0bb8ae5aee333227cf31358e7446ffbb4e572fb94aba6e485723f8341e` |

Revision id `0009_phase8_salary_advances` (30 chars - fits the
32-char `alembic_version.version_num` column). `down_revision =
0008_phase7_ess`. Downgrade to 0008 and re-upgrade are exercised in
`test_advance_migrations_db.py`. NOTE: the pinned 0009 digest changed
once DURING implementation when tests caught the decision-consistency
CHECK rejecting `disbursed` rows (section 7h); the final value above
is the tested one.

### 2.1 Tables (2 new; company-scoped, RLS enabled + forced)

- `salary_advances` (25 cols) - the advance: `company_id`,
  `employee_id` (CASCADE), `approver_employee_id` (snapshot at submit,
  SET NULL), `amount` (Numeric(12,2)), `reason` (Text),
  `requested_date`, `installment_amount` (Numeric(12,2), NULL until
  disbursement), `status` (server default `draft`), `submitted_by/at`,
  `decided_by/at`, `decision_reason` (500), `disbursed_by/at`,
  `settled_by/at`, `settle_note` (500), `deduction_rule_id` (FK to the
  frozen `payroll_deduction_rules`, SET NULL, UNIQUE), `created_by`,
  `created_at/updated_at`. CHECKs:
  `ck_salary_advance_amount` (`amount > 0`),
  `ck_salary_advance_installment` (NULL or `0 < installment <=
  amount`), `ck_salary_advance_status` (7-value set),
  `ck_salary_advance_decision_consistency` (`(status IN
  ('approved','rejected','disbursed','settled')) = (decided_at IS NOT
  NULL)`), `ck_salary_advance_decided_before_disburse`,
  `ck_salary_advance_reject_reason` (rejected rows must carry a
  decision reason), `ck_salary_advance_disbursed_rule` (disbursed rows
  must link a rule - this also makes the FK's SET NULL impossible for
  disbursed rows, so a linked rule can never be deleted out from under
  an advance), `ck_salary_advance_reason` (non-blank).
  `uq_salary_advance_deduction_rule` keeps one advance per repayment
  rule (multiple NULLs allowed). Indexes: company+status,
  employee+status, approver+status, and a PARTIAL index on
  `employee_id` for OPEN rows (`status IN ('draft','submitted',
  'approved')`).
- `salary_advance_events` (7 cols) - append-only, employee-visible
  history: `company_id`, `advance_id` (CASCADE), `event_type` (20:
  `created|submitted|approved|rejected|cancelled|disbursed|settled`),
  `actor_user_id` (SET NULL - NULL for system auto-settlement),
  `actor_name` (255, denormalized; `"system"` for auto-settlement),
  `note` (500), `created_at`. CHECKs cover the event type set and a
  non-blank actor name; rows are only ever INSERTed.

Both follow the frozen `TimestampMixin` pattern with plain String
status columns + CHECKs (no enums) and join the standard tenant
policy.

### 2.2 Permissions (10 new; 144 total)

Frozen `PHASE8_PERMISSIONS` tuple inside migration 0009 (asserted to
equal the catalog's Phase 8 codes by tests):

- `salary_advance.create`, `.update`, `.submit`, `.cancel` - owner
  verbs on OWN advances.
- `salary_advance.view` - cross-employee/company read.
- `salary_advance.approve`, `.reject` - decision verbs for assigned
  approvers.
- `salary_advance.manage` - decide ANY advance in one's companies.
- `salary_advance.disburse`, `.settle` - finance verbs.

Role backfill (computed from `DEFAULT_ROLES` and asserted by tests):

| Role | Total grants | Phase 8 grants |
|---|---|---|
| company_admin | 143 (all except `company.create`) | **10/10** |
| hr_manager | 124 | **10/10** |
| hr_officer | 74 | 7 - `view/create/update/submit/cancel` + `disburse/settle` (NO approve/reject/manage) |
| auditor | 35 | 1 - `salary_advance.view` only |
| employee | 16 | 4 - `create/update/submit/cancel` (NO view: own rows are served by the self-scope fallback, exactly like Phase 5/7) |

### 2.3 RLS / tenant isolation

Two new tables join the frozen registry: **43 tables / 43 policies**
total (verified on `saudi_hr_test`), each `ENABLE ROW LEVEL SECURITY`
+ `FORCE ROW LEVEL SECURITY` with the standard `tenant_isolation`
policy on `company_id`, registered from `main.py`, `cli.py`, the
migration, `app/core/rls_phase8.py`, `conftest.py`, and the test
helpers. Cross-company references resolve to
`SALARY_ADVANCE_NOT_FOUND`; raw-SQL probes as `saudi_hr_user` are
rejected (covered in `test_advance_rls_db.py`).

## 3. API endpoints (all under `/api/v1/salary-advances`)

- `POST /` (201) - create a draft (defaults to the caller's own
  employee; passing another `employee_id` additionally requires
  `salary_advance.view`).
- `GET /` - list (`company_id`, `employee_id`, `status`, paging) with
  the Phase 5/7 self-scope fallback; `assigned_to_me=true` switches to
  the decision-inbox scoping (manage holders see their companies'
  rows, decide holders only rows assigned to them as approver).
- `GET /{advance_id}` - detail with the full event timeline.
- `PATCH /{advance_id}` - edit amount/reason/requested_date while
  `draft`.
- `POST /{advance_id}/submit|cancel|approve|reject|disburse|settle` -
  state-machine actions. Decision bodies are optional `{reason?}`
  (reject REQUIRES one; early settle REQUIRES one while the rule is
  still active); disburse takes optional
  `{installment_amount?, note?}` (NULL installment = single drawdown,
  clamped server-side to `(0, amount]`).

Action responses return the row WITHOUT events (the timeline is only
assembled by the detail endpoint - Phase 7 pattern). Every rule -
self-scope, cross-employee, decision, finance - is enforced in the
service layer; routes authenticate only.

## 4. Business rules

### State machine

- `draft -> submitted -> approved -> disbursed -> settled`;
  `draft|submitted -> cancelled`; `submitted -> rejected`. Wrong
  transitions raise `SALARY_ADVANCE_STATE_INVALID` (409). The state
  check runs BEFORE permission checks, so an unauthorized caller
  probing a wrong-state row gets 409, never a permission oracle.
- Create returns 201 in `draft`; submit stamps `submitted_by/at` and
  the approver snapshot; approve/reject stamp
  `decided_by/at/decision_reason`; disburse stamps
  `disbursed_by/at/installment_amount/deduction_rule_id`; settle
  stamps `settled_by/at/settle_note`.
- There is NO cancel after approval (approved rows must proceed to
  disbursement) - an approved Q2 decision.

### Authorization model (roleless, no permission oracles)

- Owner verbs require ONLY the verb code when the advance belongs to
  the caller; acting FOR another employee additionally requires
  `salary_advance.view` (`_require_advance_verb`).
- Decisions require (`approver_employee_id == caller's employee` AND
  the verb) OR `salary_advance.manage`. Reads require `manage`,
  `view`, (owner AND `create`), or (assigned approver AND a decision
  verb).
- `Principal.company_ids` is derived ONLY from `user_roles` rows - a
  user with no role membership gets scoped 404s (resource-first
  fetches), never a 403/404 permission oracle; a member missing the
  verb gets 403 "forbidden". Cross-company reads 404, cross-company
  writes are also blocked by RLS.
- Employees without `salary_advance.view` list/detail their OWN rows
  through the same self-scope fallback used by Phase 5/7 leave.

### Disbursement -> frozen payroll integration

- Disbursement RE-USES the frozen Phase 6
  `create_payroll_deduction` service with the caller's real principal
  - `payroll_deduction.create` is re-enforced (no permission bypass),
  company access is re-checked, and the frozen audit entry is written
  (`Salary advance #{id}`, installment, total = amount,
  `effective_from = today`).
- Repayment draws down through the frozen payroll engine: the rule is
  included when `status='active'`, `effective_from <= period_end`,
  `effective_to` NULL or `> period_start`, and `remaining > 0`;
  payroll approval rebuilds inputs, so disbursement must happen
  BEFORE period calculation (pinned by tests).
- The linked rule cannot be deleted (the disbursed-row CHECK blocks
  the FK's SET NULL); `SalaryAdvanceRuleMissingError` is a defensive
  guard for that unreachable case - tests assert the CHECK raises
  instead.

### Settlement (manual + auto at read time)

- Manual settle requires a linked rule; if the rule is still
  `active` (early settlement) a reason is REQUIRED
  (`SALARY_ADVANCE_REASON_REQUIRED`) and the rule is cancelled through
  the frozen `update_payroll_deduction` (status -> `cancelled`,
  reason) - the remainder stops being collected. Rules already
  `completed`/`cancelled` settle with an optional note.
- AUTO-SETTLEMENT AT READ TIME (the single approved Q2 option): every
  list, detail and inbox read calls `_reconcile_if_done`; a
  `disbursed` advance whose rule already `completed` (payroll
  consumed it) or `cancelled` flips to `settled` with
  `settled_by = NULL`, `settle_note = "auto: deduction rule <status>"`,
  a `settled` event with `actor_name = "system"` / NULL
  `actor_user_id`, and a NULL-actor `salary_advance.settle` audit row.
  There is no background job - reconciliation is lazy and idempotent.
- NOT chosen: a single-active-disbursed lock (multiple concurrent
  advances per employee are allowed) and post-approval cancellation.

### Closed inputs (no formula engine)

- `amount > 0` (12,2), `reason` non-blank (<=4000),
  `requested_date` required; `installment_amount` (when given) in
  `(0, amount]`. Violations raise `SALARY_ADVANCE_AMOUNT_INVALID` /
  `SALARY_ADVANCE_REASON_REQUIRED` / `SALARY_ADVANCE_INSTALLMENT_INVALID`
  (400) - Pydantic rejects malformed bodies with 422 first. No
  interest, no legal values, no evaluation of any kind.

### Error codes (7 new, stable, translated by frontend `error.<CODE>`)

`SALARY_ADVANCE_NOT_FOUND` (404), `SALARY_ADVANCE_FORBIDDEN` (403),
`SALARY_ADVANCE_STATE_INVALID` (409), `SALARY_ADVANCE_AMOUNT_INVALID`
(400), `SALARY_ADVANCE_INSTALLMENT_INVALID` (400),
`SALARY_ADVANCE_REASON_REQUIRED` (400),
`SALARY_ADVANCE_RULE_MISSING` (409). Frozen codes reused: `forbidden`
(403), `ESS_NOT_LINKED` (403).

## 5. Audit logging

8 distinct Phase-8 audit actions (all through the frozen
`record_audit` helper with ip/actor/company, old/new snapshots from
`_snapshot`):

- `salary_advance.create/update/submit/cancel/approve/reject/
  disburse/settle`
- auto-settlement writes `salary_advance.settle` with
  `actor_user_id = NULL` (and `ip_address = NULL`)
- disbursement additionally writes the frozen
  `payroll_deduction.create` entry (created inside the reused Phase 6
  service)

Audit-log visibility remains `audit.read`. Reads (list/detail) are
not audited; auto-settlement IS (it changes state).

## 6. Frontend

- `api.ts`: Phase-8 types (`SalaryAdvance(+Event/Input/Update/
  DecisionInput/DisburseInput/SettleInput/PageParams)`) and helpers
  for all 10 operations (list/get/create/update/submit/cancel/approve/
  reject/disburse/settle) with the standard 401-refresh `request`
  pipeline; Decimal fields are typed as `string` (Pydantic v2
  serializes `Decimal` to JSON strings) and sent as numbers in
  requests.
- `pages/AdvancesPage.tsx`: gated by
  `salary_advance.view|create`; create form (amount, requested date,
  reason), status filter over all 7 statuses, an "Assigned to me"
  decision-inbox checkbox (shown only to
  `manage|approve|reject` holders, driving `assigned_to_me=true`),
  paged list (employee `#id`, amount, installment, status, dates) and
  the shared detail panel.
- `components/SalaryAdvanceDetail.tsx`: mode-driven detail/timeline/
  action panel - shows all lifecycle fields (status, amount,
  installment, reason, rule link, submitted/decided/disbursed/settled
  stamps, decision reason, settle note) plus the event timeline, and
  renders only the actions the caller's permission codes allow for
  the current status: draft (edit/submit/cancel), submitted
  (approve/reject/cancel), approved (disburse with installment+note),
  disbursed (settle with note). Reject is blocked client-side without
  a reason; all backend errors map through `error.<CODE>` translations.
- `App.tsx`: route `/advances`; nav entry gated
  `salary_advance.view|create` - permission codes only, no role names
  anywhere in the frontend.
- `i18n.ts`: full EN + AR key sets (nav, advance vocabulary, 7
  statuses, 7 event types, action labels, filters, all 7 error codes)
  - **848 keys per locale**, 641 statically used, verified symmetric
  by the automated key audit.

## 7. Design refinements (decided during implementation)

(a) auto-settlement is implemented AT READ TIME with a NULL-actor
audit row and `system` event (approved Q2 option), so settlement
never needs a scheduled job and stays idempotent;
(b) no single-active-disbursed lock - an employee can hold several
advances at once; each links its own deduction rule (UNIQUE on
`deduction_rule_id` prevents rule sharing, not multiple advances);
(c) no cancel after approval and no Employee-detail AdvancesPanel -
the single `/advances` page is the whole surface (both explicit Q2
decisions);
(d) disbursement goes through the FROZEN `create_payroll_deduction`
service rather than inserting a rule directly, so Phase 6
permissions/audits/validations cannot be bypassed by Phase 8;
(e) repayment is a pure reuse of the frozen Phase 6 installment
drawdown - Phase 8 stores an entered `installment_amount`, it never
computes one (no formula engine, no statutory values);
(f) action responses return the row WITHOUT events; only
`GET /{id}` assembles the timeline (Phase 7 pattern - small
list/action payloads);
(g) the state check runs BEFORE permission checks in every service
action, pinning the 409-vs-403 precedence in tests;
(h) the decision-consistency CHECK was corrected during test writing:
the original `(status='approved' OR status='rejected') = (decided_at
IS NOT NULL)` rejected `disbursed`/`settled` rows; both the migration
and `app/shared/models.py` now use `status IN ('approved','rejected',
'disbursed','settled')` (migration docstring updated, 0009 hash
re-pinned);
(i) `SalaryAdvanceRuleMissingError` is a defensive guard only - the
`ck_salary_advance_disbursed_rule` CHECK makes deleting a linked rule
impossible, which the security tests assert directly;
(j) creating an advance for ANOTHER employee requires
`salary_advance.view` in addition to `create` (cross-employee marker,
mirroring Phase 5/7), and inactive employees are refused at
create/submit with 403.

## 8. Tests

52 new tests in 6 files (total 749 = 697 frozen + 52):

| File | Tests | Focus |
|---|---|---|
| `test_advance_migrations_db.py` | 9 | FROZEN_HASHES 0001-0008 + pinned 0009 SHA-256, chain head `0009_phase8_salary_advances`, 144 permissions with the migration-owned `PHASE8_PERMISSIONS` snapshot == catalog, exact per-role grant sets (10/7/1/4 + company_admin 10), 11 CHECK constraints + unique + partial OPEN index, FORCE RLS + policy SQL, 0009 downgrade -> re-upgrade roundtrip |
| `test_advance_rls_db.py` | 7 | runtime FORCE ROW LEVEL SECURITY, member select scoping for both tables, cross-company insert/update/delete blocked (API-created and raw-SQL rows), API visibility |
| `test_advance_db.py` | 9 | full lifecycle (create -> PATCH -> submit -> inbox -> approve -> disburse -> payroll approve -> auto-settle with system event, NULL-actor audit, `payroll_deduction.create` audit), partial repayment across two payroll periods, reject, cancel draft/submitted (cancel_reason audit), early settle cancelling the rule, self-scope + viewer reads, filters + decide-only inbox, cross-create markers, cross-company 404, inactive employee 403 |
| `test_advance_security_db.py` | 10 | decision matrix incl. roleless -> 404, SoD on disburse/settle, cross-employee IDOR, cross-company 404, state-machine 409 precedence, reason/amount validation 400/422, rule-deletion CHECK defense, 401 on all routes, `ESS_NOT_LINKED` + roleless scoping, inactive submit 403 |
| `test_advance_concurrency_db.py` | 6 | double submit, double approve, approve-vs-reject (one decision), double disburse (exactly one rule `Salary advance #{id}`), double settle (rule cancelled once), concurrent creates both survive |
| `test_advance_unit.py` | 11 | schema validation, `_validate_amount/_validate_reason`, `_require_state`, `_snapshot`, `STATUS_PATTERN` regex |

Adapted (expectation updates only, no behavior changes):
`conftest.py` (phase8 tables in the TRUNCATE/hide list),
`test_rls_unit.py` (register_phase8_rls + 43 tables/policies),
`test_isolation_db.py` (forced-RLS list and policy set 41 -> 43),
`test_api_offline.py` (phase 8 + Phase-8 OpenAPI paths, the
forbidden `gosi`/`/loans`/`/pension` markers still absent,
`salary_advances`/`salary_advance_events` in the RLS manifest),
`test_phase2_migrations_db.py` / `test_phase3_migrations_db.py` /
`test_phase7_migrations_db.py` / `test_leave_migrations_db.py` /
`test_payroll_migrations_db.py` (head chain -> `0009_phase8_salary_
advances`, 144 permissions).

## 9. Verification results

- `pytest -q`: **749 passed** (0 failed, 52 Phase-8).
- `ruff check app tests`: clean (no noqa suppressions added; `ruff
  format` never run as a gate).
- `npm run build` (`tsc -b` + `vite build`): clean (only the
  pre-existing >500 kB chunk-size notice).
- `alembic check` on `saudi_hr_test`: clean ("No new upgrade
  operations detected").
- Migration round-trip on `saudi_hr_test`: `0009 -> 0008_phase7_ess
  -> 0009` exercised inside `test_advance_migrations_db.py`; DB left
  at head `0009_phase8_salary_advances`.
- Frozen SHA-256 hashes of 0001-0008 re-verified byte-identical after
  the phase, and 0009 matches its pinned digest (table in section 2).
- `saudi_hr` (dev DB) verified at alembic head
  `0004_phase3_employee_lifecycle` - it was NOT upgraded at any point
  in this phase.
- DB audit on `saudi_hr_test`: 43 tables RLS enabled + forced, 43
  policies, 144 permissions (10 Phase 8).
- Permission audit: 144 total codes, 10 Phase 8; grants
  143/124/74/35/16 with the exact Phase 8 sets 10/10/7/1/4 - no
  unknown or duplicate grants.
- i18n key audit: 641 statically used keys, 848 EN keys = 848 AR
  keys, 0 missing, 0 asymmetric.
- Constraint audits: zero role-name literals outside
  `app/permissions/catalog.py` (the GRANT data) - the advance module
  authorizes by permission code only; zero `eval`/`exec`/`os.system`;
  no `import odoo`; no Phase 9+ paths in the OpenAPI (`gosi`,
  `/loans`, `/pension` asserted absent by `test_api_offline.py`).
- Git: 0 commits, nothing staged (unchanged by this phase).

## 10. Known limitations / deferred items

- **Dev database not migrated**: `saudi_hr` is still at head 0004.
  `alembic upgrade head` must be run by the operator before using
  Phase 4-8 features locally (deliberately not run here).
- **Auto-settle is lazy**: reconciliation only happens when a list/
  detail/inbox read touches the row - no background job closes
  advances on a schedule (an unread settled-in-fact advance keeps
  showing `disbursed` until read).
- **No Employee-detail AdvancesPanel**: the Q2 decision left the
  single `/advances` page as the only surface; per-employee history
  is reachable via the list's employee scoping, not a panel.
- **Multiple concurrent advances allowed**: no lock caps how many
  open/disbursed advances one employee may hold.
- **No cancel after approval**: an `approved` advance can only move
  forward to disbursement (or be rejected while still `submitted`).
- **Installments are entered, not computed**: the disburser types the
  per-period amount (or accepts a single drawdown); there is no
  affordability/formula calculation by design.
- **List/detail show `#employee_id`**, not employee names (minimal
  payloads; name display would need a join through the frozen
  employee endpoints) - same as the Phase 7 inbox.
- **One reason field per open decision**: the shared detail panel
  shows a single reason input used by whichever action is selected.
- **No notifications**: submissions/decisions/disbursements do not
  email or notify anyone; the inbox is pull-based.
- **No partial early settlement**: settle always closes the whole
  remaining balance (cancelling the rule), never a negotiated part.
- **Advance records are HTML only**: no PDF/print or payslip-style
  export of an advance agreement.
