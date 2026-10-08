# Phase 3 - Employee Lifecycle

Documents, contracts, employment history, and employee-user account links.
Builds on Phase 1 (foundation) and Phase 2 (employee master data, frozen).

Status: complete. Backend 271 tests passing, frontend builds clean,
migrations applied and verified on both dev (`saudi_hr`) and test
(`saudi_hr_test`) databases.

## 1. Scope

- Employee document storage (metadata in DB, files on private disk).
- Employee contracts (with "exactly one active contract" rule).
- Effective-dated employment history (append-only, overlap-safe).
- Linking one user account to one employee (login identity, not permissions).
- Server-side search/limit on `GET /api/v1/users`.
- Employee form/detail frontend: debounced server-side search selects,
  six-tab detail page with Contracts/Documents/History/User Account panels.

Out of scope (unchanged): payroll, GOSI, tax, leave, attendance,
recruitment, self-service portal, notifications, billing.

## 2. Database (migration `0004_phase3_employee_lifecycle`)

Never modify 0001/0002/0003. Frozen SHA-256 hashes (verified this phase):

| Migration | SHA-256 |
|---|---|
| `0001_phase1` | `5fe83204197a9ffcba377181188a1141fcbaafbc0606490b92ce699150d53e30` |
| `0002_security_hardening` | `2a6bc5292832040757409f42f2ba26ef565539cb671ae11003020f4a458aef8d` |
| `0003_phase2_employee_master_data` | `d5aae7696cb5fc15a0c8ea0e2bd6599375a5c2fb8b596c61fc2eb5d18e5ba324` |
| `0004_phase3_employee_lifecycle` | `798a87c0d92312866a7fa8480d74fd670fa04a43453819eedf4d2f115ffc921a` |

### 2.1 Tables (all company-scoped, all RLS enabled + forced)

- `employee_document_types` - lookup; unique `(company_id, code)`. Eight
  default types are lazily seeded per company on first list if empty.
- `employee_documents` - metadata only (file bytes live under
  `backend/storage/documents/`, never served publicly). CHECK
  `expiry_date >= issue_date` when both set; column indexes on
  `company_id`, `employee_id`, `document_type_id`.
- `employee_contracts` - CHECKs on dates (incl.
  `ck_employee_contract_termination_within_term`); partial unique index
  `uq_employee_contract_active` (one `status='active'` row per employee);
  unique `(company_id, contract_number)` (`uq_employee_contract_company_number`);
  column indexes on `company_id` and `employee_id`.
- `employee_employment_history` - effective-dated, append-only. Partial
  unique `uq_employee_history_open` (one open interval per employee);
  exclusion constraint `exq_employee_history_no_overlap` (EXCLUDE gist,
  `[)` range, no overlaps) as backstop to service-level checks;
  `ix_employee_history_effective` on `(employee_id, effective_from)`.

### 2.2 `users.employee_id`

Phase 1 left `employee_id` as a nullable placeholder with non-unique index
`ix_users_employee_id`. 0004 drops that index and creates a real unique
constraint `users_employee_id_key` plus FK `users_employee_id_fkey` to
`employees.id` ON DELETE SET NULL: one account per employee, one employee
per user; deleting either side keeps the other. Verified on both DBs.

### 2.3 Permissions (13 new; 45 total)

Frozen `PHASE3_PERMISSIONS` tuple inside migration 0004:

`employee_document.view/create/update/delete/download`,
`employee_contract.view/create/update/delete`,
`employee_history.view/create`,
`employee_user_link.view/manage`.

Role backfill (with GUC elevation for the 0002 guard): hr_manager (all but
deletes), hr_officer (document view/create/download, contract view, history
view, link view), auditor (view-only + document download), company_admin
(all 13).

### 2.4 RLS

Four new tables join the frozen registry (15 tables / 15 policies total):
enable + FORCE + `tenant_isolation` policy on `company_id`, registered from
`main.py`, `cli.py`, the migration itself, and test helpers.

## 3. API endpoints (all under `/api/v1`)

Documents (`employee_document.*`):

