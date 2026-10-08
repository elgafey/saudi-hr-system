import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useSession } from "../App";
import {
  deleteEmployee,
  getDepartment,
  getEmployee,
  getJobGrade,
  getJobPosition,
  listBranches,
  type Employee,
} from "../api";
import AttendancePanel from "../components/AttendancePanel";
import CompensationPanel from "../components/CompensationPanel";
import ContractsPanel from "../components/ContractsPanel";
import DocumentsPanel from "../components/DocumentsPanel";
import HistoryPanel from "../components/HistoryPanel";
import LeavePanel from "../components/LeavePanel";
import UserAccountPanel from "../components/UserAccountPanel";
import {
  dangerButtonClass,
  errorMessage,
  errorTextClass,
  ghostButtonClass,
} from "../ui";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-b border-slate-100 py-2">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-sm">{value || "—"}</dd>
    </div>
  );
}

interface OrgNames {
  department: string;
  position: string;
  grade: string;
  manager: string;
  branch: string;
}

const emptyNames: OrgNames = {
  department: "",
  position: "",
  grade: "",
  manager: "",
  branch: "",
};

type TabKey =
  | "profile"
  | "employment"
  | "contracts"
  | "documents"
  | "history"
  | "account"
  | "attendance"
  | "leave"
  | "compensation";

