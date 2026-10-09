from __future__ import annotations


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class UnauthorizedError(DomainError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(DomainError):
    status_code = 403
    code = "forbidden"


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


# ---------------------------------------------------------------------------
# Phase 3 (employee lifecycle) - stable, frontend-facing error codes.
# Frontend i18n translates the `code` field; `detail` stays human-readable.
# ---------------------------------------------------------------------------


class EmployeeNotFoundError(NotFoundError):
    code = "EMPLOYEE_NOT_FOUND"


class DocumentNotFoundError(NotFoundError):
    code = "DOCUMENT_NOT_FOUND"


class DocumentAccessDeniedError(ForbiddenError):
    code = "DOCUMENT_ACCESS_DENIED"


class DocumentFileTooLargeError(DomainError):
    status_code = 413
    code = "DOCUMENT_FILE_TOO_LARGE"


class DocumentInvalidMimeTypeError(DomainError):
    status_code = 415
    code = "DOCUMENT_INVALID_MIME_TYPE"


class DocumentEmptyFileError(DomainError):
    status_code = 400
    code = "DOCUMENT_EMPTY_FILE"


class DocumentInvalidPathError(DomainError):
    status_code = 400
    code = "DOCUMENT_INVALID_PATH"


class DocumentTypeNotFoundError(NotFoundError):
    code = "DOCUMENT_TYPE_NOT_FOUND"


class DocumentDateRangeError(DomainError):
    status_code = 400
    code = "DOCUMENT_INVALID_DATE_RANGE"


class ContractNotFoundError(NotFoundError):
    code = "CONTRACT_NOT_FOUND"


class ContractDateRangeError(DomainError):
    status_code = 400
    code = "CONTRACT_INVALID_DATE_RANGE"


class ContractActiveExistsError(ConflictError):
    code = "CONTRACT_ACTIVE_EXISTS"


class EmploymentHistoryNotFoundError(NotFoundError):
    code = "EMPLOYEE_HISTORY_NOT_FOUND"


class EmploymentHistoryOverlapError(ConflictError):
    code = "EMPLOYEE_HISTORY_OVERLAP"


class EmploymentHistoryDateRangeError(DomainError):
    status_code = 400
    code = "EMPLOYEE_HISTORY_INVALID_DATE_RANGE"


class EmployeeAlreadyLinkedError(ConflictError):
    code = "EMPLOYEE_ALREADY_LINKED"


class UserAlreadyLinkedError(ConflictError):
    code = "USER_ALREADY_LINKED"


class UserNotFoundError(NotFoundError):
    code = "USER_NOT_FOUND"


class CrossCompanyRelationError(ForbiddenError):
    code = "CROSS_COMPANY_RELATION"


# ---------------------------------------------------------------------------
# Phase 4 (attendance domain) - stable, frontend-facing error codes.
# Required by spec: ATTENDANCE_ALREADY_OPEN, ATTENDANCE_OVERLAP,
# ATTENDANCE_INVALID_TIME_RANGE, ATTENDANCE_MISSING_CHECKOUT,
# SCHEDULE_INVALID_TIME_RANGE, SCHEDULE_ASSIGNMENT_OVERLAP,
# SHIFT_INVALID_TIME_RANGE, OVERTIME_ALREADY_APPROVED,
# OVERTIME_INVALID_STATUS_TRANSITION, OVERTIME_APPROVAL_REQUIRED.
# ---------------------------------------------------------------------------


class WorkScheduleNotFoundError(NotFoundError):
    code = "WORK_SCHEDULE_NOT_FOUND"


class WorkScheduleDateRangeError(DomainError):
    status_code = 400
    code = "SCHEDULE_INVALID_DATE_RANGE"


class WorkScheduleTimeRangeError(DomainError):
    status_code = 400
    code = "SCHEDULE_INVALID_TIME_RANGE"


class WorkScheduleBreakError(DomainError):
    status_code = 400
    code = "SCHEDULE_INVALID_BREAK"


class WorkScheduleCodeExistsError(ConflictError):
    code = "SCHEDULE_CODE_EXISTS"


class WorkScheduleInUseError(ConflictError):
    code = "SCHEDULE_IN_USE"


class ScheduleTimezoneError(DomainError):
    status_code = 400
    code = "SCHEDULE_INVALID_TIMEZONE"


class ShiftNotFoundError(NotFoundError):
    code = "SHIFT_NOT_FOUND"


class ShiftTimeRangeError(DomainError):
    status_code = 400
    code = "SHIFT_INVALID_TIME_RANGE"


class ShiftCodeExistsError(ConflictError):
    code = "SHIFT_CODE_EXISTS"


class ShiftInUseError(ConflictError):
    code = "SHIFT_IN_USE"


class WorkAssignmentNotFoundError(NotFoundError):
    code = "WORK_ASSIGNMENT_NOT_FOUND"


class WorkAssignmentOverlapError(ConflictError):
    code = "SCHEDULE_ASSIGNMENT_OVERLAP"


class WorkAssignmentDateRangeError(DomainError):
    status_code = 400
    code = "ASSIGNMENT_INVALID_DATE_RANGE"


class AttendanceNotFoundError(NotFoundError):
    code = "ATTENDANCE_NOT_FOUND"


class AttendanceAlreadyOpenError(ConflictError):
    code = "ATTENDANCE_ALREADY_OPEN"


class AttendanceOverlapError(ConflictError):
    code = "ATTENDANCE_OVERLAP"


class AttendanceTimeRangeError(DomainError):
    status_code = 400
    code = "ATTENDANCE_INVALID_TIME_RANGE"


class AttendanceMissingCheckoutError(DomainError):
    status_code = 400
    code = "ATTENDANCE_MISSING_CHECKOUT"


class OvertimeNotFoundError(NotFoundError):
    code = "OVERTIME_NOT_FOUND"


class OvertimeAlreadyApprovedError(ConflictError):
    code = "OVERTIME_ALREADY_APPROVED"


class OvertimeInvalidTransitionError(ConflictError):
    code = "OVERTIME_INVALID_STATUS_TRANSITION"


class OvertimeApprovalRequiredError(ConflictError):
    code = "OVERTIME_APPROVAL_REQUIRED"


class OvertimeInvalidMinutesError(DomainError):
    status_code = 400
    code = "OVERTIME_INVALID_MINUTES"


class CorrectionReasonRequiredError(DomainError):
    status_code = 400
    code = "CORRECTION_REASON_REQUIRED"


# ---------------------------------------------------------------------------
# Phase 5 - leave management (stable error codes, docs/PHASE5.md).
# ---------------------------------------------------------------------------


class LeaveTypeNotFoundError(NotFoundError):
    code = "LEAVE_TYPE_NOT_FOUND"


class LeaveTypeCodeExistsError(ConflictError):
    code = "LEAVE_TYPE_CODE_EXISTS"


class LeaveTypeInUseError(ConflictError):
    code = "LEAVE_TYPE_IN_USE"


class LeaveTypeInactiveError(ConflictError):
    code = "LEAVE_TYPE_INACTIVE"


class LeaveTypeRangeError(DomainError):
    status_code = 400
    code = "LEAVE_TYPE_INVALID_RANGE"


class StatutoryRuleNotFoundError(NotFoundError):
    code = "STATUTORY_RULE_NOT_FOUND"


class StatutoryRuleOverlapError(ConflictError):
    code = "STATUTORY_RULE_OVERLAP"


class StatutoryRuleSourceRequiredError(DomainError):
    status_code = 400
    code = "STATUTORY_RULE_SOURCE_REQUIRED"


class StatutoryRuleDateRangeError(DomainError):
    status_code = 400
    code = "STATUTORY_RULE_INVALID_DATE_RANGE"


class LeaveAllocationNotFoundError(NotFoundError):
    code = "LEAVE_ALLOCATION_NOT_FOUND"


class LeaveAllocationOverlapError(ConflictError):
    code = "LEAVE_ALLOCATION_OVERLAP"


class LeaveAllocationInvalidDaysError(DomainError):
    status_code = 400
    code = "LEAVE_ALLOCATION_INVALID_DAYS"


class LeaveAllocationStateError(ConflictError):
    code = "LEAVE_ALLOCATION_STATE_INVALID"


class LeaveAllocationInUseError(ConflictError):
    code = "LEAVE_ALLOCATION_IN_USE"


class LeaveCarryForwardError(DomainError):
    status_code = 400
    code = "LEAVE_CARRY_FORWARD_INVALID"


class LeaveRequestNotFoundError(NotFoundError):
    code = "LEAVE_REQUEST_NOT_FOUND"


class LeaveRequestOverlapError(ConflictError):
    code = "LEAVE_REQUEST_OVERLAP"


class LeaveRequestRangeError(DomainError):
    status_code = 400
    code = "LEAVE_REQUEST_INVALID_RANGE"


class LeaveRequestTimesError(DomainError):
    status_code = 400
    code = "LEAVE_REQUEST_INVALID_TIMES"


class LeaveRequestDaysError(DomainError):
    status_code = 400
    code = "LEAVE_REQUEST_INVALID_DAYS"


class LeaveRequestStateError(ConflictError):
    code = "LEAVE_REQUEST_STATE_INVALID"


class LeaveRequestAttachmentRequiredError(DomainError):
    status_code = 400
    code = "LEAVE_REQUEST_ATTACHMENT_REQUIRED"


class LeaveRequestReasonRequiredError(DomainError):
    status_code = 400
    code = "LEAVE_REQUEST_REASON_REQUIRED"


class LeaveDecisionReasonRequiredError(DomainError):
    status_code = 400
    code = "LEAVE_DECISION_REASON_REQUIRED"


class LeaveInsufficientBalanceError(ConflictError):
    code = "LEAVE_INSUFFICIENT_BALANCE"


class LeaveOnlyNonWorkingDaysError(DomainError):
    status_code = 400
    code = "LEAVE_ONLY_NON_WORKING_DAYS"


class LeaveNoScheduleError(DomainError):
    status_code = 400
    code = "LEAVE_NO_SCHEDULE"


class LeaveEmployeeNotActiveError(ConflictError):
    code = "LEAVE_EMPLOYEE_NOT_ACTIVE"


class LeaveAttendanceOpenConflictError(ConflictError):
    code = "LEAVE_ATTENDANCE_OPEN_CONFLICT"


class LeaveAttendanceRecordExistsError(ConflictError):
    code = "LEAVE_ATTENDANCE_RECORD_EXISTS"


class LeaveOvertimeConflictError(ConflictError):
    code = "LEAVE_OVERTIME_CONFLICT"


class CompanyHolidayNotFoundError(NotFoundError):
    code = "HOLIDAY_NOT_FOUND"


class CompanyHolidayExistsError(ConflictError):
    code = "HOLIDAY_EXISTS"


# ---------------------------------------------------------------------------
# Phase 6 - payroll & salary management (stable error codes, docs/PHASE6.md).
# ---------------------------------------------------------------------------


class SalaryComponentNotFoundError(NotFoundError):
    code = "SALARY_COMPONENT_NOT_FOUND"


class SalaryComponentCodeExistsError(ConflictError):
    code = "SALARY_COMPONENT_CODE_EXISTS"


class SalaryComponentInUseError(ConflictError):
    code = "SALARY_COMPONENT_IN_USE"


class SalaryAssignmentNotFoundError(NotFoundError):
    code = "SALARY_ASSIGNMENT_NOT_FOUND"


class SalaryAssignmentOverlapError(ConflictError):
    code = "SALARY_ASSIGNMENT_OVERLAP"


class SalaryAssignmentDateRangeError(DomainError):
    status_code = 400
    code = "SALARY_ASSIGNMENT_INVALID_DATE_RANGE"


class PayrollPeriodNotFoundError(NotFoundError):
    code = "PAYROLL_PERIOD_NOT_FOUND"


class PayrollPeriodExistsError(ConflictError):
    code = "PAYROLL_PERIOD_EXISTS"


class PayrollPeriodRangeError(DomainError):
    status_code = 400
    code = "PAYROLL_PERIOD_INVALID_RANGE"


class PayrollPeriodStateError(ConflictError):
    code = "PAYROLL_PERIOD_STATE_INVALID"


class PayrollRunNotFoundError(NotFoundError):
    code = "PAYROLL_RUN_NOT_FOUND"


class PayrollAttendanceOpenError(ConflictError):
    code = "PAYROLL_ATTENDANCE_OPEN"

    def __init__(self, detail: str, details: list | None = None):
        super().__init__(detail)
        # Structured employee/date/status rows so callers (and tests) can
        # show exactly which attendance records must be closed first.
        self.details = details or []


class PayrollInputsChangedError(ConflictError):
    code = "PAYROLL_INPUTS_CHANGED"


class PayrollStatutoryRuleError(ConflictError):
    code = "PAYROLL_STATUTORY_RULE_UNVERIFIED"


class PayrollReconciliationError(DomainError):
    status_code = 500
    code = "PAYROLL_RECONCILIATION_FAILED"


class PayrollNotCalculatedError(ConflictError):
    code = "PAYROLL_NOT_CALCULATED"


class PayrollImmutableError(ConflictError):
    code = "PAYROLL_IMMUTABLE"


class PayrollAdjustmentNotFoundError(NotFoundError):
    code = "PAYROLL_ADJUSTMENT_NOT_FOUND"


class PayrollAdjustmentStateError(ConflictError):
    code = "PAYROLL_ADJUSTMENT_STATE_INVALID"


class PayrollAdjustmentTargetError(ConflictError):
    code = "PAYROLL_ADJUSTMENT_INVALID_TARGET"


class PayrollDeductionNotFoundError(NotFoundError):
    code = "PAYROLL_DEDUCTION_NOT_FOUND"


class PayrollDeductionStateError(ConflictError):
    code = "PAYROLL_DEDUCTION_STATE_INVALID"


class PayrollStatutoryRuleNotFoundError(NotFoundError):
    code = "PAYROLL_STATUTORY_RULE_NOT_FOUND"


class PayrollStatutoryRuleOverlapError(ConflictError):
    code = "PAYROLL_STATUTORY_RULE_OVERLAP"


class PayrollStatutoryRuleSourceRequiredError(DomainError):
    status_code = 400
    code = "PAYROLL_STATUTORY_RULE_SOURCE_REQUIRED"


class PayrollStatutoryRuleDateRangeError(DomainError):
    status_code = 400
    code = "PAYROLL_STATUTORY_RULE_INVALID_DATE_RANGE"


class PayrollStatutoryRuleValueError(DomainError):
    status_code = 400
    code = "PAYROLL_STATUTORY_RULE_INVALID_VALUE"


class PayrollNoSalaryAssignmentError(ConflictError):
    code = "PAYROLL_NO_SALARY_ASSIGNMENT"


# ---------------------------------------------------------------------------
# Phase 7 - employee self-service & request/approval framework (stable error
# codes, docs/PHASE7.md). Frontend i18n translates the `code` field.
# ---------------------------------------------------------------------------


class EssNotLinkedError(ForbiddenError):
    code = "ESS_NOT_LINKED"


class EssDocumentNotSharedError(ForbiddenError):
    code = "ESS_DOCUMENT_NOT_SHARED"


class EmployeeRequestNotFoundError(NotFoundError):
    code = "EMPLOYEE_REQUEST_NOT_FOUND"


class EmployeeRequestStateError(ConflictError):
    code = "EMPLOYEE_REQUEST_STATE_INVALID"


class EmployeeRequestForbiddenError(ForbiddenError):
    code = "EMPLOYEE_REQUEST_FORBIDDEN"


class EmployeeRequestTypeError(DomainError):
    status_code = 400
    code = "EMPLOYEE_REQUEST_TYPE_UNSUPPORTED"


class EmployeeRequestPayloadError(DomainError):
    status_code = 400
    code = "EMPLOYEE_REQUEST_INVALID_PAYLOAD"


class EmployeeRequestDecisionReasonError(DomainError):
    status_code = 400
    code = "EMPLOYEE_REQUEST_DECISION_REASON_REQUIRED"


class EmployeeRequestRecordMismatchError(DomainError):
    status_code = 400
    code = "EMPLOYEE_REQUEST_RECORD_MISMATCH"


class AttendanceCorrectionError(DomainError):
    status_code = 400
    code = "ATTENDANCE_CORRECTION_INVALID"


class AttendanceCorrectionStaleError(ConflictError):
    code = "ATTENDANCE_CORRECTION_STALE"


class PayslipNotOwnError(ForbiddenError):
    code = "PAYSLIP_NOT_OWN"


# ---------------------------------------------------------------------------
# Phase 8 - salary advances (stable error codes, docs/PHASE8.md).
# ---------------------------------------------------------------------------


class SalaryAdvanceNotFoundError(NotFoundError):
    code = "SALARY_ADVANCE_NOT_FOUND"


class SalaryAdvanceForbiddenError(ForbiddenError):
    code = "SALARY_ADVANCE_FORBIDDEN"


class SalaryAdvanceStateError(ConflictError):
    code = "SALARY_ADVANCE_STATE_INVALID"


class SalaryAdvanceAmountError(DomainError):
    status_code = 400
    code = "SALARY_ADVANCE_AMOUNT_INVALID"


class SalaryAdvanceInstallmentError(DomainError):
    status_code = 400
    code = "SALARY_ADVANCE_INSTALLMENT_INVALID"


class SalaryAdvanceReasonRequiredError(DomainError):
    status_code = 400
    code = "SALARY_ADVANCE_REASON_REQUIRED"


class SalaryAdvanceRuleMissingError(ConflictError):
    code = "SALARY_ADVANCE_RULE_MISSING"


# ---------------------------------------------------------------------------
# Phase 9 - HR letters (stable error codes, docs/PHASE9.md).
# ---------------------------------------------------------------------------


class HrLetterNotFoundError(NotFoundError):
    code = "HR_LETTER_NOT_FOUND"


class HrLetterForbiddenError(ForbiddenError):
    code = "HR_LETTER_FORBIDDEN"


class HrLetterStateError(ConflictError):
    code = "HR_LETTER_STATE_INVALID"


class HrLetterReasonRequiredError(DomainError):
    status_code = 400
    code = "HR_LETTER_REASON_REQUIRED"


class HrLetterTypeError(DomainError):
    status_code = 400
    code = "HR_LETTER_TYPE_INVALID"


class HrLetterRequestError(DomainError):
    status_code = 400
    code = "HR_LETTER_REQUEST_INVALID"


class HrLetterRequestLinkedError(ConflictError):
    code = "HR_LETTER_REQUEST_LINKED"


class HrLetterEmployeeInvalidError(DomainError):
    status_code = 400
    code = "HR_LETTER_EMPLOYEE_INVALID"


class HrLetterSourceMissingError(ConflictError):
    code = "HR_LETTER_SOURCE_MISSING"
