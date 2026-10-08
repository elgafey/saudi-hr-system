"""Phase 8 - salary advances (interest-free advances repaid through the
frozen Phase 6 payroll deduction-rule machinery).

- ``schemas`` closed request/response payloads for the advance workflow.
- ``service``  state machine (create/update/submit/cancel/approve/reject/
  disburse/settle), self-scope + snapshot-approver authorization, event
  timeline, audit trail, and the frozen payroll-service integration.
- ``router``   ``/salary-advances`` routes (authenticate only; every rule
  is enforced in the service).
"""