- `GET/POST /employees/{id}/documents` (list supports `page`, `page_size`,
  `document_type_id`; POST is multipart: `document_type_id`,
  `document_number`, `issue_date`, `expiry_date`, `notes`, `file`)
- `GET/PATCH/DELETE /employees/{id}/documents/{doc_id}`
- `GET /employees/{id}/documents/{doc_id}/download` (RFC 5987
  Content-Disposition, `X-Content-Type-Options: nosniff`, audit
  `document.download`)
- `GET/POST /employee-document-types` (list is lazy-seeded per company)

Contracts (`employee_contract.*`):

- `GET/POST /employees/{id}/contracts` (list supports `status` filter)
- `GET/PATCH/DELETE /employees/{id}/contracts/{contract_id}`

History (`employee_history.*`):

- `GET/POST /employees/{id}/employment-history`

Account link (`employee_user_link.*`):

- `GET /employees/{id}/user` -> `{linked, user|null}`
- `POST /employees/{id}/user` `{user_id}`
- `DELETE /employees/{id}/user`

Enhanced: `GET /users` gained `search` (ilike email/full_name) and
`limit` (1..100) for autocomplete; response remains a list (Phase-1
contract kept).

## 4. Business rules

### Documents

- Files: 10 MB max, magic-byte sniffing (PDF/JPEG/PNG/WebP/TIFF); declared
  vs sniffed MIME mismatch rejected; server-generated storage keys
  `company_{id}/employee_{id}/{uuid}.{ext}` (path traversal impossible).
- Date rule: expiry cannot precede issue (`DOCUMENT_INVALID_DATE_RANGE`).
- Audits: `document.upload/update/delete/download` - never file bytes.
- Delete removes DB row first, then best-effort file cleanup
  (`OSError` swallowed).

### Contracts

- Date validation: `end_date >= start_date`, `termination_date >=
  start_date`, `termination_date <= end_date`
  (`CONTRACT_INVALID_DATE_RANGE`), active-contract uniqueness via
  pre-check + partial-unique index catch
  (`CONTRACT_ACTIVE_EXISTS`, 409), company-scoped contract number
  uniqueness (409). No general date-overlap prohibition - overlapping or
  back-to-back contracts are allowed; only status `active` is exclusive.

### Employment history

- Employee master row = current state; history is append-only. Org changes
  through `PATCH /employees/{id}` auto-append (or amend same-day open row)
  a history record with `auto: true`, `reason: "employee_update"` - no
  extra permission, audited as `employment_history.create/update`.
- Explicit `POST` requires `employee_history.create`, honors
  `apply_to_employee` (default true, full-snapshot apply).
- Overlap algorithm: closed-open `[)` intervals; gaps allowed; new period
  overlapping an open predecessor auto-closes it (`to = from - 1 day`),
  otherwise `EMPLOYEE_HISTORY_OVERLAP` (409); backstopped by the gist
  exclusion constraint and `uq_employee_history_open`.

### Account link

- One link per employee and per user (unique FK + pre-checks).
- Cross-company: RLS-hidden users surface as 404 `USER_NOT_FOUND`; visible
  but mismatched company as 403 `CROSS_COMPANY_RELATION`.
- Linking elevates `app.is_platform_admin` transaction-locally
  (`employees/link_service._set_employee_link`) to pass the frozen 0002
  `users` guard trigger, restored in `finally`.
- Audits: `employee_user_link.link/unlink` with `{user_id, employee_id}`.
- The linked account gains no permissions from the link - permissions come
  only from roles.

### Error codes (19, stable, translated by frontend `error.<CODE>`)

`EMPLOYEE_NOT_FOUND`, `DOCUMENT_NOT_FOUND`, `DOCUMENT_ACCESS_DENIED`,
`DOCUMENT_FILE_TOO_LARGE`, `DOCUMENT_INVALID_MIME_TYPE`,
`DOCUMENT_EMPTY_FILE`, `DOCUMENT_INVALID_PATH`, `DOCUMENT_TYPE_NOT_FOUND`,
`DOCUMENT_INVALID_DATE_RANGE`, `CONTRACT_NOT_FOUND`,
`CONTRACT_INVALID_DATE_RANGE`, `CONTRACT_ACTIVE_EXISTS`,
`EMPLOYEE_HISTORY_NOT_FOUND`, `EMPLOYEE_HISTORY_OVERLAP`,
`EMPLOYEE_HISTORY_INVALID_DATE_RANGE`, `EMPLOYEE_ALREADY_LINKED`,
`USER_ALREADY_LINKED`, `USER_NOT_FOUND`, `CROSS_COMPANY_RELATION`.

