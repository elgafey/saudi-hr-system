# Phase 7 - Employee Self-Service, Requests & Approvals

The employee self-service (`/me`) portal (profile, shared documents,
own attendance, own payslips), a generic request/approval framework
(`employee_requests` with a strict state machine, closed per-type
payload schemas and an append-only event history), the attendance
correction flow, HR-side document visibility toggling, and the manager
approvals inbox. Leave stays a full reuse of the frozen Phase 5
endpoints - no leave code was added or changed.
Builds on Phase 1 (foundation), Phase 2 (employee master data),
Phase 3 (employee lifecycle), Phase 4 (attendance, schedules, shifts,
overtime), Phase 5 (leave management), and Phase 6 (payroll).

Status: complete. Backend **697 tests passing** (652 frozen + 45 new
Phase-7 tests), `ruff check` clean, `alembic check` clean, frontend
builds clean (`tsc -b && vite build`), i18n EN/AR symmetric at 794
keys per locale (609 statically used), migration 0008 applied and
round-trip verified (downgrade to 0007 and re-upgrade) on the test
database (`saudi_hr_test`). The dev database (`saudi_hr`) is still at
head `0004_phase3_employee_lifecycle` - it was NOT migrated during this
phase (or any earlier phase run here); `alembic upgrade head` on
`saudi_hr` is an operator action, deliberately not run.

## 1. Scope

- ESS portal (`/me`): the signed-in user's own employee profile
  (names, number, company/department/branch/position/manager, hire
  date, employment type, contact fields, contract summary incl. own
  basic salary), own documents (default-deny: only explicitly shared
  rows), own attendance records with date filters, and own payslips
  (gated to approved/paid/locked periods) with an itemized detail
  panel. Every `/me` read is additionally self-scoped in the service
  - the portal never exposes another employee's data.
- Request framework: a single generic `employee_requests` table with
  four closed request types - `attendance_correction`, `hr_letter`,
  `document_request`, `other` - each with a fixed, strictly validated
  payload schema (unknown keys, missing required keys and wrong types
  are rejected; no formulas, no eval, no dynamic engines). Lifecycle:
  `draft -> submitted -> approved | rejected | cancelled`.
- Attendance correction flow: on APPROVE the service creates or
  updates the employee's `attendance_records` row for the request's
  `work_date` (status `completed`, `source=manual`, metrics recomputed
  from the employee's schedule, `correction_reason`/`corrected_by`
  stamped, `attendance_record_id` back-linked), overlapping windows
  are refused. Leave/HR-letter/document approvals have NO side effects
  on other domains.
- Approvals inbox (`/approvals`): the decision queue for
  `employee_request.approve`/`reject`/`manage` holders, defaulting to
  `submitted`, with inline approve/reject decisions (rejection reason
  mandatory).
- HR document visibility: a sidecar `employee_document_visibility`
  flag per document with `GET`/`PATCH
  /employee-documents/{document_id}/visibility` (gated
  `employee_document.view` / `employee_document.update`); the frozen
  Phase 3 `employee_documents` table and router are untouched.
- Frontend: nested `/me` layout with permission-gated tabs, `/requests`
  (create/submit/cancel + detail with event timeline), `/approvals`,
  three `can()`-gated nav entries, an HR visibility column in the
  Employee Detail documents panel, and full EN/AR translations
  including all 12 new error codes.

Out of scope (unchanged): notifications/email/SMS, file uploads for
request attachments, bulk/bulk-decision workflows, request delegation
or substitution, PDF payslips or letters, scheduling/automation of
approvals, any new leave behavior, Phase 8+ functionality, Odoo
dependency, and any hardcoded Saudi legal values (this phase seeds no
statutory data at all).

## 2. Database (migration `0008_phase7_ess`)

