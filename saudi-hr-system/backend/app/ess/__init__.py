"""Phase 7 - Employee Self-Service (ESS) + requests & approvals.

- ``payloads``   closed payload schemas per request type (shared by the
  request service and the attendance-correction handler).
- ``service``    request core: self-scope helpers + the workflow state
  machine (create/update/submit/cancel/approve/reject) with events, audit
  and the approvals inbox.
- ``attendance`` approval-time handler that writes ``attendance_records``.
- ``me_service`` read-only /me endpoints (profile, documents, attendance,
  payslips) - all self-scoped with ``ess.*`` company-scoped checks.
- ``router``     ``/me``, ``/employee-requests`` and ``/approvals`` routes.
"""