export default function EmployeeDetailPage() {
  const { t, can, me } = useSession();
  const navigate = useNavigate();
  const params = useParams<{ id: string }>();
  const employeeId = params.id ? Number(params.id) : null;
  const companyId = me?.company_ids[0] ?? null;

  const [employee, setEmployee] = useState<Employee | null>(null);
  const [names, setNames] = useState<OrgNames>(emptyNames);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<TabKey>("profile");

  const load = useCallback(async () => {
    if (employeeId === null) {
      return;
    }
    setLoading(true);
    try {
      const row = await getEmployee(employeeId);
      setEmployee(row);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [employeeId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!employee) {
      setNames(emptyNames);
      return;
    }
    let cancelled = false;
    const next: OrgNames = { ...emptyNames };

    const jobs: Promise<void>[] = [];
    if (employee.department_id) {
      const id = employee.department_id;
      jobs.push(
        getDepartment(id)
          .then((row) => {
            next.department = row.name_en;
          })
          .catch(() => undefined),
      );
    }
    if (employee.job_position_id) {
      const id = employee.job_position_id;
      jobs.push(
        getJobPosition(id)
          .then((row) => {
            next.position = row.name_en;
          })
          .catch(() => undefined),
      );
    }
    if (employee.job_grade_id) {
      const id = employee.job_grade_id;
      jobs.push(
        getJobGrade(id)
          .then((row) => {
            next.grade = `L${row.level} — ${row.name_en}`;
          })
          .catch(() => undefined),
      );
    }
    if (employee.manager_id) {
      const id = employee.manager_id;
      jobs.push(
        getEmployee(id)
          .then((row) => {
            next.manager = `${row.employee_number} — ${row.first_name_en} ${row.last_name_en}`;
          })
          .catch(() => undefined),
      );
    }
    if (employee.branch_id) {
      const id = employee.branch_id;
      jobs.push(
        listBranches(employee.company_id)
          .then((rows) => {
            const found = rows.find((row) => row.id === id);
            if (found) {
              next.branch = `${found.code} — ${found.name}`;
            }
          })
          .catch(() => undefined),
      );
    }

    void Promise.all(jobs).then(() => {
      if (!cancelled) {
        setNames(next);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [employee]);

  const allTabs: { key: TabKey; label: string; visible: boolean }[] = [
    { key: "profile", label: t("employees.tab.profile"), visible: true },
    { key: "employment", label: t("employees.tab.employment"), visible: true },
    {
      key: "contracts",
      label: t("employees.tab.contracts"),
      visible: can("employee_contract.view"),
    },
    {
      key: "documents",
      label: t("employees.tab.documents"),
      visible: can("employee_document.view"),
    },
    {
      key: "history",
      label: t("employees.tab.history"),
      visible: can("employee_history.view"),
    },
    {
      key: "account",
      label: t("employees.tab.account"),
      visible: can("employee_user_link.view"),
    },
    {
      key: "attendance",
      label: t("employees.tab.attendance"),
      visible:
        can("employee_work_assignment.view") ||
        can("attendance.view") ||
        can("overtime.view"),
    },
    {
      key: "leave",
      label: t("employees.tab.leave"),
      visible: can("leave_request.view") || can("leave_balance.view"),
    },
    {
      key: "compensation",
      label: t("employees.tab.compensation"),
      visible: can("salary_assignment.view"),
    },
  ];
  const tabs = allTabs.filter((entry) => entry.visible);

  useEffect(() => {
    if (!tabs.some((entry) => entry.key === tab)) {
      setTab(tabs[0]?.key ?? "profile");
    }
  });

  async function remove() {
    if (employeeId === null) {
      return;
    }
    if (!window.confirm(t("employees.deleteConfirm"))) {
      return;
    }
    try {
      await deleteEmployee(employeeId);
      navigate("/employees");
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  if (loading) {
    return (
      <div className="py-16">
        <p className="text-center text-slate-500">{t("common.loading")}</p>
      </div>
    );
  }

  if (!employee) {
    return (
      <div className="space-y-4 py-16">
        <p className={errorTextClass}>{error ?? t("common.error")}</p>
        <Link to="/employees" className="text-sm text-blue-600 hover:underline">
          {t("common.back")}
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-mono text-xs text-slate-500">
            {employee.employee_number}
          </p>
          <h1 className="text-xl font-semibold">
            {employee.first_name_en} {employee.middle_name_en ?? ""}{" "}
            {employee.last_name_en}
          </h1>
          <p dir="rtl" className="text-slate-600">
            {employee.first_name_ar} {employee.middle_name_ar ?? ""}{" "}
            {employee.last_name_ar}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded bg-slate-100 px-2 py-1 text-xs">
            {t(`status.${employee.status}`)}
          </span>
          {can("employee.update") ? (
            <Link
              to={`/employees/${employee.id}/edit`}
              className={ghostButtonClass}
            >
              {t("common.edit")}
            </Link>
          ) : null}
          {can("employee.delete") ? (
            <button
              type="button"
              onClick={() => void remove()}
              className={dangerButtonClass}
            >
              {t("common.delete")}
            </button>
          ) : null}
          <Link to="/employees" className="text-sm text-blue-600 hover:underline">
            {t("common.back")}
          </Link>
        </div>
      </div>

      {error ? <p className={errorTextClass}>{error}</p> : null}

      <div className="flex flex-wrap gap-1 border-b border-slate-200 pb-2">
        {tabs.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setTab(entry.key)}
            className={`rounded px-3 py-1.5 text-sm ${
              tab === entry.key
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {tab === "profile" ? (
        <div className="grid gap-6 md:grid-cols-2">
          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <h2 className="mb-2 text-sm font-semibold">
              {t("employees.sectionIdentity")}
            </h2>
            <dl>
              <Row
                label={t("employees.identityType")}
                value={
                  employee.identity_type
                    ? t(`identity.${employee.identity_type}`)
                    : ""
                }
              />
              <Row
                label={t("employees.identityNumber")}
                value={employee.identity_number ?? ""}
              />
              <Row
                label={t("employees.issueDate")}
                value={employee.identity_issue_date ?? ""}
              />
              <Row
                label={t("employees.expiryDate")}
                value={employee.identity_expiry_date ?? ""}
              />
              <Row
                label={t("employees.dob")}
                value={employee.date_of_birth ?? ""}
              />
              <Row
                label={t("employees.gender")}
                value={employee.gender ? t(`gender.${employee.gender}`) : ""}
              />
              <Row
                label={t("employees.nationality")}
                value={employee.nationality}
              />
            </dl>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <h2 className="mb-2 text-sm font-semibold">
              {t("employees.sectionContact")}
            </h2>
            <dl>
              <Row
                label={t("employees.personalEmail")}
                value={employee.personal_email ?? ""}
              />
              <Row
                label={t("employees.workEmail")}
                value={employee.work_email ?? ""}
              />
              <Row
                label={t("employees.mobile")}
                value={employee.mobile_phone ?? ""}
              />
              <Row
                label={t("employees.emergencyName")}
                value={employee.emergency_contact_name ?? ""}
              />
              <Row
                label={t("employees.emergencyPhone")}
                value={employee.emergency_contact_phone ?? ""}
              />
            </dl>
          </section>
        </div>
      ) : null}

      {tab === "employment" ? (
        <div className="grid gap-6 md:grid-cols-2">
          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <h2 className="mb-2 text-sm font-semibold">
              {t("employees.sectionOrg")}
            </h2>
            <dl>
              <Row
                label={t("employees.department")}
                value={names.department}
              />
              <Row label={t("employees.position")} value={names.position} />
              <Row label={t("employees.grade")} value={names.grade} />
              <Row label={t("employees.manager")} value={names.manager} />
              <Row label={t("employees.branch")} value={names.branch} />
            </dl>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <h2 className="mb-2 text-sm font-semibold">
              {t("employees.sectionEmployment")}
            </h2>
            <dl>
              <Row
                label={t("employees.employmentType")}
                value={t(`empType.${employee.employment_type}`)}
              />
              <Row
                label={t("employees.hireDate")}
                value={employee.hire_date ?? ""}
              />
              <Row
                label={t("employees.probationEnd")}
                value={employee.probation_end_date ?? ""}
              />
              <Row
                label={t("employees.terminationDate")}
                value={employee.termination_date ?? ""}
              />
              <Row label={t("employees.notes")} value={employee.notes ?? ""} />
            </dl>
          </section>
        </div>
      ) : null}

      {tab === "contracts" && companyId !== null ? (
        <ContractsPanel employeeId={employee.id} companyId={companyId} />
      ) : null}

      {tab === "documents" ? (
        <DocumentsPanel employeeId={employee.id} />
      ) : null}

      {tab === "history" && companyId !== null ? (
        <HistoryPanel employeeId={employee.id} companyId={companyId} />
      ) : null}

      {tab === "account" && companyId !== null ? (
        <UserAccountPanel employeeId={employee.id} companyId={companyId} />
      ) : null}

      {tab === "attendance" && companyId !== null ? (
        <AttendancePanel employeeId={employee.id} companyId={companyId} />
      ) : null}

      {tab === "leave" && companyId !== null ? (
        <LeavePanel employeeId={employee.id} companyId={companyId} />
      ) : null}

      {tab === "compensation" && companyId !== null ? (
        <CompensationPanel employeeId={employee.id} companyId={companyId} />
      ) : null}
    </div>
  );
}
