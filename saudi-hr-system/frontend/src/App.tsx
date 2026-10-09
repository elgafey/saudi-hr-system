import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import {
  bootstrapSession,
  logout as apiLogout,
  setActiveCompanyId,
  type MeResponse,
} from "./api";
import AdvancesPage from "./pages/AdvancesPage";
import AttendancePage from "./pages/AttendancePage";
import DashboardPage from "./pages/DashboardPage";
import DepartmentsPage from "./pages/DepartmentsPage";
import EmployeeDetailPage from "./pages/EmployeeDetailPage";
import EmployeeFormPage from "./pages/EmployeeFormPage";
import EmployeesPage from "./pages/EmployeesPage";
import EssApprovalsPage from "./pages/EssApprovalsPage";
import EssAttendancePage from "./pages/EssAttendancePage";
import EssDocumentsPage from "./pages/EssDocumentsPage";
import EssLayoutPage from "./pages/EssLayoutPage";
import EssLettersPage from "./pages/EssLettersPage";
import EssPayslipsPage from "./pages/EssPayslipsPage";
import EssProfilePage from "./pages/EssProfilePage";
import EssRequestsPage from "./pages/EssRequestsPage";
import JobGradesPage from "./pages/JobGradesPage";
import JobPositionsPage from "./pages/JobPositionsPage";
import LeaveAllocationsPage from "./pages/LeaveAllocationsPage";
import LettersPage from "./pages/LettersPage";
import LeaveBalancesPage from "./pages/LeaveBalancesPage";
import LeaveHolidaysPage from "./pages/LeaveHolidaysPage";
import LeaveRequestsPage from "./pages/LeaveRequestsPage";
import LeaveTypesPage from "./pages/LeaveTypesPage";
import LoginPage from "./pages/LoginPage";
import OvertimePage from "./pages/OvertimePage";
import PayrollAdjustmentsPage from "./pages/PayrollAdjustmentsPage";
import PayrollDeductionsPage from "./pages/PayrollDeductionsPage";
import PayrollPeriodsPage from "./pages/PayrollPeriodsPage";
import PayrollRunDetailPage from "./pages/PayrollRunDetailPage";
import PayrollStatutoryRulesPage from "./pages/PayrollStatutoryRulesPage";
import SalaryAssignmentsPage from "./pages/SalaryAssignmentsPage";
import SalaryComponentsPage from "./pages/SalaryComponentsPage";
import ShiftsPage from "./pages/ShiftsPage";
import WorkSchedulesPage from "./pages/WorkSchedulesPage";
import { applyDocumentDirection, translate, type Locale } from "./i18n";

interface Session {
  me: MeResponse | null;
  loading: boolean;
  locale: Locale;
  t: (key: string) => string;
  can: (code: string) => boolean;
  setLocale: (locale: Locale) => void;
  signIn: (me: MeResponse) => void;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    throw new Error("useSession must be used within SessionContext");
  }
  return ctx;
}

