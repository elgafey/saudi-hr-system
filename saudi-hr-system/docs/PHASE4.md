# Phase 4 - Attendance, Work Schedules, Shifts & Overtime

Work schedule templates and weekday rules, shifts, effective-dated
employee assignments, attendance capture and calculation, and the
overtime approval workflow.
Builds on Phase 1 (foundation), Phase 2 (employee master data), and
Phase 3 (employee lifecycle, frozen).

Status: complete. Backend 369 tests passing, frontend builds clean,
migration 0005 applied and verified on the test database
(`saudi_hr_test`). The dev database (`saudi_hr`) is intentionally NOT
migrated yet - `alembic upgrade head` on `saudi_hr` is an operator
action, deliberately not run during this phase.

## 1. Scope

- Work schedule templates: per-schedule timezone, effective-dated
  versioning, one rule row per ISO weekday, break periods per day.
- Shifts: reusable named windows with a service-computed
  `crosses_midnight` flag.
- Employee work assignments: effective-dated schedule (and optional
  shift override) per employee, with open-interval auto-close.
- Attendance: manual/device/import/api capture, check-in/check-out,
  open/completed/missing_checkout lifecycle, computed minute columns.
- Overtime: draft -> submitted -> approved/rejected workflow with
  cancel and approved-record correction, all reasons audited.
- Frontend: four list pages (Attendance, Work Schedules, Shifts,
  Overtime) plus an Employee Detail "Attendance / Schedule" tab.

Out of scope (unchanged): payroll (Phase 5), GOSI, tax, leave,
holidays, biometrics/GPS devices, approval engine, self-service
portal, notifications, billing. **Phase 4 does not calculate payroll
amounts** - it only produces attendance/overtime inputs
(`worked_minutes`, `overtime_candidate_minutes`, approved overtime
minutes) for a later payroll phase to consume.

## 2. Database (migration `0005_phase4_attendance`)

Never modify 0001-0004. Frozen SHA-256 hashes (verified previously):

| Migration | SHA-256 |
|---|---|
| `0001_phase1` | `5fe83204197a9ffcba377181188a1141fcbaafbc0606490b92ce699150d53e30` |
| `0002_security_hardening` | `2a6bc5292832040757409f42f2ba26ef565539cb671ae11003020f4a458aef8d` |
| `0003_phase2_employee_master_data` | `d5aae7696cb5fc15a0c8ea0e2bd6599375a5c2fb8b596c61fc2eb5d18e5ba324` |
| `0004_phase3_employee_lifecycle` | `798a87c0d92312866a7fa8480d74fd670fa04a43453819eedf4d2f115ffc921a` |

File name is `0005_phase4_attendance_schedules_shifts_overtime.py`
but the revision **id** is `0005_phase4_attendance`: alembic stores
`version_num` in a VARCHAR(32) column and the long id overflowed it.
`down_revision = 0004_phase3_employee_lifecycle`. Downgrade to 0004
and re-upgrade were exercised on `saudi_hr_test`.

### 2.1 Tables (7 new; all company-scoped, RLS enabled + forced)

- `work_schedules` - template header (code, names, per-schedule
  `timezone`, `effective_from`/`effective_to`, `status`
  active|archived, notes). Unique `(company_id, code, effective_from)`
  (`uq_work_schedule_company_code_from`) + gist EXCLUDE
  `exq_work_schedule_code_no_overlap`
  `(company_id WITH =, code WITH =, daterange(effective_from,
  effective_to, '[)') WITH &&)` so one code may version over time but
  never overlap itself. CHECKs `ck_work_schedule_date_range`,
  `ck_work_schedule_status`; index `ix_work_schedule_company_code`.
- `work_schedule_days` - exactly one row per `(schedule_id, weekday)`
  (`uq_work_schedule_day_weekday`), ISO weekday Monday=0 .. Sunday=6
  (`ck_work_schedule_day_weekday`), `is_working`, optional
  `start_time`/`end_time` (`ck_work_schedule_day_times_both_or_neither`,
  `ck_work_schedule_day_time_range`), optional `shift_id` pin.
- `shifts` - `code`, names, naive `start_time`/`end_time`,
  service-computed `crosses_midnight`, `status` active|archived,
  notes; unique `(company_id, code)` (`uq_shift_company_code`).
- `break_periods` - break rows owned by a schedule day XOR a shift
  (`ck_break_period_single_parent`), `is_paid` flag. Break periods
  inherit their parent's tenant (they are never queried alone).
