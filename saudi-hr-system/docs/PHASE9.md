# Phase 9 - HR Letters & Employment Certificates

HR letter generation end-to-end: four letter types (employment,
salary, experience, work address) in two languages (ar/en), an explicit
draft -> issued -> void / draft -> cancelled state machine, closed
server-assembled content snapshots, optional links to approved Phase 7
`hr_letter` requests with a one-active-letter-per-request guarantee,
plus an ESS "my letters" read portal. Fully additive - two new tables,
a new `/hr-letters` + `/me/letters` API, two new pages (HR + ESS), and
permission codes only. Builds on Phase 1 (foundation), Phase 2
(employee master data), Phase 3 (employee lifecycle), Phase 4
(attendance), Phase 5 (leave), Phase 6 (payroll), Phase 7 (ESS
requests & approvals), and Phase 8 (salary advances).

Status: complete. Backend **819 tests passing** (749 frozen + 70 new
Phase-9 tests across 6 new files), `ruff check` clean, `alembic check`
clean, frontend builds clean (`tsc -b && vite build`), i18n EN/AR
symmetric at 929 keys per locale (672 statically used), migration
0010 applied and round-trip verified (downgrade to 0009 and
re-upgrade) on the test database (`saudi_hr_test`). The dev database
(`saudi_hr`) is still at head `0004_phase3_employee_lifecycle` - it was
NOT migrated during this phase (or any earlier phase run here);
`alembic upgrade head` on `saudi_hr` is an operator action,
deliberately not run.

## 1. Scope

- Create: an HR actor with `hr_letter.create` creates a `draft` for an
  ACTIVE employee of an accessible company; the server assembles the
  closed `content` snapshot immediately from frozen sources (company,
  employee, contract, org data, and - for salary letters - the active
  salary assignment).
- Edit: drafts are editable (`hr_letter.update`): `purpose` and
  `language`; a language change re-assembles `content` in the target
  language.
- Issue: `hr_letter.issue` moves draft -> issued, re-assembles content
  from the still-frozen sources, stamps `issued_at/by` and freezes the
  snapshot forever.
- Void: `hr_letter.void` moves issued -> void with a REQUIRED reason
  (audit-sensitive). Cancel: `hr_letter.update` moves draft ->
  cancelled (reason optional).
- Source requests: a letter may reference one approved Phase 7
  `hr_letter` request; at most one ACTIVE (draft|issued) letter per
  request (partial unique index + service pre-check).
- ESS portal: employees with `ess.letter.view` list and read THEIR OWN
  letters (`/me/letters`); `void_reason` and void event notes are
  redacted server-side.
- Frontend: one new `/letters` HR page (create form, status/type
  filters, list, detail panel with the full action set, frozen content
  rendering and event timeline), one new `/me/letters` ESS tab, a
  permission-gated nav entry, and full EN/AR translations including
  all 9 new error codes.

Explicitly out of scope (approved design decisions + standing rules):
an approval engine, PDF/print/QR generation, attachments, email/SMS
notifications, a numbering column (the reference is derived from the
id), templates, any payroll or statutory write, salary calculations
(content only snapshots the assignment), cross-company letters,
letter amendments after issue, and Phase 10+ functionality.

## 2. Database (migration `0010_phase9_hr_letters`)

