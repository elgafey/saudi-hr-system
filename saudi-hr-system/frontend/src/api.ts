const API_BASE = "/api/v1";

let accessToken: string | null = null;
let activeCompanyId: number | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setActiveCompanyId(companyId: number | null): void {
  activeCompanyId = companyId;
}

function readCsrfCookie(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)hr_csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

export interface MeResponse {
  user: {
    id: number;
    email: string;
    full_name: string;
    is_platform_admin: boolean;
    company_id: number | null;
    employee_id: number | null;
  };
  company_ids: number[];
  permissions: string[];
}

export class ApiError extends Error {
  status: number;
  code: string | null;
  constructor(status: number, message: string, code?: string | null) {
    super(message);
    this.status = status;
    this.code = code ?? null;
  }
}

function readErrorCode(body: unknown): string | null {
  if (body && typeof body === "object" && "code" in body) {
    const code = (body as { code: unknown }).code;
    if (typeof code === "string") {
      return code;
    }
  }
  return null;
}

function extractDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const messages = detail.map((entry) => {
        if (entry && typeof entry === "object" && "msg" in entry) {
          return String((entry as { msg: unknown }).msg);
        }
        return JSON.stringify(entry);
      });
      return messages.join("; ");
    }
  }
  return fallback;
}

function buildHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  if (activeCompanyId !== null) {
    headers.set("X-Company-Id", String(activeCompanyId));
  }
  return headers;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  retryOn401 = true,
): Promise<T> {
  const headers = buildHeaders(init.headers);
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (response.status === 401 && retryOn401 && !path.startsWith("/auth/login")) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return request<T>(path, init, false);
    }
  }

  if (!response.ok) {
    let detail = response.statusText;
    let code: string | null = null;
    try {
      const body = await response.json();
      detail = extractDetail(body, detail);
      code = readErrorCode(body);
    } catch {
      // non-JSON error body
    }
    throw new ApiError(response.status, detail, code);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function tryRefresh(): Promise<boolean> {
  const csrf = readCsrfCookie();
  if (!csrf) {
    return false;
  }
  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "X-CSRF-Token": csrf },
      credentials: "include",
    });
    if (!response.ok) {
      accessToken = null;
      return false;
    }
    const body = (await response.json()) as { access_token: string };
    accessToken = body.access_token;
    return true;
  } catch {
    accessToken = null;
    return false;
  }
}

export async function bootstrapSession(): Promise<MeResponse | null> {
  const ok = await tryRefresh();
  if (!ok) {
    return null;
  }
  try {
    return await request<MeResponse>("/auth/me", {}, false);
  } catch {
    accessToken = null;
    return null;
  }
}

export async function login(
  identifier: string,
  password: string,
): Promise<MeResponse> {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier, password }),
    credentials: "include",
  });
  if (!response.ok) {
    let detail = "Sign in failed";
    let code: string | null = null;
    try {
      const body = await response.json();
      detail = extractDetail(body, detail);
      code = readErrorCode(body);
    } catch {
      // ignore
    }
    throw new ApiError(response.status, detail, code);
  }
  const body = (await response.json()) as { access_token: string };
  accessToken = body.access_token;
  return request<MeResponse>("/auth/me", {}, false);
}

export async function logout(): Promise<void> {
  const csrf = readCsrfCookie();
  if (csrf) {
    await fetch(`${API_BASE}/auth/logout`, {
      method: "POST",
      headers: { "X-CSRF-Token": csrf },
      credentials: "include",
    }).catch(() => undefined);
  }
  accessToken = null;
}

export interface PageMeta {
  page: number;
  page_size: number;
  total: number;
}

export interface PageResponse<T> {
  items: T[];
  page: PageMeta;
}