- `employee_work_assignments` - `schedule_id`, optional `shift_id`,
  `effective_from`/`effective_to`, notes. CHECK
  `ck_work_assignment_date_range`; partial unique
  `uq_work_assignment_open` (one open interval per employee); gist
  EXCLUDE `exq_work_assignment_no_overlap`
  `(employee_id WITH =, daterange(..., '[)') WITH &&)`; index
  `ix_work_assignment_employee_effective`.
- `attendance_records` - `work_date`, `schedule_id`/`shift_id`
  snapshot, `check_in`/`check_out`, `status`
  (open|completed|missing_checkout, default open), `source`
  (manual|device|import|api, default manual), six nullable computed
  minute columns, notes, `correction_reason`/`corrected_by`/
  `corrected_at`/`closed_by`. CHECKs: `ck_attendance_time_range`,
  `ck_attendance_completed_has_checkout`, `ck_attendance_status`,
  `ck_attendance_source`. Partial unique `uq_attendance_open` (one
  open record per employee); gist EXCLUDE
  `exq_attendance_no_overlap` `(employee_id WITH =, tstzrange(check_in,
  check_out, '[)') WITH &&) WHERE check_out IS NOT NULL` (timezone-
  aware; service pre-checks are naive-in-schedule-tz). Indexes:
  `ix_attendance_company_work_date`, `ix_attendance_employee_checkin`,
  `ix_attendance_company_open`.
- `overtime_records` - `employee_id`, optional `attendance_id`,
  `work_date`, `requested_minutes`, `approved_minutes`, `status`
  (draft|submitted|approved|rejected|cancelled, default draft),
  `reason`, submitted/decided/correction metadata. CHECKs:
  `ck_overtime_requested_minutes` (1..1440),
  `ck_overtime_approved_minutes` (1..requested), `ck_overtime_status`.
  Indexes: `ix_overtime_company_status_date`,
  `ix_overtime_employee_date`.

EXCLUDE constraints use `btree_gist` (installed by frozen migration
0004; intentionally left in place, cluster-level object).

### 2.2 Permissions (24 new; 69 total)

Frozen `PHASE4_PERMISSIONS` tuple inside migration 0005:

- `work_schedule.view/create/update/delete`
- `shift.view/create/update/delete`
- `employee_work_assignment.view/create/update/delete`
- `attendance.view/create/update/delete/correct`
- `overtime.view/create/update/submit/approve/reject/cancel`

(There is deliberately no `overtime.correct`: the backend
`POST /overtime/{id}/correct` endpoint requires `overtime.approve`,
and the frontend gates its Correct action with the same code.)

Role backfill (with GUC elevation for the 0002 guard): company_admin
(all 24), hr_manager (schedules/shifts/assignments view+create+
update, attendance view/create/update/correct, overtime view/create/
update/submit/approve/reject/cancel - deletes of schedules/shifts/
assignments and `attendance.delete` stay company_admin-only),
hr_officer (schedule/shift/assignment view, assignment create,
attendance view/create/update, overtime view/create/submit),
auditor (five view codes only).

### 2.3 RLS / tenant isolation

Seven new tables join the frozen registry: 22 tables / 22 policies
total, each `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`
with the standard `tenant_isolation` policy on `company_id`,
registered from `main.py`, `cli.py`, the migration itself, and the
test helpers. Cross-company references (schedule/shift/employee
lookups) resolve to `*_NOT_FOUND` rather than leaking existence.
Raw-SQL insert probes as `saudi_hr_user` are rejected by RLS (covered
in `test_phase4_security_db.py`).

## 3. API endpoints (all under `/api/v1`)

Work schedules (`work_schedule.*`):

- `GET/POST /work-schedules` (list: `page`, `page_size`, `search`,
  `status`)
- `GET/PATCH/DELETE /work-schedules/{schedule_id}`
- `GET/PUT /work-schedules/{schedule_id}/days` - PUT replaces/updates
  the weekday rows present in the payload (upsert per weekday;
  breaks are replace-all for each submitted weekday)
- `GET /employees/{employee_id}/schedule?date=YYYY-MM-DD` - resolves
  the effective assignment/day/shift/breaks for a date
  (requires `employee_work_assignment.view`; defaults to today in the
  company timezone)

Shifts (`shift.*`):

- `GET/POST /shifts` (list: `search`, `status`)
- `GET/PATCH/DELETE /shifts/{shift_id}`