export default function App() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [locale, setLocaleState] = useState<Locale>(
    () => (localStorage.getItem("locale") as Locale) || "en",
  );
  const navigate = useNavigate();

  const t = useCallback(
    (key: string) => translate(locale, key),
    [locale],
  );

  const can = useCallback(
    (code: string) => Boolean(me?.permissions.includes(code)),
    [me],
  );

  useEffect(() => {
    setActiveCompanyId(me?.company_ids[0] ?? null);
  }, [me]);

  const setLocale = useCallback((next: Locale) => {
    localStorage.setItem("locale", next);
    setLocaleState(next);
  }, []);

  useEffect(() => {
    applyDocumentDirection(locale);
  }, [locale]);

  useEffect(() => {
    let cancelled = false;
    bootstrapSession().then((session) => {
      if (!cancelled) {
        setMe(session);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(
    (session: MeResponse) => {
      setMe(session);
      navigate("/");
    },
    [navigate],
  );

  const signOut = useCallback(async () => {
    await apiLogout();
    setMe(null);
    navigate("/login");
  }, [navigate]);

  const value: Session = {
    me,
    loading,
    locale,
    t,
    can,
    setLocale,
    signIn,
    signOut,
  };

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `rounded px-2 py-1 text-sm ${
      isActive
        ? "bg-slate-900 text-white"
        : "text-slate-600 hover:bg-slate-100"
    }`;

  const showNav = Boolean(me);

  return (
    <SessionContext.Provider value={value}>
      <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-4">
        <header className="flex items-center justify-between gap-4 py-4">
          <span className="text-lg font-semibold">{t("app.title")}</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setLocale(locale === "en" ? "ar" : "en")}
              className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100"
            >
              {t("lang.toggle")}
            </button>
          </div>
        </header>
        {showNav ? (
          <nav className="flex flex-wrap gap-1 border-b border-slate-200 pb-2">
            <NavLink to="/" end className={navLinkClass}>
              {t("nav.dashboard")}
            </NavLink>
            <NavLink to="/departments" className={navLinkClass}>
              {t("nav.departments")}
            </NavLink>
            <NavLink to="/job-positions" className={navLinkClass}>
              {t("nav.jobPositions")}
            </NavLink>
            <NavLink to="/job-grades" className={navLinkClass}>
              {t("nav.jobGrades")}
            </NavLink>
            <NavLink to="/employees" className={navLinkClass}>
              {t("nav.employees")}
            </NavLink>
            {can("attendance.view") ? (
              <NavLink to="/attendance" className={navLinkClass}>
                {t("nav.attendance")}
              </NavLink>
            ) : null}
            {can("work_schedule.view") ? (
              <NavLink to="/work-schedules" className={navLinkClass}>
                {t("nav.workSchedules")}
              </NavLink>
            ) : null}
            {can("shift.view") ? (
              <NavLink to="/shifts" className={navLinkClass}>
                {t("nav.shifts")}
              </NavLink>
            ) : null}
            {can("overtime.view") ? (
              <NavLink to="/overtime" className={navLinkClass}>
                {t("nav.overtime")}
              </NavLink>
            ) : null}
            {can("leave_request.view") || can("leave_request.create") ? (
              <NavLink to="/leave-requests" className={navLinkClass}>
                {t("nav.leaveRequests")}
              </NavLink>
            ) : null}
            {can("leave_allocation.view") ? (
              <NavLink to="/leave-allocations" className={navLinkClass}>
                {t("nav.leaveAllocations")}
              </NavLink>
            ) : null}
            {can("leave_type.view") ? (
              <NavLink to="/leave-types" className={navLinkClass}>
                {t("nav.leaveTypes")}
              </NavLink>
            ) : null}
            {can("leave_balance.view") ? (
              <NavLink to="/leave-balances" className={navLinkClass}>
                {t("nav.leaveBalances")}
              </NavLink>
            ) : null}
            {can("leave_holiday.view") ? (
              <NavLink to="/leave-holidays" className={navLinkClass}>
                {t("nav.leaveHolidays")}
              </NavLink>
            ) : null}
            {can("payroll_period.view") ? (
              <NavLink to="/payroll-periods" className={navLinkClass}>
                {t("nav.payroll")}
              </NavLink>
            ) : null}
            {can("salary_component.view") ? (
              <NavLink to="/salary-components" className={navLinkClass}>
                {t("nav.salaryComponents")}
              </NavLink>
            ) : null}
            {can("salary_assignment.view") ? (
              <NavLink to="/salary-assignments" className={navLinkClass}>
                {t("nav.salaryAssignments")}
              </NavLink>
            ) : null}
            {can("payroll_adjustment.view") ? (
              <NavLink to="/payroll-adjustments" className={navLinkClass}>
                {t("nav.payrollAdjustments")}
              </NavLink>
            ) : null}
            {can("payroll_deduction.view") ? (
              <NavLink to="/payroll-deductions" className={navLinkClass}>
                {t("nav.payrollDeductions")}
              </NavLink>
            ) : null}
            {can("payroll_statutory_rule.view") ? (
              <NavLink
                to="/payroll-statutory-rules"
                className={navLinkClass}
              >
                {t("nav.payrollStatutoryRules")}
              </NavLink>
            ) : null}
            <NavLink to="/me" className={navLinkClass}>
              {t("nav.me")}
            </NavLink>
            {can("employee_request.view") ||
            can("employee_request.create") ? (
              <NavLink to="/requests" className={navLinkClass}>
                {t("nav.requests")}
              </NavLink>
            ) : null}
            {can("employee_request.approve") ||
            can("employee_request.manage") ||
            can("employee_request.view") ? (
              <NavLink to="/approvals" className={navLinkClass}>
                {t("nav.approvals")}
              </NavLink>
            ) : null}
            {can("salary_advance.view") || can("salary_advance.create") ? (
              <NavLink to="/advances" className={navLinkClass}>
                {t("nav.advances")}
              </NavLink>
            ) : null}
            {can("hr_letter.view") || can("hr_letter.create") ? (
              <NavLink to="/letters" className={navLinkClass}>
                {t("nav.letters")}
              </NavLink>
            ) : null}
          </nav>
        ) : null}
        <main className="flex-1">
          {loading ? (
            <p className="py-16 text-center text-slate-500">
              {t("common.loading")}
            </p>
          ) : (
            <Routes>
              <Route
                path="/login"
                element={
                  me ? <Navigate to="/" replace /> : <LoginPage />
                }
              />
              <Route
                path="/"
                element={
                  me ? <DashboardPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/departments"
                element={
                  me ? <DepartmentsPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/job-positions"
                element={
                  me ? <JobPositionsPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/job-grades"
                element={
                  me ? <JobGradesPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/employees"
                element={
                  me ? <EmployeesPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/employees/new"
                element={
                  me ? (
                    <EmployeeFormPage mode="create" />
                  ) : (
                    <Navigate to="/login" replace />
                  )
                }
              />
              <Route
                path="/employees/:id/edit"
                element={
                  me ? (
                    <EmployeeFormPage mode="edit" />
                  ) : (
                    <Navigate to="/login" replace />
                  )
                }
              />
              <Route
                path="/employees/:id"
                element={
                  me ? (
                    <EmployeeDetailPage />
                  ) : (
                    <Navigate to="/login" replace />
                  )
                }
              />
              <Route
                path="/attendance"
                element={
                  me ? <AttendancePage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/work-schedules"
                element={
                  me ? <WorkSchedulesPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/shifts"
                element={
                  me ? <ShiftsPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/overtime"
                element={
                  me ? <OvertimePage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/leave-requests"
                element={
                  me ? <LeaveRequestsPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/leave-allocations"
                element={
                  me ? (
                    <LeaveAllocationsPage />
                  ) : (
                    <Navigate to="/login" replace />
                  )
                }
              />
              <Route
                path="/leave-types"
                element={
                  me ? <LeaveTypesPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/leave-balances"
                element={
                  me ? <LeaveBalancesPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/leave-holidays"
                element={
                  me ? (
                    <LeaveHolidaysPage />
                  ) : (
                    <Navigate to="/login" replace />
                  )
                }
              />
              <Route
                path="/salary-components"
                element={
                  me ? <SalaryComponentsPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/salary-assignments"
                element={
                  me ? (
                    <SalaryAssignmentsPage />
                  ) : (
                    <Navigate to="/login" replace />
                  )
                }
              />
              <Route
                path="/payroll-periods"
                element={
                  me ? <PayrollPeriodsPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/payroll-runs/:id"
                element={
                  me ? (
                    <PayrollRunDetailPage />
                  ) : (
                    <Navigate to="/login" replace />
                  )
                }
              />
              <Route
                path="/payroll-adjustments"
                element={
                  me ? (
                    <PayrollAdjustmentsPage />
                  ) : (
                    <Navigate to="/login" replace />
                  )
                }
              />
              <Route
                path="/payroll-deductions"
                element={
                  me ? (
                    <PayrollDeductionsPage />
                  ) : (
                    <Navigate to="/login" replace />
                  )
                }
              />
              <Route
                path="/payroll-statutory-rules"
                element={
                  me ? (
                    <PayrollStatutoryRulesPage />
                  ) : (
                    <Navigate to="/login" replace />
                  )
                }
              />
              <Route
                path="/me"
                element={
                  me ? <EssLayoutPage /> : <Navigate to="/login" replace />
                }
              >
                <Route index element={<EssProfilePage />} />
                <Route path="documents" element={<EssDocumentsPage />} />
                <Route path="attendance" element={<EssAttendancePage />} />
                <Route path="payslips" element={<EssPayslipsPage />} />
                <Route path="letters" element={<EssLettersPage />} />
              </Route>
              <Route
                path="/requests"
                element={
                  me ? <EssRequestsPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/approvals"
                element={
                  me ? <EssApprovalsPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/advances"
                element={
                  me ? <AdvancesPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="/letters"
                element={
                  me ? <LettersPage /> : <Navigate to="/login" replace />
                }
              />
              <Route
                path="*"
                element={<Navigate to="/" replace />}
              />
            </Routes>
          )}
        </main>
      </div>
    </SessionContext.Provider>
  );
}