Never modify 0001-0007. Frozen SHA-256 hashes (re-verified this
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

File name is `0008_phase7_ess_requests.py` and the revision **id** is
`0008_phase7_ess` (abbreviated to fit the 32-char
`alembic_version.version_num` column; the file name keeps the full
description). `down_revision = 0007_phase6_payroll`. Downgrade to 0007
and re-upgrade were exercised on `saudi_hr_test` (inside
`test_phase7_migrations_db.py` and interactively).

### 2.1 Tables (3 new; all company-scoped, RLS enabled + forced)

- `employee_requests` (22 cols) - the generic request:
  `company_id`, `employee_id` (who the request is FOR),
  `approver_employee_id` (snapshot of `employees.manager_id` taken at
  SUBMIT; `SET NULL` FK; forced to NULL when it would equal the
  requester - self-managed requests have no approver row),
  `request_type` (40), `status` (server default `draft`),
  `subject` (255), `reason` (Text), `payload` (JSONB, server default
  `{}`, validated against the CLOSED per-type schema in the service
  layer), `work_date` (indexed; only for attendance corrections),
  `submitted_by/submitted_at`, `decided_by/decided_at`,
  `decision_reason` (500), `cancelled_by/cancelled_at`,
  `cancel_reason` (500), `attendance_record_id` (SET NULL back-link
  filled when a correction is applied), `created_by`,
  `created_at/updated_at`. CHECKs: `ck_employee_request_type`,
  `ck_employee_request_status`, `ck_employee_request_decision_consistency`
  (`approved|rejected <=> decided_at IS NOT NULL`),
  `ck_employee_request_reject_reason` (rejected rows must carry a
  decision reason - the service enforces the same rule with the
  dedicated error code). Partial unique index keeps **one OPEN
  attendance_correction per employee per work date**; additional
  indexes cover company/status/type and employee/status lookups.
- `employee_request_events` (8 cols) - append-only, employee-visible
  history: `company_id`, `request_id` (CASCADE), `event_type` (20:
  `created|submitted|approved|rejected|cancelled`), `actor_user_id`
  (SET NULL), `actor_name` (255, denormalized display name - events
  remain readable after user deletion), `note` (500), `created_at`.
  Rows are only ever INSERTed (never updated or deleted), CHECKs
  cover the event type set.
- `employee_document_visibility` (7 cols) - sidecar default-deny flag:
  `company_id`, `document_id` (FK to the FROZEN `employee_documents`,
  CASCADE, unique - one flag per document), `employee_visible`
  (BOOLEAN, server default **false**), `updated_by` (SET NULL),
  `created_at/updated_at`. The frozen `employee_documents` table
  itself is never modified by Phase 7.

All three use plain String status columns with CHECKs (no enums),
follow the frozen `TimestampMixin` pattern, and join the standard
tenant policy.

### 2.2 Permissions (12 new; 134 total)

Frozen `PHASE7_PERMISSIONS` tuple inside migration 0008 (asserted to
equal the catalog's Phase 7 codes by tests):

- `ess.profile.view`, `ess.document.view`, `ess.attendance.view`,
  `ess.payslip.view` - gate the four `/me` portal reads.
- `employee_request.create`, `employee_request.update`,
  `employee_request.submit`, `employee_request.cancel` - owner verbs
  on OWN requests.
- `employee_request.view` - cross-employee/HR read (inbox + detail).
- `employee_request.approve`, `employee_request.reject` - decision
  verbs for assigned approvers.
- `employee_request.manage` - decide ANY request in one's companies.

Role backfill (computed from `DEFAULT_ROLES` and asserted by tests):

| Role | Total grants | Phase 7 grants |
|---|---|---|
| company_admin | 133 (all except `company.create`) | **12/12** |
| hr_manager | 114 | **12/12** |
| hr_officer | 67 | 9 - the 4 `ess.*` + `employee_request.create/update/submit/cancel/view` (NO approve/reject/manage) |
| auditor | 34 | 1 - `employee_request.view` only |
| employee | 12 | 8 - the 4 `ess.*` + `employee_request.create/update/submit/cancel` (NO view: own rows are served by the self-scope fallback, exactly like Phase 5 leave) |

### 2.3 RLS / tenant isolation

Three new tables join the frozen registry: **41 tables / 41
policies** total (verified on `saudi_hr_test`), each `ENABLE ROW LEVEL
SECURITY` + `FORCE ROW LEVEL SECURITY` with the standard
`tenant_isolation` policy on `company_id`, registered from `main.py`,
`cli.py`, the migration, `app/core/rls_phase7.py`, `conftest.py`, and
the test helpers. Cross-company references resolve to `*_NOT_FOUND`;
raw-SQL probes as `saudi_hr_user` are rejected (covered in
`test_phase7_rls_db.py` and `test_phase7_security_db.py`).

## 3. API endpoints (all under `/api/v1`)

ESS portal (`ess.*.view`, always additionally self-scoped):

- `GET /me/profile` - own employee profile incl. contract summary.
- `GET /me/documents` - own documents, INNER JOIN on the visibility
  flag (`employee_visible IS TRUE`) - default-deny.
- `GET /me/documents/{document_id}/download` - audited
  (`document.download`); 403 `ESS_DOCUMENT_NOT_SHARED` when not
  shared (never leaking existence across employees).
- `GET /me/attendance` - own records (`date_from`, `date_to`, paging).
- `GET /me/payslips` - own payslip summaries, period gated to
  `approved|paid|locked` (audited, entity `employee`).
- `GET /me/payslips/{run_line_id}` - full itemized payslip, own line
  only (403 `PAYSLIP_NOT_OWN`, audited, entity `payroll_run_line`,
  record_id stored as the STRING id).

Requests (`employee_request.*`):

- `GET/POST /employee-requests` (list: `status`, `request_type`,
  `employee_id`, paging; create returns **201**).
- `GET/PATCH /employee-requests/{request_id}` (detail serves the
  event timeline; PATCH only while `draft`).
- `POST /employee-requests/{request_id}/submit|approve|reject|cancel`
  (decision bodies are optional `{reason?}`; reject REQUIRES a
  non-empty reason).
- `GET /approvals` - the decision inbox (status filter, paging).

Document visibility (`employee_document.*`):

- `GET /employee-documents/{document_id}/visibility`
  (`employee_document.view`) - reads the sidecar flag; a missing row
  reads as `employee_visible: false, updated_by: null` (default-deny).
- `PATCH /employee-documents/{document_id}/visibility`
  (`employee_document.update`) - body `{employee_visible: bool}`,
  creates or updates the sidecar row, audits `document.visibility`.
  Both 404 `DOCUMENT_NOT_FOUND` cross-company (no probing).

Leave: NO new endpoints - the portal and approvals reuse the frozen
Phase 5 `/leave-requests` endpoints unchanged.

## 4. Business rules

### Request state machine

- `draft -> submitted -> approved | rejected`; `draft|submitted ->
  cancelled`. Wrong transitions raise
  `EMPLOYEE_REQUEST_STATE_INVALID` (409). Create returns 201 with the
  row in `draft`.
- APPROVE/REJECT capture `decided_by/decided_at/decision_reason`
  (rejection reason mandatory - `EMPLOYEE_REQUEST_DECISION_REASON_REQUIRED`
  400, plus the DB CHECK); CANCEL captures
  `cancelled_by/cancelled_at/cancel_reason` (reason optional).
- The approver is a SNAPSHOT of `employees.manager_id` taken at
  SUBMIT (a later manager change does not reroute pending requests);
  a self-managed employee gets `approver_employee_id = NULL`.
- Duplicate protection: one OPEN `attendance_correction` per employee
  per `work_date` (service pre-check + partial unique index backstop).

### Authorization model (roleless, no permission oracles)

- Owner verbs (`create/update/submit/cancel`) require ONLY the verb
  code when the request belongs to the caller; acting FOR another
  employee additionally requires `employee_request.view`.
- Decisions (`approve/reject`) require
  (`approver_employee_id == caller's employee` AND the verb) OR
  `employee_request.manage`. Reads require `manage`, `view`,
  (owner AND `create`), or (assigned approver AND a decision verb).
- The inbox returns ALL rows in the caller's companies to `manage`
  holders, and only ASSIGNED rows to decide holders.
- `Principal.company_ids` is derived ONLY from `user_roles` rows - a
  user with no role membership gets scoped 404s (resource-first
  fetches), never a 403/404 permission oracle; a member missing the
  verb gets 403 "forbidden". Cross-company reads 404, cross-company
  writes are blocked by RLS as well.
- Employees without `employee_request.view` list/detail their OWN
  rows through the same self-scope fallback used by Phase 5 leave.

### Closed payload schemas (`app/ess/payloads.py`)

- `attendance_correction`: `work_date` (ISO date, required),
  `check_in`, `check_out` (ISO-8601 timestamps, required; both naive
  or both aware; `check_out > check_in`) - violations raise
  `ATTENDANCE_CORRECTION_INVALID` (400).
- `hr_letter`: `purpose` (required, <=500), optional `language`
  (`ar|en`).
- `document_request`: `document_name` (required, <=255), optional
  `note` (<=1000).
- `other`: optional `details` (<=4000).
- Unknown keys / missing required keys / wrong JSON types raise
  `EMPLOYEE_REQUEST_INVALID_PAYLOAD` (400); unknown request types
  raise `EMPLOYEE_REQUEST_TYPE_UNSUPPORTED` (400). No formula
  evaluation, no `eval`/`exec`, nothing executable is stored.

### Attendance correction application (on APPROVE only)

- Reuses the frozen Phase 4 metrics helpers (`resolve_employee_schedule`,
  `compute_metrics`) - schedule resolution and worked/late computation
  are Phase 4's, not reimplemented.
- Creates the record when `work_date` has none, otherwise updates it
  in place; always stamps `correction_reason`, `corrected_by/at`,
  sets `status=completed`, `source=manual`, links
  `employee_requests.attendance_record_id`, audits
  `attendance.correct` with an old/new snapshot, and maps overlap
  `IntegrityError` to the frozen 409 `AttendanceOverlapError`.
- Stale/conflicting corrections are refused:
  `ATTENDANCE_CORRECTION_STALE` (409) when the target record changed
  after the request was created, `EMPLOYEE_REQUEST_RECORD_MISMATCH`
  (400) when the request's `work_date` no longer matches the record.

### Payslip self-access

- Period gate: only periods in `approved`, `paid` or `locked` are
  listed (same gate as the frozen Phase 6 payslip read).
- Own line only: another employee's `run_line_id` returns 403
  `PAYSLIP_NOT_OWN`; list responses are filtered to the caller's
  `employee_id`.
- Audited as `payslip.view` (list: entity `employee`; detail: entity
  `payroll_run_line`, `record_id` stored as a STRING).

### Document visibility (default-deny sidecar)

- The `/me` document list INNER JOINs
  `employee_document_visibility.employee_visible IS TRUE`; a missing
  sidecar row means hidden. Download of a not-shared document is 403
  `ESS_DOCUMENT_NOT_SHARED` for EVERY caller except the owner-scoped
  HR path.
- Employees can never flip their own flag (route gate
  `employee_document.update`; the `/me` router has no visibility
  endpoint at all).
- HR reads the current state via the sidecar GET so the Employee
  Detail documents panel can display and toggle it.

### Error codes (12 new, stable, translated by frontend `error.<CODE>`)

`ESS_NOT_LINKED` (403), `ESS_DOCUMENT_NOT_SHARED` (403),
`EMPLOYEE_REQUEST_NOT_FOUND` (404), `EMPLOYEE_REQUEST_STATE_INVALID`
(409), `EMPLOYEE_REQUEST_FORBIDDEN` (403),
`EMPLOYEE_REQUEST_TYPE_UNSUPPORTED` (400),
`EMPLOYEE_REQUEST_INVALID_PAYLOAD` (400),
`EMPLOYEE_REQUEST_DECISION_REASON_REQUIRED` (400),
`EMPLOYEE_REQUEST_RECORD_MISMATCH` (400),
`ATTENDANCE_CORRECTION_INVALID` (400),
`ATTENDANCE_CORRECTION_STALE` (409), `PAYSLIP_NOT_OWN` (403).
Frozen codes reused: `DOCUMENT_NOT_FOUND` (404), `forbidden` (403),
`AttendanceOverlapError` (409).

## 5. Audit logging

10 distinct Phase-7 audit actions (all through the frozen
`record_audit` helper with ip/actor/company):

- `employee_request.create/update/submit/cancel/approve/reject`
- `document.download` (ESS download), `document.visibility` (toggle)
- `payslip.view` (list + detail)
- `attendance.correct` (correction applied at approval, with old/new
  record snapshots)

Audit-log visibility remains `audit.read`. Reads (profile, document
list, attendance list) are not audited; every sensitive READ
(payslip, file download) is.

## 6. Frontend

- `api.ts`: Phase-7 types (`EssProfile`, `PayslipSummary`,
  `EmployeeRequest(+Event/Input/Update/PageParams)`,
  `ApprovalsPageParams`, `DocumentVisibility`) and helpers for every
  endpoint above, including the raw-fetch `downloadMyDocument` with
  401-refresh and `Content-Disposition` filename parsing, and
  `get/setEmployeeDocumentVisibility`.
- `pages/EssLayoutPage.tsx`: nested `/me` route shell with tabs
  gated by `ess.document.view` / `ess.attendance.view` /
  `ess.payslip.view`.
- `pages/EssProfilePage.tsx`: profile fields (locale-aware EN/AR
  names), contract card with own basic salary.
- `pages/EssDocumentsPage.tsx`: own shared documents with paged
  download (blob + filename).
- `pages/EssAttendancePage.tsx`: `date_from/date_to` filters, worked/
  late columns, Phase 4 status labels.
- `pages/EssPayslipsPage.tsx`: gated list with period range, earnings/
  deductions/net, and an on-demand itemized detail panel with
  locale-selected line labels.
- `pages/EssRequestsPage.tsx`: status/type filters, create form with
  per-type fields (correction date+times, letter purpose+language,
  document name+note, free details), list, and a shared detail panel
  with submit/cancel actions and the event timeline.
- `pages/EssApprovalsPage.tsx`: inbox (status filter defaults to
  `submitted`), employee/subject/type columns, detail panel with
  approve/reject (inline reason; rejection blocked without one).
- `components/EmployeeRequestDetail.tsx`: shared detail/timeline/
  action panel used by both pages (mode-driven action set).
- `components/DocumentsPanel.tsx`: new "Employee visibility" column
  - current state fetched per row (`employee_document.view`) and a
  toggle button (`employee_document.update`) that flips the sidecar
  flag.
- `App.tsx`: routes `/me` (nested index/documents/attendance/
  payslips), `/requests`, `/approvals`; nav entries `/me`, `/requests`
  (`employee_request.view|create`), `/approvals`
  (`employee_request.approve|manage|view`) - permission codes only,
  no role names anywhere in the frontend.
- `i18n.ts`: full EN + AR key sets (nav, ESS vocabulary, request
  types/statuses/events, approvals vocabulary, visibility labels, all
  12 error codes) - **794 keys per locale**, 609 statically used,
  verified symmetric by the automated key audit. Document direction
  follows the locale toggle.

## 7. Design refinements (decided during implementation)

(a) document visibility lives in a SIDECAR table with a boolean
defaulting to false, so the frozen `employee_documents` table and its
Phase 3 router/schema stay byte-identical - visibility is an additive
concern with its own `employee_document.view/update` gates;
(b) the visibility endpoints were placed on the ESS router
(`/employee-documents/...`) rather than extending the frozen Phase 3
router, and a GET was added so HR can display the current state
(PATCH-only would leave the panel guessing);
(c) requests are ONE generic table with closed per-type payload
schemas instead of per-type tables or a dynamic form engine - the
state machine, authorization, audit and timeline are shared while
payload validation stays a fixed field set per type;
(d) the approver is snapshotted at SUBMIT from `employees.manager_id`
(and NULLed when it equals the requester), making pending requests
insensitive to later org changes;
(e) action responses return the request row WITHOUT events (the
`EmployeeRequest` model has no `events` relationship - the timeline
is only assembled by the detail endpoint), keeping list/action
payloads small;
(f) principal company scoping reads ONLY `user_roles`, so a user with
no role membership sees scoped 404s rather than permission oracles -
and tests pin the 404-vs-403 split per case;
(g) leave integration is a full REUSE of the frozen Phase 5
endpoints - the ESS "requests" concept does not duplicate or wrap
leave;
(h) the correction application reuses Phase 4's schedule/metrics
helpers and writes through the same overlap guard, so a correction
cannot bypass attendance invariants;
(i) HR officer gets `employee_request.view` (paperwork) but NO
decision verbs - decisions stay with the approver/manager or
`manage` holders;
(j) payslip reads audit `payslip.view` with a STRING `record_id` for
detail reads (ids of payroll run lines are not integers in the audit
contract).

## 8. Tests

45 new tests in 4 files (total 697 = 652 frozen + 45):

| File | Tests | Focus |
|---|---|---|
| `test_phase7_migrations_db.py` | 9 | FROZEN_HASHES 0001-0007 + pinned 0008 SHA-256, chain head `0008_phase7_ess`, 134 permissions with the migration-owned `PHASE7_PERMISSIONS` snapshot == catalog, exact per-role grant sets, CHECK constraints + partial unique correction index, FORCE RLS + policy SQL, downgrade to 0007 -> re-upgrade roundtrip (permissions delete/restore asserted) |
| `test_phase7_rls_db.py` | 9 | runtime FORCE ROW LEVEL SECURITY, member select scoping, cross-company insert/update/delete blocked for all 3 tables, audit company scoping |
| `test_phase7_concurrency_db.py` | 3 | duplicate-correction race (one wins), double-submit race (single `submitted` transition + one event), double-approve race (single winner, one decision) |
| `test_phase7_security_db.py` | 24 | IDOR matrix (cross-employee create/detail/cancel/decide), roleless 404 vs missing-verb 403, request lifecycle guards (state/author/reason), document default-deny + visibility GET/PATCH gates + cross-company 404, payslip period gating + own-only + audit, correction stale/overlap/mismatch guards, HR-letter approval has no attendance side effect |

Adapted (expectation updates only, no behavior changes):
`conftest.py` (phase7 tables in the TRUNCATE/hide list),
`test_rls_unit.py` (register_phase7_rls + 41 tables/policies),
`test_isolation_db.py` (forced-RLS list and policy set 38 -> 41),
`test_api_offline.py` (phase 7 + Phase-7 OpenAPI paths, GET+PATCH
methods on the visibility path, `employee_requests` in the RLS
manifest), `test_phase2_migrations_db.py` /
`test_phase3_migrations_db.py` / `test_leave_migrations_db.py` /
`test_payroll_migrations_db.py` (head chain -> `0008_phase7_ess`,
134 permissions; the leave file asserts the employee role's exact
Phase 7 code set).

## 9. Verification results

- `pytest -q`: **697 passed** (0 failed, 45 Phase-7).
- `ruff check .`: clean (no noqa suppressions added; `ruff format`
  never run as a gate).
- `npm run build` (`tsc -b` + `vite build`): clean (only the
  pre-existing >500 kB chunk-size notice).
- `alembic check` on `saudi_hr_test`: clean ("No new upgrade
  operations detected").
- Migration round-trip on `saudi_hr_test`: `0008 -> 0007_phase6_payroll
  -> 0008` succeeded interactively; DB left at head `0008_phase7_ess`.
- Frozen SHA-256 hashes of 0001-0007 re-verified byte-identical after
  the phase, and 0008 matches its pinned digest (table in section 2);
  no unexpected files in `alembic/versions`.
- `saudi_hr` (dev DB) verified at alembic head
  `0004_phase3_employee_lifecycle` - it was NOT upgraded to 0005,
  0006, 0007 or 0008 at any point in this phase.
- DB audit on `saudi_hr_test`: 41 tables RLS enabled + forced, 41
  policies, 134 permissions (12 Phase 7).
- Permission audit (script over the catalog): 134 total codes, 12
  Phase 7; grants 133/114/67/34/12 with the exact Phase 7 sets
  12/12/9/1/8 - no unknown or duplicate grants.
- i18n key audit: 609 statically used keys, 794 EN keys = 794 AR
  keys, 0 missing, 0 asymmetric.
- Constraint audits: zero role-name literals in `app/ess` or
  `app/core` authorization code (only the permission GRANT data in
  `app/permissions/catalog.py` and the migration backfill, as in
  Phases 1-6); zero `eval`/`exec`/`__import__` (only
  `re.compile` false-positive matches removed by the audit); zero
  `import odoo`/`from odoo`; no Phase 8+ paths in the OpenAPI
  (`gosi`, `/loans`, `/pension` asserted absent).
- Git: 0 commits, nothing staged (unchanged by this phase).

## 10. Known limitations / deferred items

- **Dev database not migrated**: `saudi_hr` is still at head 0004.
  `alembic upgrade head` must be run by the operator before using
  Phase 4-7 features locally (deliberately not run here).
- **Decisions use inline prompts**: approve/reject/cancel reasons are
  an inline reason field in the detail panel (reject is blocked
  without one) rather than modal dialogs - same lightweight approach
  as earlier phases.
- **Approvals list shows `#employee_id`**, not employee names (the
  inbox keeps the API payload minimal; name display would need a
  join through the frozen employee list endpoints).
- **One reason field per open decision**: the shared detail panel
  shows a single reason input used by whichever action
  (approve/reject/cancel) is selected; switching actions keeps the
  typed text.
- **No request attachments**: requests carry structured payload fields
  only - there is no file upload on `employee_requests` (document
  REQUESTS ask for a name/note; the actual file arrives later via the
  frozen Phase 3 documents flow once shared).
- **No notifications**: submissions/decisions do not email or notify
  anyone; the inbox is pull-based.
- **Payslip detail is HTML**: no PDF/print rendering.
- **Visibility toggle is per document** (N GETs per panel page of 10)
  - there is no bulk share/unshare and no per-type default.
- **Correction scope is a full window**: a correction always carries
  both check-in and check-out for the whole `work_date`; partial-day
  corrections and split shifts are out of scope.
- **No delegation**: decisions are made by the snapshotted approver
  or `manage` holders; there is no substitute-approver mechanism.