Assignments (`employee_work_assignment.*`):

- `GET/POST /employees/{id}/work-assignments`
- `GET/PATCH/DELETE /employees/{id}/work-assignments/{assignment_id}`

Attendance (`attendance.*`):

- `GET/POST /attendance` (list filters: `company_id`, `employee_id`,
  `date_from`, `date_to`, `status`, `department_id`, `branch_id`,
  `schedule_id`, `shift_id`, paging)
- `POST /attendance/check-in`, `POST /attendance/check-out`
- `GET/PATCH/DELETE /attendance/{attendance_id}`
  (DELETE takes `?reason=`)

Overtime (`overtime.*`):

- `GET/POST /overtime` (list filters: `company_id`, `employee_id`,
  `status`, `date_from`, `date_to`, paging)
- `GET/PATCH /overtime/{overtime_id}` (PATCH only in `draft`)
- `POST /overtime/{id}/submit|approve|reject|cancel|correct`

## 4. Business rules

### Work schedules and days

- Schedules are versioned: one code may cover several non-overlapping
  effective windows; overlapping windows for the same
  `(company, code)` are rejected by the gist constraint
  (`SCHEDULE_CODE_EXISTS` on the service pre-check, constraint as
  backstop). Timezone must be a valid IANA zone
  (`SCHEDULE_INVALID_TIMEZONE`); naive day/shift times are
  interpreted in the schedule timezone.