Never modify 0001-0009. Frozen SHA-256 hashes (re-verified this
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
| `0008_phase7_ess_requests` | `dbbaa5fc2efd5185eaf71d6bbe2649dc05ad3dfef5632570eb8c0886a9378c73` |
| `0009_phase8_salary_advances` | `00994a0bb8ae5aee333227cf31358e7446ffbb4e572fb94aba6e485723f8341e` |
| `0010_phase9_hr_letters` (this phase) | `9024a7fdeb4694ee1b952af47564fad339251d403ff64d05c2b9b689f4fddf93` |

Revision id `0010_phase9_hr_letters` (22 chars - fits the 32-char
`alembic_version.version_num` column). `down_revision =
0009_phase8_salary_advances`. Downgrade to 0009 and re-upgrade (both
tables, both policies, all 6 permission rows and the default-role
grants) are exercised in `test_letter_migrations_db.py`.

### 2.1 Tables (2 new; company-scoped, RLS enabled + forced)

- `hr_letters` (22 cols) - the letter: `company_id`, `employee_id`
  (CASCADE), `letter_type` (String(32)), `language` (String(2)),
  `purpose` (500), `status` (server default `draft`), `content`
  (JSONB NOT NULL - the closed server-assembled snapshot),
  `source_request_id` (FK `employee_requests`, SET NULL),
  `issued_at` + `issued_by`, `cancelled_at/by` + `cancel_reason` (500),
  `voided_at/by` + `void_reason` (500), `created_by`, `updated_by`,
  `version` (optimistic counter, default 1), `created_at/updated_at`.
  CHECKs: `ck_hr_letter_type` (4-value set), `ck_hr_letter_language`
  (`ar|en`), `ck_hr_letter_status` (draft/issued/void/cancelled),
  `ck_hr_letter_issued_consistency` (`status IN ('issued','void') =
  (issued_at IS NOT NULL)` - void always follows issue),
  `ck_hr_letter_cancelled_consistency`, `ck_hr_letter_void_consistency`
  (`voided_at` and `void_reason` exist exactly for void rows),
  `ck_hr_letter_void_reason` (`status <> 'void' OR
  length(trim(void_reason)) > 0`). Indexes:
  `ix_hr_letter_company_status`, `ix_hr_letter_company_employee`,
  `ix_hr_letter_company_created`, and the partial unique
  `uq_hr_letter_active_request` (`source_request_id` WHERE
  `source_request_id IS NOT NULL AND status IN ('draft','issued')`).
  The `reference` `LTR-000123` is a MODEL PROPERTY derived from the
  id - no column, no sequence, no numbering table.
- `hr_letter_events` (11 cols) - append-only, employee-visible
  history: `company_id`, `letter_id` (CASCADE), `action`
  (created/updated/issued/cancelled/voided), `from_status` (NULL for
  creation), `to_status`, `actor_user_id` (SET NULL), `actor_name`
  (denormalized, survives user deletion), `note` (500 - the
  cancel/void reason mirrored into history), `ip_address`
  (String(64)), `created_at`. CHECKs: `ck_hr_letter_event_action`,
  `ck_hr_letter_event_from_status`, `ck_hr_letter_event_to_status`,
  `ck_hr_letter_event_actor`. Index `ix_hr_letter_event_letter` on
  (`letter_id`, `id`).

### 2.2 Permissions (6 new; 150 total)

Frozen in the migration as `PHASE9_PERMISSIONS` (module `hr_letters`
except the ESS one):

| Code | Name | company_admin | hr_manager | hr_officer | auditor | employee |
|---|---|---|---|---|---|---|
| `hr_letter.view` | View HR letters | yes | yes | yes | yes | - |
| `hr_letter.create` | Create HR letter drafts | yes | yes | yes | - | - |
| `hr_letter.update` | Edit or cancel draft HR letters | yes | yes | yes | - | - |
| `hr_letter.issue` | Issue HR letters | yes | yes | yes | - | - |
| `hr_letter.void` | Void issued HR letters | yes | yes | - | - | - |
| `ess.letter.view` | View own letters | (yes) | - | - | - | yes |

`company_admin` gains all six through the DEFAULT_ROLES catalog
comprehension; `hr_officer` gets five (no void - the audit-sensitive
verb stays with managers); `auditor` is read-only on HR letters; the
employee self-service role gains `ess.letter.view`. The migration
backfills grants for pre-existing companies from the current catalog
(idempotent `ON CONFLICT`), and the roundtrip test proves downgrade
removes + upgrade restores every grant.

### 2.3 RLS / tenant isolation

Both tables are registered through `register_phase9_rls()` in
`app/core/rls_phase9.py` (`PHASE9_RLS_TABLES`), giving the standard
`{table}_tenant_isolation` policy: deny-by-default on `company_id
= ANY(app.current_company_ids)` with the platform-admin bypass. The
migration enables + forces RLS and creates both policies; runtime
forced-RLS, scoped SELECT, blocked cross-company INSERT/UPDATE/DELETE
and API visibility are covered in `test_letter_rls_db.py`. Total RLS
tables: 43 -> 45 (audited: 45 enabled / 45 forced / 45 policies).

## 3. API endpoints (all under `/api/v1`)

HR router `/hr-letters` (authenticate only - state, permission and
tenant rules all live in the service, Phase 7/8 pattern):

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/hr-letters` | `hr_letter.view` (scoped) | filters `company_id`, `employee_id`, `letter_type`, `status`, page; LIST PROJECTION - no content, no reasons |
| `POST` | `/hr-letters` | `hr_letter.create` (target company) | 201, body `LetterCreate` (extra=forbid) |
| `GET` | `/hr-letters/{id}` | `hr_letter.view` | full detail + events |
| `PATCH` | `/hr-letters/{id}` | `hr_letter.update` | drafts only; purpose/language |
| `POST` | `/hr-letters/{id}/issue` | `hr_letter.issue` | draft -> issued |
| `POST` | `/hr-letters/{id}/cancel` | `hr_letter.update` | draft -> cancelled, optional reason |
| `POST` | `/hr-letters/{id}/void` | `hr_letter.void` | issued -> void, reason required (service-level 400) |

ESS router `/me/letters` (route dependency `ess.letter.view`, service
scopes to the caller's own employee link):

| Method | Path | Notes |
|---|---|---|
| `GET` | `/me/letters` | own letters only, list projection |
| `GET` | `/me/letters/{id}` | own letters only; non-owned = 404 (no existence leak); `void_reason` and void-event notes redacted |

Query validation: `status` and `letter_type` use route patterns
(`^(|draft|issued|void|cancelled)$`, `^(|employment|salary|experience|work_address)$`)
so bad filter values are 422, not silent empties. Health endpoint
bumped to `"phase": 9`.

## 4. Business rules

### State machine

```
            ┌────────── issue ──────────► issued ──── void ───► void
            │                                                    (terminal)
 draft ─────┤
            └────────── cancel ────────► cancelled (terminal)
```

- Allowed sets: update/cancel = `draft`, issue = `draft`, void =
  `issued`. Everything else is `HR_LETTER_STATE_INVALID` (409).
- STATE IS CHECKED BEFORE PERMISSION (Phase 8 pattern): e.g. voiding
  a DRAFT returns 409 even for a caller without `hr_letter.void`, and
  an auditor issuing an issued letter gets 409 (not 403).
- Row fetch: missing or cross-company ids are always 404
  (`HR_LETTER_NOT_FOUND`) - no existence leak across tenants.
- Transitions run inside `SELECT ... FOR UPDATE`; `version` bumps on
  every mutation; concurrent double-issue/double-void races have
  exactly one winner (tests).

### Authorization model (roleless, no permission oracles)

- HR verbs are company-scoped permission checks in the service
  (`_require(principal, code, company_id)`); no role names appear in
  `app/letter/*` (unit test enforces the grep).
- ESS: route dependency `ess.letter.view` + service self-scope
  (`self_employee`); non-owned letters 404.
- `list_letters` without `company_id` scopes to the caller's
  `hr_letter.view` companies; `?company_id` for an inaccessible
  company is 403.

### Closed content (server-assembled, no client input)

- Four closed pydantic models (`extra="forbid"`, `app/letter/schemas.py`):
  `_LetterContentBase` (company name/CR/address/city, employee name/
  number/identity, position, department, branch, employment type,
  hire date) + per-type fields - employment (status + contract
  number/start/end), salary (`basic_salary` Decimal(12,2), `currency`,
  `salary_effective_from`), experience (status + contract start),
  work address (branch address/city).
- Assembly reads ONLY frozen sources: companies, employees, active
  contracts, departments, positions, branches, salary assignments.
  No calculations, no statutory values, no writes to other domains.
- Built at create, rebuilt on language change, re-assembled + frozen
  at issue (deterministic - tests assert issue output equals the
  draft snapshot when sources are unchanged).
- Language-localized names (`name_ar`/`name_en`, employee AR/EN name
  parts).
- `salary` letters require an ACTIVE `employee_salary_assignments`
  row (`uq_salary_assignment_open` guarantees at most one) -
  `HR_LETTER_SOURCE_MISSING` (409) at create AND at issue.
- Client payloads carrying `content` are rejected (422 extra=forbid).

### Source requests (Phase 7 integration)

- `source_request_id` must reference an approved `hr_letter` request
  of the SAME company (`HR_LETTER_REQUEST_INVALID`, 400) - checked at
  create only; the link is not re-validated later.
- One active letter per request: service pre-check (409
  `HR_LETTER_REQUEST_LINKED`) + `uq_hr_letter_active_request` partial
  unique index as the race-proof backstop (IntegrityError on flush is
  mapped to the same domain error). Cancelling a letter frees the
  request again.

### Error codes (9 stable, translated by frontend `error.<CODE>`)

| Code | Status | When |
|---|---|---|
| `HR_LETTER_NOT_FOUND` | 404 | missing / cross-tenant / non-owned ESS row |
| `HR_LETTER_FORBIDDEN` | 403 | missing company-scoped permission |
| `HR_LETTER_STATE_INVALID` | 409 | transition not allowed from current status |
| `HR_LETTER_REASON_REQUIRED` | 400 | void without a non-blank reason |
| `HR_LETTER_TYPE_INVALID` | 400 | reserved service-level type guard |
| `HR_LETTER_REQUEST_INVALID` | 400 | source request missing/not approved/wrong type/other company |
| `HR_LETTER_REQUEST_LINKED` | 409 | an active letter already references the request |
| `HR_LETTER_EMPLOYEE_INVALID` | 400 | **sanctioned addition**: unknown/cross-tenant/inactive target employee at create time |
| `HR_LETTER_SOURCE_MISSING` | 409 | **sanctioned addition**: no active salary assignment at create, or sources gone (employee no longer active) at issue |

The design named seven codes; `HR_LETTER_EMPLOYEE_INVALID` and
`HR_LETTER_SOURCE_MISSING` were added so bad INPUT stays 400 while a
letter whose sources DISAPPEAR between draft and issue is a 409
conflict - the pattern used by the frozen phases. All nine are
translated in both locales.

## 5. Audit logging

Five actions through the frozen `record_audit` (`entity="hr_letter"`):
`hr_letter.create`, `hr_letter.update`, `hr_letter.cancel`,
`hr_letter.issue`, `hr_letter.void`. The snapshot written to
`old_value/new_value` contains reference, employee/type/language/
purpose/status, source request, timestamps and version - NEVER
`content` and never a salary value (tests assert the audit rows carry
no `basic_salary`/amount). Events additionally record `ip_address`
(String(64), matching `audit_logs.ip_address` - not the design's
`ip`/INET sketch) and the denormalized actor name.

## 6. Frontend

- `api.ts`: Phase 9 block - `HrLetterListItem`/`HrLetter`/`HrLetterEvent`
  types, `HrLetterInput`/`HrLetterUpdate`, and the 9 functions
  (`listHrLetters`, `getHrLetter`, `createHrLetter`, `updateHrLetter`,
  `issueHrLetter`, `cancelHrLetter`, `voidHrLetter`, `listMyLetters`,
  `getMyLetter`).
- `/letters` HR page (`LettersPage.tsx`): permission-gated
  (`hr_letter.view`/`hr_letter.create`), create form (employee select
  from `listEmployees`, type, language, purpose - with a hint that the
  body is server-assembled), status + type filters, list table
  (reference, employee, type, language, status, issued at) and the
  detail panel.
- `HrLetterDetail.tsx`: reference/status/type/language/purpose
  metadata, frozen content rendered as a localized label/value grid
  (21 field labels + enum labels), reason displays, actions gated by
  permission AND status (edit/issue/cancel on draft, void on issued),
  void requires a reason, full event timeline.
- `/me/letters` ESS tab (`EssLettersPage.tsx`, `ess.letter.view`
  gated): own-letters list + read-only detail (server has already
  redacted void reasons/notes).
- Routes/nav: `nav.letters` entry behind `hr_letter.view ||
  hr_letter.create`, `/letters` route, ESS child route `letters` +
  `ess.tab.letters` tab behind `ess.letter.view`.
- i18n: 81 new keys per locale (nav/page/labels/statuses/events/
  content fields/ESS tab + all 9 `error.HR_LETTER_*` messages), EN/AR
  symmetric at 929 keys; the parity checker reports zero missing on
  either side.

## 7. Design refinements (decided during implementation)

1. **Two sanctioned error codes** beyond the design's seven
   (`HR_LETTER_EMPLOYEE_INVALID` 400 for create-time employee
   validation, `HR_LETTER_SOURCE_MISSING` 409 for missing sources) -
   keeps "bad input" (400) distinct from "world changed under a
   draft" (409), mirroring the frozen phases.
2. **Issue-consistency CHECK corrected**: the design sketch wrote
   `status = 'issued' = (issued_at IS NOT NULL)`, which would reject
   every void row (void keeps `issued_at`). Implemented as
   `status IN ('issued','void') = (issued_at IS NOT NULL)` - same
   intent, void-compatible; documented here as the single deliberate
   deviation from the literal DDL sketch.
3. **State check before permission check** (Phase 8 pattern)
   throughout, including void-on-draft -> 409 for everyone.
4. **`LetterVoid.reason` is optional in the schema and required in
   the service** so a missing reason is the stable 400
   `HR_LETTER_REASON_REQUIRED` (mapped by the frontend) instead of a
   FastAPI 422 validation error - the Phase 8 "closed optional field,
   service-level enforcement" pattern.
5. **`ip_address` naming** on events (String(64)) to match the frozen
   `audit_logs` convention, instead of the sketch's `ip`/INET.
6. **Reference derived, not stored**: `HrLetter.reference` property
   (`LTR-{id:06d}`) - no column to keep in sync, no sequence to seed.
7. **List projection excludes `content` AND all reason fields**
   (`LetterListOut`); audit snapshots exclude `content`; ESS redacts
   `void_reason` + the void event note but keeps `cancel_reason`
   (cancel reasons are employee-facing, void reasons are internal).
   Salary values therefore leave the server only through the
   HR/ESS DETAIL responses of a `salary` letter.
8. **Employee eligibility split across statuses**: at CREATE a
   non-active target (statuses are `draft|active|suspended|terminated`)
   is 400 `HR_LETTER_EMPLOYEE_INVALID`; at ISSUE the same condition is
   409 `HR_LETTER_SOURCE_MISSING` (the draft was valid when made).
9. **Create/update/issue/cancel/void responses return `events: []`**
   - history comes from the detail read (identical to the frozen
   advance endpoints); tests assert history through `GET`.
10. **Mutation response events vs detail**: `test_letter_db.py`
    asserts event timelines through detail reads, matching the
    Phase 8 contract rather than inventing a new one.

## 8. Tests

70 new tests in 6 files (749 frozen + 70 = 819 total):

- `test_letter_unit.py` (10): catalog/role-grant tables, closed
  content models (extra=forbid, required per type), client payloads
  reject `content`, reference derivation, all 9 exception codes/
  statuses, no-role-names grep over `app/letter/*`, model CHECK
  names.
- `test_letter_db.py` (21): full API lifecycle - draft shape +
  reference + created event, all 4 types assembled (EN/AR), list
  without content + status/type/employee filters, purpose/language
  update with content rebuild, issue freezes content + stamps
  metadata, cancel draft only, void with reason (empty -> 400,
  double-void -> 409), draft-void 409, issued mutations blocked, enum
  422s, unknown/suspended employee 400, source-request link +
  duplicate 409 + reuse after cancel, unapproved/wrong-type/missing
  request 400, salary without assignment 409, issue after suspension
  409, audit rows never contain content/salary, persisted ordered
  event history with actor + ip, happy path through the ESS portal.
- `test_letter_security_db.py` (18): 401 on every route, officer
  cannot void (manager can), officer can create/issue, manager can
  edit, auditor read-only across all 5 write verbs, plain employee
  denied on all HR routes (incl. the state-before-permission 409 on
  void-draft), ESS own-only (list/detail/foreign 404), ESS void-field
  and note redaction, full cross-company matrix (404s, 400 on foreign
  employee, 403 on foreign company filter, list scoping both sides),
  list responses leak neither content nor reasons.
- `test_letter_rls_db.py` (8): forced RLS at runtime, scoped SELECT
  per context company, blocked cross-company INSERT on both tables,
  blocked cross-company UPDATE/DELETE (rows survive), standard policy
  names, API visibility for company A.
- `test_letter_migrations_db.py` (10): frozen hashes 0001-0009 +
  pinned 0010 hash, head/chain, permission set == catalog (150),
  migration snapshot owns exactly its 6 codes, default-role letter
  grants per role, all 11 CHECKs + partial unique index + 4 indexes,
  forced-RLS policies, downgrade/upgrade roundtrip (tables, perms,
  policies, Phase 8 artifacts untouched), grant restoration for a
  pre-existing company.
- `test_letter_concurrency_db.py` (3): barrier races with per-thread
  engines - double-issue one winner, double-void one winner,
  duplicate source-request creates one winner (`ok` +
  `HrLetterStateError`/`HrLetterRequestLinkedError` exactly once).

Frozen-test adaptations (minimal, documented, assertion values only
where possible): head assertions `0009` -> `0010` (6 files), post-
upgrade version asserts -> `0010_phase9_hr_letters` (4 files),
permission totals `144` -> `150` (7 assertions), `conftest.py`
(`PHASE9_RLS_TABLES` in the hidden set + TRUNCATE of both new
tables), `test_rls_unit.py` (+`register_phase9_rls`, 43 -> 45),
`test_isolation_db.py` (43 -> 45 tables/policies),
`test_api_offline.py` (health `phase` 8 -> 9 only; the forbidden-
marker rows at line 133 were NOT touched),
`test_leave_migrations_db.py` (employee grant set += `ess.letter.view`),
`test_phase7_migrations_db.py` (`ess.*` count 4 -> 5). Frozen test
FUNCTION NAMES were left as-is (several were already stale in earlier
phases, e.g. leave's `test_migration_0006_is_head...` asserting the
current head).

## 9. Verification results

All run against `saudi_hr_test` this phase:

- `python -m pytest -q`: **819 passed** (0 failures; 2 pre-existing
  deprecation/key-length warnings).
- `python -m ruff check app tests`: **All checks passed**.
- `alembic check` (after the suite, `TEST_DATABASE_URL` set): **No
  new upgrade operations detected** (models == head migration).
- Migration roundtrip: downgrade to `0009_phase8_salary_advances` ->
  both tables gone, 6 letter permissions gone, Phase 8 tables/perms
  intact; re-upgrade -> version `0010_phase9_hr_letters`, 2 tables,
  6 perms, 2 policies, role grants restored.
- `npm run build` (`tsc -b && vite build`): clean (the >500 kB chunk
  warning is pre-existing).
- i18n parity script: `MISSING in en: []`, `MISSING in ar: []`,
  929 == 929 keys (672 statically used).
- `db_audit.py`: dev `saudi_hr` head `0004_phase3_employee_lifecycle`
  (untouched), test head `0010_phase9_hr_letters`, RLS tables 45,
  forced 45, policies 45, permissions 150.
- Frozen hash re-verification: 0001-0009 byte-identical (enforced by
  `test_frozen_migration_files_are_unchanged` + `docs/PHASE8.md`
  unchanged).
- Git audit (no commits/staging/push this phase): workspace-root repo
  (`New folder`, branch `main` @ `e41b57b`, in sync with `origin/main`)
  shows 19 modified + 13 untracked files = the complete Phase 9
  changeset, nothing staged. Note: `saudi-hr-system/` also contains a
  NESTED repository (`saudi-hr-system/.git`, branch `main` @ `a5a8270`,
  stale `origin/main` ref; created 2026-10-08 during repo housekeeping)
  that sees the same files unstaged relative to its own HEAD - future
  staging/commits must be made from the workspace-root repository, NOT
  from inside `saudi-hr-system/`.

## 10. Known limitations / deferred items

- No PDF/print/QR rendering: content is exposed as JSON for a future
  renderer; the design explicitly deferred document generation.
- No notifications: issuing a letter does not email/SMS the employee;
  they see it in the ESS portal.
- No approval engine: letters go straight draft -> issued by anyone
  with `hr_letter.issue` (letter issuance is considered an HR act,
  not an approval workflow).
- `source_request_id` is validated at CREATE only; approving/rejecting
  the linked request afterwards does not affect an existing letter
  (the active-letter partial index still prevents duplicates).
- The reference number derives from the id (`LTR-000001`); a
  fiscal/gapped numbering scheme would need a dedicated allocator.
- Content is frozen at issue: later employee data changes do NOT
  rewrite issued letters (by design), and there is no amendment flow -
  void + reissue is the path.
- Salary letters snapshot `basic_salary` from the ACTIVE assignment
  only; historical/graded salary history is not assembled.
- `HR_LETTER_TYPE_INVALID` is a service-level guard for
  check-constraint escapes (unreachable through the typed API).
- Multi-company users see letters from every company where they hold
  `hr_letter.view`; the UI always sends the first company id for
  creation context (same limitation as the frozen pages).