export interface Department {
  id: number;
  company_id: number;
  parent_id: number | null;
  code: string;
  name_ar: string;
  name_en: string;
  description: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface DepartmentInput {
  company_id: number;
  parent_id?: number | null;
  code: string;
  name_ar: string;
  name_en: string;
  description?: string | null;
  status?: string;
}

export interface JobPosition {
  id: number;
  company_id: number;
  department_id: number | null;
  code: string;
  name_ar: string;
  name_en: string;
  description: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface JobPositionInput {
  company_id: number;
  department_id?: number | null;
  code: string;
  name_ar: string;
  name_en: string;
  description?: string | null;
  status?: string;
}

export interface JobGrade {
  id: number;
  company_id: number;
  code: string;
  name_ar: string;
  name_en: string;
  description: string | null;
  level: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface JobGradeInput {
  company_id: number;
  code: string;
  name_ar: string;
  name_en: string;
  description?: string | null;
  level: number;
  status?: string;
}

export interface Branch {
  id: number;
  company_id: number;
  name: string;
  name_ar: string | null;
  code: string;
  address: string | null;
  city: string | null;
  status: string;
}

export interface Employee {
  id: number;
  company_id: number;
  branch_id: number | null;
  department_id: number | null;
  job_position_id: number | null;
  job_grade_id: number | null;
  manager_id: number | null;
  employee_number: string;
  first_name_ar: string;
  middle_name_ar: string | null;
  last_name_ar: string;
  first_name_en: string;
  middle_name_en: string | null;
  last_name_en: string;
  date_of_birth: string | null;
  gender: string | null;
  nationality: string;
  personal_email: string | null;
  work_email: string | null;
  mobile_phone: string | null;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  identity_type: string | null;
  identity_number: string | null;
  identity_issue_date: string | null;
  identity_expiry_date: string | null;
  status: string;
  employment_type: string;
  hire_date: string | null;
  probation_end_date: string | null;
  termination_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface EmployeeInput {
  company_id: number;
  employee_number?: string | null;
  first_name_ar: string;
  middle_name_ar?: string | null;
  last_name_ar: string;
  first_name_en: string;
  middle_name_en?: string | null;
  last_name_en: string;
  date_of_birth?: string | null;
  gender?: string | null;
  nationality?: string;
  personal_email?: string | null;
  work_email?: string | null;
  mobile_phone?: string | null;
  emergency_contact_name?: string | null;
  emergency_contact_phone?: string | null;
  identity_type?: string | null;
  identity_number?: string | null;
  identity_issue_date?: string | null;
  identity_expiry_date?: string | null;
  branch_id?: number | null;
  department_id?: number | null;
  job_position_id?: number | null;
  job_grade_id?: number | null;
  manager_id?: number | null;
  status?: string;
  employment_type?: string;
  hire_date?: string | null;
  probation_end_date?: string | null;
  termination_date?: string | null;
  notes?: string | null;
}

export type EmployeePatch = Partial<Omit<EmployeeInput, "company_id">>;

export interface ListParams {
  company_id?: number;
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  department_id?: number;
  branch_id?: number;
  limit?: number;
}

function qs(params: ListParams): string {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      sp.set(key, String(value));
    }
  }
  const encoded = sp.toString();
  return encoded ? `?${encoded}` : "";
}

async function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

async function post<T>(path: string, payload: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function patch<T>(path: string, payload: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function del(path: string): Promise<void> {
  await request<void>(path, { method: "DELETE" });
}

export function listDepartments(
  params: ListParams = {},
): Promise<PageResponse<Department>> {
  return get(`/departments${qs(params)}`);
}

export function getDepartment(id: number): Promise<Department> {
  return get(`/departments/${id}`);
}

export function createDepartment(
  payload: DepartmentInput,
): Promise<Department> {
  return post("/departments", payload);
}

export function updateDepartment(
  id: number,
  payload: Partial<DepartmentInput>,
): Promise<Department> {
  return patch(`/departments/${id}`, payload);
}

export function deleteDepartment(id: number): Promise<void> {
  return del(`/departments/${id}`);
}

export function listJobPositions(
  params: ListParams = {},
): Promise<PageResponse<JobPosition>> {
  return get(`/job-positions${qs(params)}`);
}

export function createJobPosition(
  payload: JobPositionInput,
): Promise<JobPosition> {
  return post("/job-positions", payload);
}

export function updateJobPosition(
  id: number,
  payload: Partial<JobPositionInput>,
): Promise<JobPosition> {
  return patch(`/job-positions/${id}`, payload);
}

export function deleteJobPosition(id: number): Promise<void> {
  return del(`/job-positions/${id}`);
}

export function listJobGrades(
  params: ListParams = {},
): Promise<PageResponse<JobGrade>> {
  return get(`/job-grades${qs(params)}`);
}

export function createJobGrade(payload: JobGradeInput): Promise<JobGrade> {
  return post("/job-grades", payload);
}

export function updateJobGrade(
  id: number,
  payload: Partial<JobGradeInput>,
): Promise<JobGrade> {
  return patch(`/job-grades/${id}`, payload);
}

export function deleteJobGrade(id: number): Promise<void> {
  return del(`/job-grades/${id}`);
}

export function listBranches(companyId?: number): Promise<Branch[]> {
  return get(`/branches${qs({ company_id: companyId })}`);
}

export function listEmployees(
  params: ListParams = {},
): Promise<PageResponse<Employee>> {
  return get(`/employees${qs(params)}`);
}

export function getEmployee(id: number): Promise<Employee> {
  return get(`/employees/${id}`);
}

export function createEmployee(payload: EmployeeInput): Promise<Employee> {
  return post("/employees", payload);
}

export function updateEmployee(
  id: number,
  payload: EmployeePatch,
): Promise<Employee> {
  return patch(`/employees/${id}`, payload);
}

export function deleteEmployee(id: number): Promise<void> {
  return del(`/employees/${id}`);
}

export function getJobPosition(id: number): Promise<JobPosition> {
  return get(`/job-positions/${id}`);
}

export function getJobGrade(id: number): Promise<JobGrade> {
  return get(`/job-grades/${id}`);
}

export interface User {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  company_id: number | null;
  created_at: string;
}

export function listUsers(params: ListParams = {}): Promise<User[]> {
  return get(`/users${qs(params)}`);
}

export function getUser(id: number): Promise<User> {
  return get(`/users/${id}`);
}

export interface EmployeeDocumentType {
  id: number;
  company_id: number;
  code: string;
  name_ar: string;
  name_en: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface EmployeeDocumentTypeInput {
  company_id: number;
  code: string;
  name_ar: string;
  name_en: string;
}

export interface EmployeeDocument {
  id: number;
  company_id: number;
  employee_id: number;
  document_type_id: number;
  document_number: string | null;
  issue_date: string | null;
  expiry_date: string | null;
  file_name: string;
  mime_type: string;
  file_size: number;
  notes: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface EmployeeDocumentPatch {
  document_type_id?: number;
  document_number?: string | null;
  issue_date?: string | null;
  expiry_date?: string | null;
  notes?: string | null;
}

export function listDocumentTypes(
  companyId?: number,
): Promise<EmployeeDocumentType[]> {
  return get(`/employee-document-types${qs({ company_id: companyId })}`);
}

export function createDocumentType(
  payload: EmployeeDocumentTypeInput,
): Promise<EmployeeDocumentType> {
  return post("/employee-document-types", payload);
}

export function listEmployeeDocuments(
  employeeId: number,
  params: ListParams = {},
): Promise<PageResponse<EmployeeDocument>> {
  return get(`/employees/${employeeId}/documents${qs(params)}`);
}

// Phase 4 — Work Schedules
export interface WorkSchedule {
  id: number;
  company_id: number;
  code: string;
  name_ar: string;
  name_en: string;
  timezone: string;
  effective_from: string;
  effective_to: string | null;
  status: string;
  notes: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface WorkScheduleInput {
  company_id: number;
  code: string;
  name_ar: string;
  name_en: string;
  timezone?: string;
  effective_from: string;
  effective_to?: string | null;
  status?: string;
  notes?: string | null;
}

export interface WorkScheduleDay {
  id: number;
  company_id: number;
  schedule_id: number;
  weekday: number;
  is_working: boolean;
  start_time: string | null;
  end_time: string | null;
  shift_id: number | null;
  breaks: BreakPeriod[];
  created_at: string;
  updated_at: string;
}

export interface WorkScheduleDayInput {
  weekday: number;
  is_working: boolean;
  start_time?: string | null;
  end_time?: string | null;
  shift_id?: number | null;
  breaks?: BreakPeriodInput[];
}

export interface BreakPeriod {
  id: number;
  company_id: number;
  schedule_day_id: number | null;
  shift_id: number | null;
  start_time: string;
  end_time: string;
  is_paid: boolean;
  created_at: string;
  updated_at: string;
}

export interface BreakPeriodInput {
  start_time: string;
  end_time: string;
  is_paid: boolean;
}

export interface WorkScheduleDaysPut {
  days: WorkScheduleDayInput[];
}

export interface ResolvedSchedule {
  date: string;
  weekday: number;
  is_working: boolean;
  timezone: string;
  crosses_midnight: boolean;
  assignment_id: number | null;
  schedule_id: number | null;
  schedule_code: string | null;
  schedule_name_en: string | null;
  schedule_name_ar: string | null;
  shift_id: number | null;
  shift_code: string | null;
  shift_name_en: string | null;
  start_time: string | null;
  end_time: string | null;
  breaks: BreakPeriod[];
}

export interface WorkSchedulePageParams extends ListParams {
  status?: string;
  search?: string;
}

export function listWorkSchedules(
  params: WorkSchedulePageParams = {},
): Promise<PageResponse<WorkSchedule>> {
  return get(`/work-schedules${qs(params)}`);
}

export function getWorkSchedule(id: number): Promise<WorkSchedule> {
  return get(`/work-schedules/${id}`);
}

export function createWorkSchedule(
  payload: WorkScheduleInput,
): Promise<WorkSchedule> {
  return post("/work-schedules", payload);
}

export function updateWorkSchedule(
  id: number,
  payload: Partial<WorkScheduleInput>,
): Promise<WorkSchedule> {
  return patch(`/work-schedules/${id}`, payload);
}

export function deleteWorkSchedule(id: number): Promise<void> {
  return del(`/work-schedules/${id}`);
}

export function getWorkScheduleDays(scheduleId: number): Promise<{
  items: WorkScheduleDay[];
}> {
  return get(`/work-schedules/${scheduleId}/days`);
}

export function putWorkScheduleDays(
  scheduleId: number,
  payload: WorkScheduleDaysPut,
): Promise<{ items: WorkScheduleDay[] }> {
  return request<{ items: WorkScheduleDay[] }>(
    `/work-schedules/${scheduleId}/days`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function resolveEmployeeSchedule(
  employeeId: number,
  date?: string,
): Promise<ResolvedSchedule> {
  const params = date ? `?date=${date}` : "";
  return get(`/employees/${employeeId}/schedule${params}`);
}

// Phase 4 — Shifts
export interface Shift {
  id: number;
  company_id: number;
  code: string;
  name_ar: string;
  name_en: string;
  start_time: string;
  end_time: string;
  crosses_midnight: boolean;
  status: string;
  notes: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  breaks: BreakPeriod[];
}

export interface ShiftInput {
  company_id: number;
  code: string;
  name_ar: string;
  name_en: string;
  start_time: string;
  end_time: string;
  status?: string;
  notes?: string | null;
  breaks?: BreakPeriodInput[];
}

export interface ShiftPageParams extends ListParams {
  status?: string;
  search?: string;
}

export function listShifts(params: ShiftPageParams = {}): Promise<PageResponse<Shift>> {
  return get(`/shifts${qs(params)}`);
}

export function getShift(id: number): Promise<Shift> {
  return get(`/shifts/${id}`);
}

export function createShift(payload: ShiftInput): Promise<Shift> {
  return post("/shifts", payload);
}

export function updateShift(
  id: number,
  payload: Partial<ShiftInput>,
): Promise<Shift> {
  return patch(`/shifts/${id}`, payload);
}

export function deleteShift(id: number): Promise<void> {
  return del(`/shifts/${id}`);
}

// Phase 4 — Employee Work Assignments
export interface EmployeeWorkAssignment {
  id: number;
  company_id: number;
  employee_id: number;
  schedule_id: number;
  shift_id: number | null;
  effective_from: string;
  effective_to: string | null;
  notes: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface EmployeeWorkAssignmentInput {
  schedule_id: number;
  shift_id?: number | null;
  effective_from: string;
  effective_to?: string | null;
  notes?: string | null;
}

export interface EmployeeWorkAssignmentUpdate {
  schedule_id?: number | null;
  shift_id?: number | null;
  effective_from?: string | null;
  effective_to?: string | null;
  notes?: string | null;
}

export interface AssignmentPageParams extends ListParams {
  page?: number;
  page_size?: number;
}

export function listEmployeeWorkAssignments(
  employeeId: number,
  params: AssignmentPageParams = {},
): Promise<PageResponse<EmployeeWorkAssignment>> {
  return get(
    `/employees/${employeeId}/work-assignments${qs(params)}`,
  );
}

export function getEmployeeWorkAssignment(
  employeeId: number,
  assignmentId: number,
): Promise<EmployeeWorkAssignment> {
  return get(`/employees/${employeeId}/work-assignments/${assignmentId}`);
}

export function createEmployeeWorkAssignment(
  employeeId: number,
  payload: EmployeeWorkAssignmentInput,
): Promise<EmployeeWorkAssignment> {
  return post(`/employees/${employeeId}/work-assignments`, payload);
}

export function updateEmployeeWorkAssignment(
  employeeId: number,
  assignmentId: number,
  payload: EmployeeWorkAssignmentUpdate,
): Promise<EmployeeWorkAssignment> {
  return patch(
    `/employees/${employeeId}/work-assignments/${assignmentId}`,
    payload,
  );
}

export function deleteEmployeeWorkAssignment(
  employeeId: number,
  assignmentId: number,
): Promise<void> {
  return del(`/employees/${employeeId}/work-assignments/${assignmentId}`);
}

// Phase 4 — Attendance
export interface AttendanceRecord {
  id: number;
  company_id: number;
  employee_id: number;
  work_date: string;
  schedule_id: number | null;
  shift_id: number | null;
  check_in: string;
  check_out: string | null;
  status: string;
  source: string;
  scheduled_minutes: number | null;
  worked_minutes: number | null;
  break_minutes: number | null;
  late_minutes: number | null;
  early_leave_minutes: number | null;
  overtime_candidate_minutes: number | null;
  notes: string | null;
  correction_reason: string | null;
  corrected_by: number | null;
  corrected_at: string | null;
  closed_by: number | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface AttendanceCreate {
  employee_id: number;
  check_in: string;
  check_out?: string | null;
  status?: string | null;
  source?: string;
  notes?: string | null;
}

export interface AttendanceCheckIn {
  employee_id: number;
  at?: string | null;
  source?: string;
  notes?: string | null;
}

export interface AttendanceCheckOut {
  employee_id: number;
  at?: string | null;
}

export interface AttendanceUpdate {
  check_in?: string | null;
  check_out?: string | null;
  status?: string | null;
  source?: string | null;
  notes?: string | null;
  reason?: string | null;
}

export interface AttendancePageParams extends ListParams {
  employee_id?: number;
  date_from?: string;
  date_to?: string;
  status?: string;
  department_id?: number;
  branch_id?: number;
  schedule_id?: number;
  shift_id?: number;
  page?: number;
  page_size?: number;
}

export function listAttendance(
  params: AttendancePageParams = {},
): Promise<PageResponse<AttendanceRecord>> {
  return get(`/attendance${qs(params)}`);
}

export function createAttendance(
  payload: AttendanceCreate,
): Promise<AttendanceRecord> {
  return post("/attendance", payload);
}

export function checkInAttendance(
  payload: AttendanceCheckIn,
): Promise<AttendanceRecord> {
  return post("/attendance/check-in", payload);
}

export function checkOutAttendance(
  payload: AttendanceCheckOut,
): Promise<AttendanceRecord> {
  return post("/attendance/check-out", payload);
}

export function getAttendance(id: number): Promise<AttendanceRecord> {
  return get(`/attendance/${id}`);
}

export function updateAttendance(
  id: number,
  payload: AttendanceUpdate,
): Promise<AttendanceRecord> {
  return patch(`/attendance/${id}`, payload);
}

export function deleteAttendance(
  id: number,
  reason?: string | null,
): Promise<void> {
  const query = reason
    ? `?${new URLSearchParams({ reason: reason })}`
    : "";
  return request<void>(`/attendance/${id}${query}`, {
    method: "DELETE",
  });
}

// Phase 4 — Overtime
export interface OvertimeRecord {
  id: number;
  company_id: number;
  employee_id: number;
  attendance_id: number | null;
  work_date: string;
  requested_minutes: number;
  approved_minutes: number | null;
  status: string;
  reason: string | null;
  decision_reason: string | null;
  decided_by: number | null;
  decided_at: string | null;
  submitted_by: number | null;
  submitted_at: string | null;
  correction_reason: string | null;
  corrected_by: number | null;
  corrected_at: string | null;
  notes: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface OvertimeCreate {
  employee_id: number;
  work_date: string;
  requested_minutes: number;
  attendance_id?: number | null;
  reason?: string | null;
  notes?: string | null;
}

export interface OvertimeUpdate {
  work_date?: string | null;
  requested_minutes?: number | null;
  attendance_id?: number | null;
  reason?: string | null;
  notes?: string | null;
}

export interface OvertimeApprove {
  approved_minutes?: number | null;
  reason?: string | null;
}

export interface OvertimeDecision {
  reason?: string | null;
}

export interface OvertimeCorrect {
  approved_minutes: number;
  reason?: string | null;
}

export interface OvertimePageParams extends ListParams {
  employee_id?: number;
  status?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}

export function listOvertime(
  params: OvertimePageParams = {},
): Promise<PageResponse<OvertimeRecord>> {
  return get(`/overtime${qs(params)}`);
}

export function createOvertime(payload: OvertimeCreate): Promise<OvertimeRecord> {
  return post("/overtime", payload);
}

export function getOvertime(id: number): Promise<OvertimeRecord> {
  return get(`/overtime/${id}`);
}

export function updateOvertime(
  id: number,
  payload: OvertimeUpdate,
): Promise<OvertimeRecord> {
  return patch(`/overtime/${id}`, payload);
}

export function submitOvertime(id: number): Promise<OvertimeRecord> {
  return post(`/overtime/${id}/submit`, {});
}

export function approveOvertime(
  id: number,
  payload: OvertimeApprove,
): Promise<OvertimeRecord> {
  return post(`/overtime/${id}/approve`, payload);
}

export function rejectOvertime(
  id: number,
  payload: OvertimeDecision,
): Promise<OvertimeRecord> {
  return post(`/overtime/${id}/reject`, payload);
}

export function cancelOvertime(
  id: number,
  payload: OvertimeDecision,
): Promise<OvertimeRecord> {
  return post(`/overtime/${id}/cancel`, payload);
}

export function correctOvertime(
  id: number,
  payload: OvertimeCorrect,
): Promise<OvertimeRecord> {
  return post(`/overtime/${id}/correct`, payload);
}

export function uploadEmployeeDocument(
  employeeId: number,
  formData: FormData,
): Promise<EmployeeDocument> {
  return request<EmployeeDocument>(
    `/employees/${employeeId}/documents`,
    { method: "POST", body: formData },
  );
}

export function updateEmployeeDocument(
  employeeId: number,
  documentId: number,
  payload: EmployeeDocumentPatch,
): Promise<EmployeeDocument> {
  return patch(`/employees/${employeeId}/documents/${documentId}`, payload);
}

export function deleteEmployeeDocument(
  employeeId: number,
  documentId: number,
): Promise<void> {
  return del(`/employees/${employeeId}/documents/${documentId}`);
}

export async function downloadEmployeeDocument(
  employeeId: number,
  documentId: number,
): Promise<{ blob: Blob; filename: string }> {
  const path = `/employees/${employeeId}/documents/${documentId}/download`;
  const fetchOnce = () =>
    fetch(`${API_BASE}${path}`, {
      headers: buildHeaders(),
      credentials: "include",
    });
  let response = await fetchOnce();
  if (response.status === 401 && (await tryRefresh())) {
    response = await fetchOnce();
  }
  if (!response.ok) {
    let detail = response.statusText;
    let code: string | null = null;
    try {
      const body = await response.json();
      detail = extractDetail(body, detail);
      code = readErrorCode(body);
    } catch {
      // non-JSON error body
    }
    throw new ApiError(response.status, detail, code);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  let filename = "download";
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) {
    filename = decodeURIComponent(star[1]);
  } else {
    const plain = disposition.match(/filename="?([^";]+)"?/i);
    if (plain) {
      filename = plain[1];
    }
  }
  return { blob: await response.blob(), filename };
}

export interface EmployeeContract {
  id: number;
  company_id: number;
  employee_id: number;
  contract_type: string;
  status: string;
  contract_number: string | null;
  start_date: string;
  end_date: string | null;
  signed_date: string | null;
  termination_date: string | null;
  termination_reason: string | null;
  basic_salary: number | null;
  currency: string;
  notes: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface EmployeeContractInput {
  company_id: number;
  contract_type: string;
  status?: string;
  contract_number?: string | null;
  start_date: string;
  end_date?: string | null;
  signed_date?: string | null;
  termination_date?: string | null;
  termination_reason?: string | null;
  basic_salary?: number | null;
  currency?: string;
  notes?: string | null;
}

export interface EmploymentHistory {
  id: number;
  company_id: number;
  employee_id: number;
  effective_from: string;
  effective_to: string | null;
  employment_status: string;
  employment_type: string;
  branch_id: number | null;
  department_id: number | null;
  position_id: number | null;
  grade_id: number | null;
  manager_id: number | null;
  change_reason: string | null;
  notes: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface EmploymentHistoryInput {
  company_id: number;
  effective_from: string;
  effective_to?: string | null;
  employment_status: string;
  employment_type: string;
  branch_id?: number | null;
  department_id?: number | null;
  position_id?: number | null;
  grade_id?: number | null;
  manager_id?: number | null;
  change_reason?: string | null;
  notes?: string | null;
  apply_to_employee?: boolean;
}

export function listEmployeeContracts(
  employeeId: number,
  params: ListParams = {},
): Promise<PageResponse<EmployeeContract>> {
  return get(`/employees/${employeeId}/contracts${qs(params)}`);
}

export function createEmployeeContract(
  employeeId: number,
  payload: EmployeeContractInput,
): Promise<EmployeeContract> {
  return post(`/employees/${employeeId}/contracts`, payload);
}

export function updateEmployeeContract(
  employeeId: number,
  contractId: number,
  payload: Partial<EmployeeContractInput>,
): Promise<EmployeeContract> {
  return patch(`/employees/${employeeId}/contracts/${contractId}`, payload);
}

export function deleteEmployeeContract(
  employeeId: number,
  contractId: number,
): Promise<void> {
  return del(`/employees/${employeeId}/contracts/${contractId}`);
}

export function listEmploymentHistory(
  employeeId: number,
  params: ListParams = {},
): Promise<PageResponse<EmploymentHistory>> {
  return get(`/employees/${employeeId}/employment-history${qs(params)}`);
}

export function createEmploymentHistory(
  employeeId: number,
  payload: EmploymentHistoryInput,
): Promise<EmploymentHistory> {
  return post(`/employees/${employeeId}/employment-history`, payload);
}

export interface LinkedUser {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  company_id: number | null;
}

export interface EmployeeUserLink {
  linked: boolean;
  user: LinkedUser | null;
}

export function getEmployeeUserLink(
  employeeId: number,
): Promise<EmployeeUserLink> {
  return get(`/employees/${employeeId}/user`);
}

export function linkEmployeeUser(
  employeeId: number,
  userId: number,
): Promise<EmployeeUserLink> {
  return post(`/employees/${employeeId}/user`, { user_id: userId });
}

export function unlinkEmployeeUser(employeeId: number): Promise<void> {
  return del(`/employees/${employeeId}/user`);
}

// Phase 5 — Leave Management
export interface LeaveType {
  id: number;
  company_id: number;
  code: string;
  name_ar: string;
  name_en: string;
  description: string | null;
  is_paid: boolean;
  requires_approval: boolean;
  allocation_requires_approval: boolean;
  day_counting_mode: string;
  requires_attachment: boolean;
  attachment_threshold_days: number | null;
  requires_reason: boolean;
  negative_balance_allowed: boolean;
  min_request_days: number | null;
  max_request_days: number | null;
  default_entitlement_days: number | null;
  carry_forward_enabled: boolean;
  carry_forward_max_days: number | null;
  carry_forward_expiry: string;
  allowance_treatment: string;
  is_statutory: boolean;
  statutory_key: string | null;
  status: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface LeaveTypeInput {
  company_id: number;
  code: string;
  name_ar: string;
  name_en: string;
  description?: string | null;
  is_paid?: boolean;
  requires_approval?: boolean;
  allocation_requires_approval?: boolean;
  day_counting_mode?: string;
  requires_attachment?: boolean;
  attachment_threshold_days?: number | null;
  requires_reason?: boolean;
  negative_balance_allowed?: boolean;
  min_request_days?: number | null;
  max_request_days?: number | null;
  default_entitlement_days?: number | null;
  carry_forward_enabled?: boolean;
  carry_forward_max_days?: number | null;
  carry_forward_expiry?: string;
  allowance_treatment?: string;
  is_statutory?: boolean;
  statutory_key?: string | null;
  status?: string;
  sort_order?: number;
}

export interface LeaveTypePageParams extends ListParams {
  statutory_key?: string;
  q?: string;
}

export function listLeaveTypes(
  params: LeaveTypePageParams = {},
): Promise<PageResponse<LeaveType>> {
  return get(`/leave-types${qs(params)}`);
}

export function createLeaveType(
  payload: LeaveTypeInput,
): Promise<LeaveType> {
  return post("/leave-types", payload);
}

export function getLeaveType(id: number): Promise<LeaveType> {
  return get(`/leave-types/${id}`);
}

export function updateLeaveType(
  id: number,
  payload: Partial<LeaveTypeInput>,
): Promise<LeaveType> {
  return patch(`/leave-types/${id}`, payload);
}

export function deleteLeaveType(id: number): Promise<void> {
  return del(`/leave-types/${id}`);
}

export interface StatutoryRule {
  id: number;
  company_id: number;
  statutory_key: string;
  jurisdiction: string;
  version: number;
  effective_from: string;
  effective_to: string | null;
  rule_json: Record<string, unknown>;
  source_reference: string;
  source_date: string | null;
  requires_legal_verification: boolean;
  notes: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface StatutoryRuleInput {
  company_id: number;
  statutory_key: string;
  effective_from: string;
  effective_to?: string | null;
  rule_json?: Record<string, unknown>;
  source_reference: string;
  source_date?: string | null;
  requires_legal_verification?: boolean;
  notes?: string | null;
}

export interface StatutoryRulePageParams extends ListParams {
  statutory_key?: string;
  as_of?: string;
}

export function listStatutoryRules(
  params: StatutoryRulePageParams = {},
): Promise<PageResponse<StatutoryRule>> {
  return get(`/leave-statutory-rules${qs(params)}`);
}

export function createStatutoryRule(
  payload: StatutoryRuleInput,
): Promise<StatutoryRule> {
  return post("/leave-statutory-rules", payload);
}

export function deactivateStatutoryRule(
  id: number,
  payload: { reason?: string | null } = {},
): Promise<StatutoryRule> {
  return post(`/leave-statutory-rules/${id}/deactivate`, payload);
}

export interface LeaveAllocation {
  id: number;
  company_id: number;
  employee_id: number;
  leave_type_id: number;
  period_start: string;
  period_end: string;
  allocated_days: number;
  used_days: number;
  source: string;
  carried_from_id: number | null;
  status: string;
  reason: string | null;
  decision_reason: string | null;
  approved_by: number | null;
  approved_at: string | null;
  rejected_by: number | null;
  rejected_at: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface LeaveAllocationInput {
  employee_id: number;
  leave_type_id: number;
  period_start: string;
  period_end: string;
  allocated_days: number;
  source?: string;
  reason?: string | null;
}

export interface LeaveAllocationGenerateInput {
  leave_type_id: number;
  period_start: string;
  period_end: string;
  allocated_days?: number | null;
  employee_ids?: number[] | null;
}

export interface CarryForwardInput {
  company_id: number;
  period_start: string;
  period_end: string;
}

export interface LeaveAllocationPageParams extends ListParams {
  employee_id?: number;
  leave_type_id?: number;
  period_from?: string;
  period_to?: string;
}

export function listLeaveAllocations(
  params: LeaveAllocationPageParams = {},
): Promise<PageResponse<LeaveAllocation>> {
  return get(`/leave-allocations${qs(params)}`);
}

export function createLeaveAllocation(
  payload: LeaveAllocationInput,
): Promise<LeaveAllocation> {
  return post("/leave-allocations", payload);
}

export function generateLeaveAllocations(
  payload: LeaveAllocationGenerateInput,
): Promise<LeaveAllocation[]> {
  return post("/leave-allocations/generate", payload);
}

export function carryForwardAllocations(
  payload: CarryForwardInput,
): Promise<LeaveAllocation[]> {
  return post("/leave-allocations/carry-forward", payload);
}

export function updateLeaveAllocation(
  id: number,
  payload: Partial<LeaveAllocationInput>,
): Promise<LeaveAllocation> {
  return patch(`/leave-allocations/${id}`, payload);
}

export function deleteLeaveAllocation(id: number): Promise<void> {
  return del(`/leave-allocations/${id}`);
}

export function approveLeaveAllocation(
  id: number,
  payload: { reason?: string | null } = {},
): Promise<LeaveAllocation> {
  return post(`/leave-allocations/${id}/approve`, payload);
}

export function rejectLeaveAllocation(
  id: number,
  payload: { reason?: string | null } = {},
): Promise<LeaveAllocation> {
  return post(`/leave-allocations/${id}/reject`, payload);
}

export interface LeaveRequest {
  id: number;
  company_id: number;
  employee_id: number;
  leave_type_id: number;
  start_date: string;
  end_date: string;
  start_time: string | null;
  end_time: string | null;
  days: number;
  reason: string | null;
  attachment_name: string | null;
  attachment_mime: string | null;
  attachment_size: number | null;
  status: string;
  count_details: Record<string, unknown> | null;
  submitted_by: number | null;
  submitted_at: string | null;
  decided_by: number | null;
  decided_at: string | null;
  decision_reason: string | null;
  cancelled_by: number | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface LeaveRequestInput {
  employee_id: number;
  leave_type_id: number;
  start_date: string;
  end_date: string;
  start_time?: string | null;
  end_time?: string | null;
  reason?: string | null;
}

export interface LeaveRequestPageParams extends ListParams {
  employee_id?: number;
  leave_type_id?: number;
  date_from?: string;
  date_to?: string;
  q?: string;
}

export interface LeaveBalance {
  leave_type_id: number;
  code: string;
  name_ar: string;
  name_en: string;
  is_paid: boolean;
  allocated_days: number;
  used_days: number;
  pending_days: number;
  remaining_days: number;
  negative_balance_allowed: boolean;
}

export interface LeaveBalancesResponse {
  items: LeaveBalance[];
}

export interface LeaveBalanceParams {
  employee_id?: number;
  leave_type_id?: number;
  as_of?: string;
  period_start?: string;
  period_end?: string;
}

export interface LeaveRequestPreview {
  days: number;
  day_counting_mode: string;
  count_details: Record<string, unknown>;
  balance: LeaveBalance | null;
  would_be_negative: boolean;
  has_open_attendance_conflict: boolean;
  has_approved_overtime_conflict: boolean;
}

export function listLeaveRequests(
  params: LeaveRequestPageParams = {},
): Promise<PageResponse<LeaveRequest>> {
  return get(`/leave-requests${qs(params)}`);
}

export function createLeaveRequest(
  payload: LeaveRequestInput,
): Promise<LeaveRequest> {
  return post("/leave-requests", payload);
}

export function previewLeaveRequest(payload: {
  employee_id: number;
  leave_type_id: number;
  start_date: string;
  end_date: string;
  start_time?: string | null;
  end_time?: string | null;
  exclude_request_id?: number | null;
}): Promise<LeaveRequestPreview> {
  return post("/leave-requests/preview", payload);
}

export function updateLeaveRequest(
  id: number,
  payload: Partial<LeaveRequestInput>,
): Promise<LeaveRequest> {
  return patch(`/leave-requests/${id}`, payload);
}

export function deleteLeaveRequest(id: number): Promise<void> {
  return del(`/leave-requests/${id}`);
}

export function submitLeaveRequest(id: number): Promise<LeaveRequest> {
  return post(`/leave-requests/${id}/submit`, {});
}

export function approveLeaveRequest(
  id: number,
  payload: { reason?: string | null } = {},
): Promise<LeaveRequest> {
  return post(`/leave-requests/${id}/approve`, payload);
}

export function rejectLeaveRequest(
  id: number,
  payload: { reason?: string | null },
): Promise<LeaveRequest> {
  return post(`/leave-requests/${id}/reject`, payload);
}

export function cancelLeaveRequest(
  id: number,
  payload: { reason?: string | null } = {},
): Promise<LeaveRequest> {
  return post(`/leave-requests/${id}/cancel`, payload);
}

export function uploadLeaveRequestAttachment(
  requestId: number,
  formData: FormData,
): Promise<LeaveRequest> {
  return request<LeaveRequest>(`/leave-requests/${requestId}/attachment`, {
    method: "POST",
    body: formData,
  });
}

export function deleteLeaveRequestAttachment(requestId: number): Promise<void> {
  return del(`/leave-requests/${requestId}/attachment`);
}

export async function downloadLeaveRequestAttachment(
  requestId: number,
): Promise<{ blob: Blob; filename: string }> {
  const path = `/leave-requests/${requestId}/attachment`;
  const fetchOnce = () =>
    fetch(`${API_BASE}${path}`, {
      headers: buildHeaders(),
      credentials: "include",
    });
  let response = await fetchOnce();
  if (response.status === 401 && (await tryRefresh())) {
    response = await fetchOnce();
  }
  if (!response.ok) {
    let detail = response.statusText;
    let code: string | null = null;
    try {
      const body = await response.json();
      detail = extractDetail(body, detail);
      code = readErrorCode(body);
    } catch {
      // non-JSON error body
    }
    throw new ApiError(response.status, detail, code);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  let filename = "download";
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) {
    filename = decodeURIComponent(star[1]);
  } else {
    const plain = disposition.match(/filename="?([^";]+)"?/i);
    if (plain) {
      filename = plain[1];
    }
  }
  return { blob: await response.blob(), filename };
}

export function listLeaveBalances(
  params: LeaveBalanceParams = {},
): Promise<LeaveBalancesResponse> {
  return get(`/leave-balances${qs(params as ListParams)}`);
}

export function myLeaveBalances(
  asOf?: string,
): Promise<LeaveBalancesResponse> {
  return get(`/leave-balances/me${qs({ as_of: asOf } as ListParams)}`);
}

export interface CompanyHoliday {
  id: number;
  company_id: number;
  date: string;
  name_ar: string;
  name_en: string;
  status: string;
  notes: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface CompanyHolidayInput {
  company_id: number;
  date: string;
  name_ar: string;
  name_en: string;
  status?: string;
  notes?: string | null;
}

export interface HolidayPageParams extends ListParams {
  year?: number;
}

export function listCompanyHolidays(
  params: HolidayPageParams = {},
): Promise<PageResponse<CompanyHoliday>> {
  return get(`/company-holidays${qs(params)}`);
}

export function createCompanyHoliday(
  payload: CompanyHolidayInput,
): Promise<CompanyHoliday> {
  return post("/company-holidays", payload);
}

export function updateCompanyHoliday(
  id: number,
  payload: Partial<CompanyHolidayInput>,
): Promise<CompanyHoliday> {
  return patch(`/company-holidays/${id}`, payload);
}

export function deleteCompanyHoliday(id: number): Promise<void> {
  return del(`/company-holidays/${id}`);
}

// Phase 6 — Payroll & Salary Management
export interface SalaryComponent {
  id: number;
  company_id: number;
  code: string;
  name_ar: string;
  name_en: string;
  description: string | null;
  category: string;
  calculation_basis: string;
  default_amount: number | null;
  default_rate: number | null;
  is_statutory: boolean;
  statutory_key: string | null;
  status: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface SalaryComponentInput {
  company_id: number;
  code: string;
  name_ar: string;
  name_en: string;
  description?: string | null;
  category: string;
  calculation_basis: string;
  default_amount?: number | null;
  default_rate?: number | null;
  is_statutory?: boolean;
  statutory_key?: string | null;
  status?: string;
  sort_order?: number;
}

export interface SalaryComponentPageParams extends ListParams {
  category?: string;
  status?: string;
}

export function listSalaryComponents(
  params: SalaryComponentPageParams = {},
): Promise<PageResponse<SalaryComponent>> {
  return get(`/salary-components${qs(params)}`);
}

export function createSalaryComponent(
  payload: SalaryComponentInput,
): Promise<SalaryComponent> {
  return post("/salary-components", payload);
}

export function updateSalaryComponent(
  id: number,
  payload: Partial<SalaryComponentInput>,
): Promise<SalaryComponent> {
  return patch(`/salary-components/${id}`, payload);
}

export function deactivateSalaryComponent(id: number): Promise<SalaryComponent> {
  return post(`/salary-components/${id}/deactivate`, {});
}

export interface SalaryAssignment {
  id: number;
  company_id: number;
  employee_id: number;
  effective_from: string;
  effective_to: string | null;
  basic_salary: number;
  currency: string;
  reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface SalaryAssignmentInput {
  company_id: number;
  employee_id: number;
  effective_from: string;
  effective_to?: string | null;
  basic_salary: number;
  currency?: string;
  reason?: string | null;
}

export interface SalaryAssignmentUpdate {
  basic_salary?: number;
  currency?: string;
  reason?: string | null;
  effective_to?: string | null;
}

export interface SeedAssignmentsResult {
  created: number;
  skipped: number;
}

export interface SalaryAssignmentPageParams extends ListParams {
  employee_id?: number;
  as_of?: string;
}

export function listSalaryAssignments(
  params: SalaryAssignmentPageParams = {},
): Promise<PageResponse<SalaryAssignment>> {
  return get(`/salary-assignments${qs(params)}`);
}

export function createSalaryAssignment(
  payload: SalaryAssignmentInput,
): Promise<SalaryAssignment> {
  return post("/salary-assignments", payload);
}

export function updateSalaryAssignment(
  id: number,
  payload: SalaryAssignmentUpdate,
): Promise<SalaryAssignment> {
  return patch(`/salary-assignments/${id}`, payload);
}

export function seedSalaryAssignments(
  companyId: number,
): Promise<SeedAssignmentsResult> {
  return post(`/salary-assignments/seed${qs({ company_id: companyId })}`, {});
}

export interface PayrollPeriod {
  id: number;
  company_id: number;
  name: string;
  period_start: string;
  period_end: string;
  currency: string;
  status: string;
  calculated_at: string | null;
  calculated_by: number | null;
  reviewed_at: string | null;
  reviewed_by: number | null;
  approved_at: string | null;
  approved_by: number | null;
  paid_at: string | null;
  paid_by: number | null;
  locked_at: string | null;
  locked_by: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface PayrollPeriodInput {
  company_id: number;
  name: string;
  period_start: string;
  period_end: string;
  currency?: string;
  notes?: string | null;
}

export interface PayrollPeriodPageParams extends ListParams {
  status?: string;
}

export function listPayrollPeriods(
  params: PayrollPeriodPageParams = {},
): Promise<PageResponse<PayrollPeriod>> {
  return get(`/payroll-periods${qs(params)}`);
}

export function createPayrollPeriod(
  payload: PayrollPeriodInput,
): Promise<PayrollPeriod> {
  return post("/payroll-periods", payload);
}

export function updatePayrollPeriod(
  id: number,
  payload: { name?: string; notes?: string | null },
): Promise<PayrollPeriod> {
  return patch(`/payroll-periods/${id}`, payload);
}

export function calculatePayrollPeriod(id: number): Promise<PayrollRun> {
  return post(`/payroll-periods/${id}/calculate`, {});
}

export function reviewPayrollPeriod(id: number): Promise<PayrollPeriod> {
  return post(`/payroll-periods/${id}/review`, {});
}

export function approvePayrollPeriod(id: number): Promise<PayrollPeriod> {
  return post(`/payroll-periods/${id}/approve`, {});
}

export function markPayrollPeriodPaid(id: number): Promise<PayrollPeriod> {
  return post(`/payroll-periods/${id}/mark-paid`, {});
}

export function lockPayrollPeriod(id: number): Promise<PayrollPeriod> {
  return post(`/payroll-periods/${id}/lock`, {});
}

export interface PayrollRun {
  id: number;
  company_id: number;
  period_id: number;
  run_number: number;
  status: string;
  inputs_hash: string | null;
  engine_version: string | null;
  employee_count: number;
  gross_total: number;
  deductions_total: number;
  employer_total: number;
  net_total: number;
  warnings: Array<Record<string, unknown>> | null;
  calculated_at: string | null;
  calculated_by: number | null;
  created_at: string;
  updated_at: string;
  period_status: string | null;
  period_start: string | null;
  period_end: string | null;
}

export interface PayslipLine {
  id: number;
  component_id: number | null;
  line_type: string;
  label_ar: string;
  label_en: string;
  unit: string;
  quantity: number | null;
  rate: number | null;
  amount: number;
  sort_order: number;
}

export interface PayrollRunLine {
  id: number;
  run_id: number;
  employee_id: number;
  basic_snapshot: number;
  currency: string;
  earnings_total: number;
  deductions_total: number;
  employer_total: number;
  net_pay: number;
  worked_minutes: number;
  overtime_minutes: number;
  paid_leave_days: number;
  unpaid_leave_days: number;
  absent_days: number;
  late_minutes: number;
  warnings: Array<Record<string, unknown>> | null;
  lines: PayslipLine[];
}

export interface Payslip extends PayrollRunLine {
  run_status: string | null;
  period_status: string | null;
  period_start: string | null;
  period_end: string | null;
  run_number: number | null;
  inputs_hash: string | null;
}

export interface PayrollRunPageParams extends ListParams {
  period_id?: number;
}

export function listPayrollRuns(
  params: PayrollRunPageParams = {},
): Promise<PageResponse<PayrollRun>> {
  return get(`/payroll-runs${qs(params)}`);
}

export function getPayrollRun(id: number): Promise<PayrollRun> {
  return get(`/payroll-runs/${id}`);
}

export function listPayrollRunLines(
  runId: number,
  params: ListParams = {},
): Promise<PageResponse<PayrollRunLine>> {
  return get(`/payroll-runs/${runId}/lines${qs(params)}`);
}

export function recalculatePayrollRun(id: number): Promise<PayrollRun> {
  return post(`/payroll-runs/${id}/recalculate`, {});
}

export interface AccountingExportLine {
  employee_id: number;
  employee_number: string | null;
  component_code: string | null;
  line_type: string;
  label_en: string;
  amount: number;
}

export interface AccountingExport {
  schema_name: string;
  engine_version: string | null;
  inputs_hash: string | null;
  company_id: number;
  period_id: number;
  period_start: string;
  period_end: string;
  currency: string;
  status: string;
  gross_total: number;
  deductions_total: number;
  employer_total: number;
  net_total: number;
  employee_count: number;
  lines: AccountingExportLine[];
}

export function exportPayrollRun(runId: number): Promise<AccountingExport> {
  return get(`/payroll-runs/${runId}/export`);
}

export function getPayslip(runLineId: number): Promise<Payslip> {
  return get(`/payslips/${runLineId}`);
}

export interface PayrollAdjustment {
  id: number;
  company_id: number;
  employee_id: number;
  period_id: number;
  original_run_id: number | null;
  component_id: number | null;
  amount: number;
  direction: string;
  reason: string;
  status: string;
  requested_by: number | null;
  decided_by: number | null;
  decided_at: string | null;
  decision_reason: string | null;
  voided_by: number | null;
  voided_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PayrollAdjustmentInput {
  company_id: number;
  employee_id: number;
  period_id: number;
  original_run_id?: number | null;
  component_id?: number | null;
  amount: number;
  direction: string;
  reason: string;
}

export interface PayrollAdjustmentPageParams extends ListParams {
  status?: string;
  period_id?: number;
  employee_id?: number;
}

export function listPayrollAdjustments(
  params: PayrollAdjustmentPageParams = {},
): Promise<PageResponse<PayrollAdjustment>> {
  return get(`/payroll-adjustments${qs(params)}`);
}

export function createPayrollAdjustment(
  payload: PayrollAdjustmentInput,
): Promise<PayrollAdjustment> {
  return post("/payroll-adjustments", payload);
}

export function decidePayrollAdjustment(
  id: number,
  decision: "approve" | "reject" | "void",
  payload: { decision_reason?: string | null } = {},
): Promise<PayrollAdjustment> {
  return post(`/payroll-adjustments/${id}/${decision}`, payload);
}

export interface PayrollDeduction {
  id: number;
  company_id: number;
  employee_id: number;
  component_id: number | null;
  name: string;
  amount: number;
  total_amount: number | null;
  remaining_amount: number | null;
  effective_from: string;
  effective_to: string | null;
  status: string;
  reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface PayrollDeductionInput {
  company_id: number;
  employee_id: number;
  component_id?: number | null;
  name: string;
  amount: number;
  total_amount?: number | null;
  effective_from: string;
  effective_to?: string | null;
  reason?: string | null;
}

export interface PayrollDeductionUpdate {
  amount?: number;
  effective_to?: string | null;
  status?: string;
  reason?: string | null;
}

export interface PayrollDeductionPageParams extends ListParams {
  status?: string;
  employee_id?: number;
}

export function listPayrollDeductions(
  params: PayrollDeductionPageParams = {},
): Promise<PageResponse<PayrollDeduction>> {
  return get(`/payroll-deductions${qs(params)}`);
}

export function createPayrollDeduction(
  payload: PayrollDeductionInput,
): Promise<PayrollDeduction> {
  return post("/payroll-deductions", payload);
}

export function updatePayrollDeduction(
  id: number,
  payload: PayrollDeductionUpdate,
): Promise<PayrollDeduction> {
  return patch(`/payroll-deductions/${id}`, payload);
}

export interface PayrollStatutoryRule {
  id: number;
  company_id: number;
  statutory_key: string;
  jurisdiction: string;
  version: number;
  effective_from: string;
  effective_to: string | null;
  rule_json: Record<string, unknown>;
  source_reference: string;
  source_date: string | null;
  requires_legal_verification: boolean;
  notes: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface PayrollStatutoryRuleInput {
  company_id: number;
  statutory_key: string;
  effective_from: string;
  effective_to?: string | null;
  rule_json?: Record<string, unknown>;
  source_reference: string;
  source_date?: string | null;
  requires_legal_verification?: boolean;
  notes?: string | null;
}

export interface PayrollStatutoryRulePageParams extends ListParams {
  statutory_key?: string;
  status?: string;
  as_of?: string;
}

export function listPayrollStatutoryRules(
  params: PayrollStatutoryRulePageParams = {},
): Promise<PageResponse<PayrollStatutoryRule>> {
  return get(`/payroll-statutory-rules${qs(params)}`);
}

export function createPayrollStatutoryRule(
  payload: PayrollStatutoryRuleInput,
): Promise<PayrollStatutoryRule> {
  return post("/payroll-statutory-rules", payload);
}

export function deactivatePayrollStatutoryRule(
  id: number,
  payload: { status?: string } = {},
): Promise<PayrollStatutoryRule> {
  return post(`/payroll-statutory-rules/${id}/deactivate`, payload);
}

// Phase 7 — Employee Self-Service (ESS)
export interface EssProfileName {
  id: number;
  name_ar: string;
  name_en: string;
}

export interface EssContract {
  id: number;
  contract_number: string | null;
  contract_type: string;
  start_date: string;
  end_date: string | null;
  basic_salary: string | null;
  currency: string;
}

export interface EssProfile {
  id: number;
  company_id: number;
  employee_number: string;
  first_name_ar: string;
  middle_name_ar: string | null;
  last_name_ar: string;
  first_name_en: string;
  middle_name_en: string | null;
  last_name_en: string;
  status: string;
  employment_type: string;
  hire_date: string | null;
  nationality: string;
  gender: string | null;
  work_email: string | null;
  mobile_phone: string | null;
  company: EssProfileName | null;
  department: EssProfileName | null;
  branch: EssProfileName | null;
  job_position: EssProfileName | null;
  manager: EssProfileName | null;
  contract: EssContract | null;
}

export interface PayslipSummary {
  id: number;
  run_id: number;
  employee_id: number;
  basic_snapshot: string;
  currency: string;
  earnings_total: string;
  deductions_total: string;
  net_pay: string;
  run_number: number;
  period_id: number;
  period_name: string;
  period_start: string;
  period_end: string;
  period_status: string;
}

export function myProfile(): Promise<EssProfile> {
  return get("/me/profile");
}

export function myDocuments(
  params: ListParams = {},
): Promise<PageResponse<EmployeeDocument>> {
  return get(`/me/documents${qs(params)}`);
}

export async function downloadMyDocument(
  documentId: number,
): Promise<{ blob: Blob; filename: string }> {
  const path = `/me/documents/${documentId}/download`;
  const fetchOnce = () =>
    fetch(`${API_BASE}${path}`, {
      headers: buildHeaders(),
      credentials: "include",
    });
  let response = await fetchOnce();
  if (response.status === 401 && (await tryRefresh())) {
    response = await fetchOnce();
  }
  if (!response.ok) {
    let detail = response.statusText;
    let code: string | null = null;
    try {
      const body = await response.json();
      detail = extractDetail(body, detail);
      code = readErrorCode(body);
    } catch {
      // non-JSON error body
    }
    throw new ApiError(response.status, detail, code);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  let filename = "download";
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) {
    filename = decodeURIComponent(star[1]);
  } else {
    const plain = disposition.match(/filename="?([^";]+)"?/i);
    if (plain) {
      filename = plain[1];
    }
  }
  return { blob: await response.blob(), filename };
}

export function myAttendance(
  params: AttendancePageParams = {},
): Promise<PageResponse<AttendanceRecord>> {
  return get(`/me/attendance${qs(params)}`);
}

export function myPayslips(
  params: ListParams = {},
): Promise<PageResponse<PayslipSummary>> {
  return get(`/me/payslips${qs(params)}`);
}

export function myPayslip(runLineId: number): Promise<Payslip> {
  return get(`/me/payslips/${runLineId}`);
}

// Phase 7 — Employee requests & approvals
export interface EmployeeRequestEvent {
  id: number;
  event_type: string;
  actor_name: string;
  note: string | null;
  created_at: string;
}

export interface EmployeeRequest {
  id: number;
  company_id: number;
  employee_id: number;
  approver_employee_id: number | null;
  request_type: string;
  status: string;
  subject: string;
  reason: string | null;
  payload: Record<string, unknown>;
  work_date: string | null;
  submitted_by: number | null;
  submitted_at: string | null;
  decided_by: number | null;
  decided_at: string | null;
  decision_reason: string | null;
  cancelled_by: number | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  attendance_record_id: number | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  events: EmployeeRequestEvent[];
}

export interface EmployeeRequestInput {
  request_type: string;
  subject: string;
  reason?: string | null;
  payload?: Record<string, unknown>;
  employee_id?: number | null;
}

export interface EmployeeRequestUpdate {
  subject?: string;
  reason?: string | null;
  payload?: Record<string, unknown>;
}

export interface EmployeeRequestPageParams extends ListParams {
  employee_id?: number;
  request_type?: string;
  status?: string;
}

export interface ApprovalsPageParams extends ListParams {
  status?: string;
}

export function listEmployeeRequests(
  params: EmployeeRequestPageParams = {},
): Promise<PageResponse<EmployeeRequest>> {
  return get(`/employee-requests${qs(params)}`);
}

export function getEmployeeRequest(id: number): Promise<EmployeeRequest> {
  return get(`/employee-requests/${id}`);
}

export function createEmployeeRequest(
  payload: EmployeeRequestInput,
): Promise<EmployeeRequest> {
  return post("/employee-requests", payload);
}

export function updateEmployeeRequest(
  id: number,
  payload: EmployeeRequestUpdate,
): Promise<EmployeeRequest> {
  return patch(`/employee-requests/${id}`, payload);
}

export function submitEmployeeRequest(id: number): Promise<EmployeeRequest> {
  return post(`/employee-requests/${id}/submit`, {});
}

export function cancelEmployeeRequest(
  id: number,
  reason?: string | null,
): Promise<EmployeeRequest> {
  return post(`/employee-requests/${id}/cancel`, { reason: reason || null });
}

export function approveEmployeeRequest(
  id: number,
  reason?: string | null,
): Promise<EmployeeRequest> {
  return post(`/employee-requests/${id}/approve`, { reason: reason || null });
}

export function rejectEmployeeRequest(
  id: number,
  reason: string,
): Promise<EmployeeRequest> {
  return post(`/employee-requests/${id}/reject`, { reason });
}

export function listApprovals(
  params: ApprovalsPageParams = {},
): Promise<PageResponse<EmployeeRequest>> {
  return get(`/approvals${qs(params)}`);
}

export interface DocumentVisibility {
  document_id: number;
  employee_visible: boolean;
  updated_by: number | null;
}

export function setEmployeeDocumentVisibility(
  documentId: number,
  employeeVisible: boolean,
): Promise<DocumentVisibility> {
  return patch(`/employee-documents/${documentId}/visibility`, {
    employee_visible: employeeVisible,
  });
}

export function getEmployeeDocumentVisibility(
  documentId: number,
): Promise<DocumentVisibility> {
  return get(`/employee-documents/${documentId}/visibility`);
}

// Phase 8 — Salary advances
export interface SalaryAdvanceEvent {
  id: number;
  event_type: string;
  actor_name: string;
  note: string | null;
  created_at: string;
}

export interface SalaryAdvance {
  id: number;
  company_id: number;
  employee_id: number;
  approver_employee_id: number | null;
  amount: string;
  reason: string;
  requested_date: string;
  installment_amount: string | null;
  status: string;
  submitted_by: number | null;
  submitted_at: string | null;
  decided_by: number | null;
  decided_at: string | null;
  decision_reason: string | null;
  disbursed_by: number | null;
  disbursed_at: string | null;
  settled_by: number | null;
  settled_at: string | null;
  settle_note: string | null;
  deduction_rule_id: number | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  events: SalaryAdvanceEvent[];
}

export interface SalaryAdvanceInput {
  amount: number;
  reason: string;
  requested_date: string;
  employee_id?: number | null;
}

export interface SalaryAdvanceUpdate {
  amount?: number;
  reason?: string;
  requested_date?: string;
}

export interface SalaryAdvanceDecisionInput {
  reason?: string | null;
}

export interface SalaryAdvanceDisburseInput {
  installment_amount?: number | null;
  note?: string | null;
}

export interface SalaryAdvanceSettleInput {
  reason?: string | null;
}

export interface SalaryAdvancesPageParams extends ListParams {
  employee_id?: number;
  assigned_to_me?: boolean;
}

export function listSalaryAdvances(
  params: SalaryAdvancesPageParams = {},
): Promise<PageResponse<SalaryAdvance>> {
  return get(`/salary-advances${qs(params)}`);
}

export function getSalaryAdvance(id: number): Promise<SalaryAdvance> {
  return get(`/salary-advances/${id}`);
}

export function createSalaryAdvance(
  payload: SalaryAdvanceInput,
): Promise<SalaryAdvance> {
  return post("/salary-advances", payload);
}

export function updateSalaryAdvance(
  id: number,
  payload: SalaryAdvanceUpdate,
): Promise<SalaryAdvance> {
  return patch(`/salary-advances/${id}`, payload);
}

export function submitSalaryAdvance(id: number): Promise<SalaryAdvance> {
  return post(`/salary-advances/${id}/submit`, {});
}

export function cancelSalaryAdvance(
  id: number,
  reason?: string | null,
): Promise<SalaryAdvance> {
  return post(`/salary-advances/${id}/cancel`, { reason: reason || null });
}

export function approveSalaryAdvance(
  id: number,
  reason?: string | null,
): Promise<SalaryAdvance> {
  return post(`/salary-advances/${id}/approve`, { reason: reason || null });
}

export function rejectSalaryAdvance(
  id: number,
  reason: string,
): Promise<SalaryAdvance> {
  return post(`/salary-advances/${id}/reject`, { reason });
}

export function disburseSalaryAdvance(
  id: number,
  payload: SalaryAdvanceDisburseInput = {},
): Promise<SalaryAdvance> {
  return post(`/salary-advances/${id}/disburse`, payload);
}

export function settleSalaryAdvance(
  id: number,
  payload: SalaryAdvanceSettleInput = {},
): Promise<SalaryAdvance> {
  return post(`/salary-advances/${id}/settle`, payload);
}

// Phase 9 — HR letters
export interface HrLetterEvent {
  id: number;
  action: string;
  from_status: string | null;
  to_status: string;
  actor_name: string;
  note: string | null;
  created_at: string;
}

export interface HrLetterListItem {
  id: number;
  reference: string;
  company_id: number;
  employee_id: number;
  letter_type: string;
  language: string;
  purpose: string | null;
  status: string;
  source_request_id: number | null;
  issued_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface HrLetter extends HrLetterListItem {
  content: Record<string, string | null>;
  issued_by: number | null;
  cancelled_at: string | null;
  cancelled_by: number | null;
  cancel_reason: string | null;
  voided_at: string | null;
  voided_by: number | null;
  void_reason: string | null;
  created_by: number | null;
  updated_by: number | null;
  version: number;
  events: HrLetterEvent[];
}

export interface HrLetterInput {
  employee_id: number;
  letter_type: string;
  language?: string;
  purpose?: string | null;
  source_request_id?: number | null;
}

export interface HrLetterUpdate {
  purpose?: string | null;
  language?: string;
}

export interface HrLettersPageParams extends ListParams {
  employee_id?: number;
  letter_type?: string;
}

export function listHrLetters(
  params: HrLettersPageParams = {},
): Promise<PageResponse<HrLetterListItem>> {
  return get(`/hr-letters${qs(params)}`);
}

export function getHrLetter(id: number): Promise<HrLetter> {
  return get(`/hr-letters/${id}`);
}

export function createHrLetter(payload: HrLetterInput): Promise<HrLetter> {
  return post("/hr-letters", payload);
}

export function updateHrLetter(
  id: number,
  payload: HrLetterUpdate,
): Promise<HrLetter> {
  return patch(`/hr-letters/${id}`, payload);
}

export function issueHrLetter(id: number): Promise<HrLetter> {
  return post(`/hr-letters/${id}/issue`, {});
}

export function cancelHrLetter(
  id: number,
  reason?: string | null,
): Promise<HrLetter> {
  return post(`/hr-letters/${id}/cancel`, { reason: reason || null });
}

export function voidHrLetter(id: number, reason: string): Promise<HrLetter> {
  return post(`/hr-letters/${id}/void`, { reason });
}

export function listMyLetters(
  params: ListParams = {},
): Promise<PageResponse<HrLetterListItem>> {
  return get(`/me/letters${qs(params)}`);
}

export function getMyLetter(id: number): Promise<HrLetter> {
  return get(`/me/letters/${id}`);
}