- Day rows are per ISO weekday (Monday=0). A working day defines
  EITHER a plain window (`start_time`/`end_time`) OR a pinned
  `shift_id` (`SCHEDULE_INVALID_TIME_RANGE`), never both; rest days
  must define neither and must have no breaks
  (`SCHEDULE_INVALID_BREAK`). Breaks must fit inside the effective
  window (or the pinned shift's window), must not overlap each other,
  and are flagged paid/unpaid.
- Resolution precedence: `assignment.shift_id` >
  `day.shift_id` > day window; **schedule-day breaks override shift
  breaks when both exist**.
- Deleting a schedule/shift in use fails with
  `SCHEDULE_IN_USE` / `SHIFT_IN_USE`.

### Employee work assignments

- Effective-dated closed-open `[)` intervals; gaps allowed; ranges
  validated (`ASSIGNMENT_INVALID_DATE_RANGE`).
- On create, the single open assignment (if any) is auto-closed to
  `new_start - 1 day` when the new start is later - mirroring the
  employment-history rule - otherwise the overlap is rejected
  (`SCHEDULE_ASSIGNMENT_OVERLAP`), backstopped by
  `uq_work_assignment_open` + `exq_work_assignment_no_overlap`.
- Delete is a hard delete (the assignment history is the set of
  remaining rows; audit keeps the record).

### Attendance lifecycle

- Statuses: `open` (checked in, not yet out) -> `completed` (has
  check-out); `missing_checkout` is an administrative state, inert in
  calculation. `ck_attendance_completed_has_checkout` enforces the
  invariant.
- Timezone rule: the resolution DATE comes from the company timezone,
  then a naive timestamp is interpreted in the SCHEDULE timezone
  (aware timestamps are converted); if the resolved date changes the
  record is re-anchored. This is the single place where naive
  check-in/out values acquire a timezone.
- Half-open `[)` windows; service-level overlap pre-check plus
  `uq_attendance_open` plus the gist EXCLUDE constraint
  (`ATTENDANCE_ALREADY_OPEN`, `ATTENDANCE_OVERLAP`).
- Correcting or deleting a CLOSED record requires a non-empty
  `reason` (`CORRECTION_REASON_REQUIRED`); correction of a closed
  record additionally requires `attendance.correct` on top of
  `attendance.update`. Audit action is `attendance.correct` when the
  record was closed, `attendance.update` otherwise.
- Check-in/out audit as `attendance.check_in` / `attendance.check_out`
  with timestamps.

### Attendance calculation (`app/attendance/calculation.py`)

Computed on check-out (whole minutes, floored, never negative):

- `worked_minutes` = span(check_in -> check_out) - unpaid breaks
- `scheduled_minutes` = window length - unpaid breaks (0 without a
  window)
- `break_minutes` = unpaid break minutes actually deducted (paid
  breaks never deducted; breaks outside the window ignored)
- `late_minutes` = max(0, check_in - window_start)
- `early_leave_minutes` = max(0, window_end - check_out)
- `overtime_candidate_minutes` = max(0, check_out - window_end) -
  a candidate only; approval happens in the overtime workflow

While a record is `open` (or `missing_checkout`) all six columns stay
NULL. Without a resolved schedule the raw span is stored as
`worked_minutes` and the other columns are 0.

### Overtime workflow

- Transitions (`_transition_guard`): submit from `draft`; approve and
  reject from `submitted`; cancel from `draft`/`submitted`/`approved`;
  PATCH only in `draft`; correct only from `approved`. Wrong
  transitions raise `OVERTIME_INVALID_STATUS_TRANSITION`,
  `OVERTIME_APPROVAL_REQUIRED`.
- `approved_minutes <= requested_minutes` and both in 1..1440
  (`OVERTIME_INVALID_MINUTES`); approving without an explicit value
  defaults to the requested minutes.
- Correction of an approved record requires a reason
  (`CORRECTION_REASON_REQUIRED`) and `overtime.approve`;
  `OVERTIME_ALREADY_APPROVED` guards double-approve.

### Error codes (25 new, stable, translated by frontend `error.<CODE>`)

`WORK_SCHEDULE_NOT_FOUND`, `SCHEDULE_INVALID_DATE_RANGE`,
`SCHEDULE_INVALID_TIME_RANGE`, `SCHEDULE_INVALID_BREAK`,
`SCHEDULE_CODE_EXISTS`, `SCHEDULE_IN_USE`, `SCHEDULE_INVALID_TIMEZONE`,
`SHIFT_NOT_FOUND`, `SHIFT_INVALID_TIME_RANGE`, `SHIFT_CODE_EXISTS`,
`SHIFT_IN_USE`, `WORK_ASSIGNMENT_NOT_FOUND`,
`SCHEDULE_ASSIGNMENT_OVERLAP`, `ASSIGNMENT_INVALID_DATE_RANGE`,
`ATTENDANCE_NOT_FOUND`, `ATTENDANCE_ALREADY_OPEN`,
`ATTENDANCE_OVERLAP`, `ATTENDANCE_INVALID_TIME_RANGE`,
`ATTENDANCE_MISSING_CHECKOUT`, `OVERTIME_NOT_FOUND`,
`OVERTIME_ALREADY_APPROVED`, `OVERTIME_INVALID_STATUS_TRANSITION`,
`OVERTIME_APPROVAL_REQUIRED`, `OVERTIME_INVALID_MINUTES`,
`CORRECTION_REASON_REQUIRED`.

## 5. Audit logging

22 Phase-4 audit actions (no payloads contain raw time-card secrets
beyond ids/dates/reasons):

- `work_schedule.create/update/delete` (days PUT audits
  `work_schedule.update` with `{"fields": ["days"], "weekdays": [...]}`)
- `shift.create/update/delete`
- `work_assignment.create/update/delete`
- `attendance.create/check_in/check_out/update/correct/delete`
- `overtime.create/update/submit/approve/reject/cancel/correct`

All writes go through the frozen `record_audit` helper (ip address,
actor, company). Audit-log visibility remains `audit.read`.

## 6. Frontend

- `api.ts`: Phase-4 types (schedule/day/break/assignment/attendance/
  overtime + resolved schedule) and helpers for every endpoint above,
  including `deleteAttendance(id, reason?)` and the overtime workflow
  calls.
- `pages/WorkSchedulesPage.tsx`: server-side search/status filter,
  create/edit (code, names, timezone, effective window, status,
  notes), weekday days editor (per-day working toggle, window, shift
  select from active shifts, multiple paid/unpaid breaks). The days
  editor submits ALL seven weekdays (the API upserts only submitted
  weekdays, so rest days must be sent explicitly with null times).
- `pages/ShiftsPage.tsx`: CRUD with overnight indicator derived from
  `end < start` (backend recomputes `crosses_midnight`).
- `pages/AttendancePage.tsx`: filters (date range, status, employee/
  department/branch/schedule/shift via debounced server-side
  `SearchSelect`), metric columns, check-in/check-out buttons,
  record form, inline detail expansion (source, notes, correction
  reason, schedule/shift), delete with reason prompt for closed
  records, pagination.
- `pages/OvertimePage.tsx`: filters, create/edit (draft only), and
  permission-gated submit/approve/reject/cancel/correct actions with
  status-driven visibility; approved rows render without edit
  controls; minute validation mirrors the backend rules.
- `components/AttendancePanel.tsx` + Employee Detail
  "Attendance / Schedule" tab: resolved current schedule, assignment
  history with create/edit/delete, recent attendance, recent
  overtime; every section gated by its own `.view` permission.
- `App.tsx`: routes `/attendance`, `/work-schedules`, `/shifts`,
  `/overtime` with nav entries gated by `attendance.view`,
  `work_schedule.view`, `shift.view`, `overtime.view` (permission
  codes only - no role names anywhere in the frontend).
- `i18n.ts`: full EN + AR key sets (nav, page vocabulary, statuses
  incl. `status.archived`, filters, workflow actions, all 25 error
  codes) - 355 keys per locale, verified symmetric by an automated
  key audit. Arabic cells render with `dir="rtl"`; document direction
  follows the locale toggle.

## 7. Tests

98 new tests in 7 files (total 369 = 271 frozen + 98):

| File | Tests | Focus |
|---|---|---|
| `test_work_schedules_db.py` | 15 | CRUD, versioning, overlap constraint, days/breaks validation, timezone errors |
| `test_shifts_db.py` | 11 | CRUD, overnight flag, code/in-use guards |
| `test_work_assignments_db.py` | 13 | CRUD, auto-close of open row, overlaps, resolution precedence |
| `test_attendance_db.py` | 20 | lifecycle, check-in/out, open uniqueness, overlaps, timezone anchoring, reason-gated correction/delete, audits |
| `test_attendance_calculation_db.py` | 9 | worked/scheduled/break/late/early/overtime-candidate, paid vs unpaid breaks, day-break override, no-window fallback |
| `test_overtime_db.py` | 20 | CRUD, every transition, minute guards, correction, role matrix, audits |
| `test_phase4_security_db.py` | 10 | 9-point permission matrix (incl. approve hidden from officer), raw RLS insert probes |

Adapted (no test-count change): `conftest.py` (RLS registry + clean
tables for 7 new tables), `test_rls_unit.py` (22 tables/policies),
`test_isolation_db.py`, `test_api_offline.py` (phase 4, Phase-4
OpenAPI paths, attendance removed from forbidden markers),
`test_phase2_migrations_db.py` / `test_phase3_migrations_db.py`
(head chain -> `0005_phase4_attendance`, 69 permissions).

## 8. Verification results

- `pytest -q`: **369 passed** (0 failed).
- `ruff check .`: clean.
- `npm run build` (tsc -b + vite): clean.
- `alembic check`: clean on `saudi_hr_test` ("No new upgrade
  operations detected").
- 0005 downgrade to `0004` then upgrade to `head` on `saudi_hr_test`:
  success (performed while fixing the EXCLUDE constraint), `alembic
  check` clean afterwards.
- Migration `exq_work_schedule_code_no_overlap` includes
  `code WITH =` (found and fixed during this phase - it previously
  blocked two different codes with overlapping windows).
- psql as `saudi_hr_user`: 22 tables RLS enabled + forced, 22
  policies, 69 permissions (24 Phase-4), EXCLUDE/partial-unique
  indexes present.
- i18n key audit: 276 statically used keys, 355 EN keys = 355 AR
  keys, 0 missing.
- Git: 0 commits, nothing staged (unchanged by this phase).

## 9. Known limitations / deferred items

- **Dev database not migrated**: `saudi_hr` is still at head 0004.
  `alembic upgrade head` must be run by the operator before using
  Phase-4 features locally (deliberately not run here).
- **Attendance correction UI deferred**: the backend supports
  `PATCH /attendance/{id}` with a reason for closed records
  (`attendance.update` + `attendance.correct` -> audit
  `attendance.correct`), but the UI currently offers only
  create/check-in/check-out, an inline read-only detail row, and
  delete-with-reason. No edit/correction modal yet.
- **No shift-breaks editor**: `ShiftInput.breaks` is supported by the
  API, but the Shifts page does not expose break editing; breaks are
  editable only on schedule days. (Resolution prefers schedule-day
  breaks anyway.)
- **Overtime actions use native prompts** (approve minutes, reasons)
  instead of modal forms; `window.prompt`/`window.confirm` only.
- **Attendance page has no month calendar view** - tabular
  server-side filtered list only.
- **`GET /branches` is unpaginated** (pre-existing Phase-1/2
  contract); the attendance branch filter loads the company's branch
  list and filters client-side.
- **No websocket/live updates**: lists refresh after each mutation
  only.