## 5. Frontend

- `api.ts`: `ApiError.code` (parsed from body `code`), Phase-3 types and
  helpers (documents + blob download with 401-refresh retry, contracts,
  history, user link, `listUsers({search, limit})`,
  `getJobPosition`/`getJobGrade`/`getUser`).
- `ui.ts`: `errorMessage(error, fallback, t?)` prefers the translated
  `error.<CODE>` when present.
- `components/SearchSelect.tsx`: debounced (300 ms) server-side search
  select with label resolution by id; used by the employee form
  (department/position/grade/manager), history form, and user search -
  no more 200-row client fetches for these lookups.
- `pages/EmployeeDetailPage.tsx`: six permission-gated tabs (Profile,
  Employment, Contracts, Documents, History, User Account); org names
  resolved individually by id.
- `components/ContractsPanel.tsx`, `DocumentsPanel.tsx` (upload/download/
  metadata edit/delete with 413/415/400/422 messaging),
  `HistoryPanel.tsx` (create with `apply_to_employee`), and
  `UserAccountPanel.tsx` (search/link/unlink).
- `i18n.ts`: ~100 new keys in EN + AR (tabs, fields, contract/document/
  history/account vocabulary, all 19 error codes).

## 6. Tests

71 new tests in 7 files (total 271 = 200 frozen + 71):

| File | Tests | Focus |
|---|---|---|
| `test_documents_db.py` | 16 | upload/scan/magic-bytes/limits/dates/types/download/audits |
| `test_contracts_db.py` | 11 | CRUD, dates, active uniqueness, number conflict, audits |
| `test_employment_history_db.py` | 15 | overlap/split/amend/auto-append/apply/audits |
| `test_employee_user_link_db.py` | 9 | link/unlink, cross-company, duplicates, guard trigger |
| `test_phase3_security_db.py` | 10 | 9-point permission matrix, raw RLS insert probe |
| `test_phase3_search_db.py` | 3 | 210-row server-side search/limit |
| `test_phase3_migrations_db.py` | 7 | 4 hash pins, head chain, 45 perms, role matrix, constraints, `alembic check` |

Adapted (no test-count change): `conftest.py` (RLS registry + clean tables),
`test_rls_unit.py`, `test_api_offline.py`, `test_isolation_db.py`,
`test_phase2_migrations_db.py` (0004 chain, 45 permissions).

## 7. Verification results

- `pytest -q`: **271 passed** (0 failed).
- `ruff check .`: clean.
- `npm run build` (tsc -b + vite): clean.
- `alembic check`: clean on `saudi_hr` and `saudi_hr_test`.
- 0004 downgrade to `0003` then upgrade to `head` on `saudi_hr_test`:
  success, `alembic check` clean afterwards.
- psql as `saudi_hr_user`: 15 tables RLS enabled + forced, 15 policies,
  45 permissions (13 Phase-3), exclusion/partial/unique indexes present,
  `users_employee_id_key` unique + `users_employee_id_fkey` SET NULL,
  placeholder `ix_users_employee_id` dropped, `btree_gist` installed,
  4 CHECK constraints on the three new entity tables.
- Git: 0 commits, nothing staged (unchanged by this phase).

## 8. Known non-blocking issues

- PATCH document metadata cannot clear a field to `null` (Pydantic
  `None` means "not provided"); create/update text fields only.
- `POST /employee-document-types` has no update/delete UI (API supports
  create; types are mostly system-seeded).
- `SearchSelect` shows `#id` if label resolution 404s (e.g. caller lacks
  `user.read` for `/users/{id}`); list labels are still correct.
