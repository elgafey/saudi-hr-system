import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSession } from "../App";
import {
  createEmployeeWorkAssignment,
  deleteEmployeeWorkAssignment,
  getShift,
  getWorkSchedule,
  listAttendance,
  listEmployeeWorkAssignments,
  listOvertime,
  listShifts,
  listWorkSchedules,
  resolveEmployeeSchedule,
  updateEmployeeWorkAssignment,
  type AttendanceRecord,
  type EmployeeWorkAssignment,
  type OvertimeRecord,
  type PageMeta,
  type ResolvedSchedule,
} from "../api";
import Pagination from "./Pagination";
import SearchSelect from "./SearchSelect";
import {
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../ui";

const pageSize = 10;

interface AssignmentFormState {
  schedule_id: string;
  shift_id: string;
  effective_from: string;
  effective_to: string;
  notes: string;
}

const emptyForm: AssignmentFormState = {
  schedule_id: "",
  shift_id: "",
  effective_from: "",
  effective_to: "",
  notes: "",
};

interface Props {
  employeeId: number;
  companyId: number;
}

export default function AttendancePanel({ employeeId, companyId }: Props) {
  const { t, can } = useSession();

  const [resolved, setResolved] = useState<ResolvedSchedule | null>(null);
  const [resolvedAt, setResolvedAt] = useState<string>("");

  const [assignments, setAssignments] = useState<EmployeeWorkAssignment[]>([]);
  const [assignmentMeta, setAssignmentMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [assignmentPage, setAssignmentPage] = useState(1);
  const [assignmentsLoading, setAssignmentsLoading] = useState(true);

  const [attendance, setAttendance] = useState<AttendanceRecord[]>([]);
  const [attendanceLoading, setAttendanceLoading] = useState(true);

  const [overtime, setOvertime] = useState<OvertimeRecord[]>([]);
  const [overtimeLoading, setOvertimeLoading] = useState(true);

  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<AssignmentFormState | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (key: keyof AssignmentFormState, value: string) =>
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));

  const loadResolved = useCallback(async () => {
    try {
      const row = await resolveEmployeeSchedule(employeeId);
      setResolved(row);
      setResolvedAt(row.date);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    }
  }, [employeeId, t]);

  const loadAssignments = useCallback(async () => {
    setAssignmentsLoading(true);
    try {
      const res = await listEmployeeWorkAssignments(employeeId, {
        page: assignmentPage,
        page_size: pageSize,
      });
      setAssignments(res.items);
      setAssignmentMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setAssignmentsLoading(false);
    }
  }, [employeeId, assignmentPage, t]);

  const loadAttendance = useCallback(async () => {
    setAttendanceLoading(true);
    try {
      const res = await listAttendance({
        company_id: companyId,
        employee_id: employeeId,
        page: 1,
        page_size: pageSize,
      });
      setAttendance(res.items);
      setAttendanceLoading(false);
    } catch {
      setAttendanceLoading(false);
    }
  }, [companyId, employeeId]);

  const loadOvertime = useCallback(async () => {
    setOvertimeLoading(true);
    try {
      const res = await listOvertime({
        company_id: companyId,
        employee_id: employeeId,
        page: 1,
        page_size: pageSize,
      });
      setOvertime(res.items);
      setOvertimeLoading(false);
    } catch {
      setOvertimeLoading(false);
    }
  }, [companyId, employeeId]);

  useEffect(() => {
    void loadResolved();
  }, [loadResolved]);

  useEffect(() => {
    void loadAssignments();
  }, [loadAssignments]);

  useEffect(() => {
    void loadAttendance();
  }, [loadAttendance]);

  useEffect(() => {
    void loadOvertime();
  }, [loadOvertime]);

  function startCreate() {
    setEditingId(null);
    setForm({ ...emptyForm });
  }

  function startEdit(row: EmployeeWorkAssignment) {
    setEditingId(row.id);
    setForm({
      schedule_id: String(row.schedule_id),
      shift_id: row.shift_id ? String(row.shift_id) : "",
      effective_from: row.effective_from,
      effective_to: row.effective_to ?? "",
      notes: row.notes ?? "",
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editingId !== null) {
        await updateEmployeeWorkAssignment(employeeId, editingId, {
          schedule_id: Number(form.schedule_id),
          shift_id: form.shift_id ? Number(form.shift_id) : null,
          effective_from: form.effective_from,
          effective_to: form.effective_to || null,
          notes: form.notes.trim() || null,
        });
      } else {
        await createEmployeeWorkAssignment(employeeId, {
          schedule_id: Number(form.schedule_id),
          shift_id: form.shift_id ? Number(form.shift_id) : null,
          effective_from: form.effective_from,
          effective_to: form.effective_to || null,
          notes: form.notes.trim() || null,
        });
      }
      setForm(null);
      setEditingId(null);
      await Promise.all([
        loadAssignments(),
        loadResolved(),
        loadAttendance(),
      ]);
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSaving(false);
    }
  }

  async function remove(row: EmployeeWorkAssignment) {
    if (!window.confirm(t("employees.assignment.deleteConfirm"))) {
      return;
    }
    setError(null);
    try {
      await deleteEmployeeWorkAssignment(employeeId, row.id);
      await Promise.all([loadAssignments(), loadResolved()]);
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  const canViewAssignments = can("employee_work_assignment.view");
  const canCreateAssignment = can("employee_work_assignment.create");
  const canUpdateAssignment = can("employee_work_assignment.update");
  const canDeleteAssignment = can("employee_work_assignment.delete");

  return (
    <div className="space-y-6">
      {error ? <p className={errorTextClass}>{error}</p> : null}

      {canViewAssignments ? (
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">
              {t("employees.assignment.current")}
            </h2>
            {canCreateAssignment ? (
              <button
                type="button"
                onClick={startCreate}
                className={primaryButtonClass}
              >
                + {t("employees.assignment.new")}
              </button>
            ) : null}
          </div>

          {!resolved || !resolved.schedule_id ? (
            <p className="text-sm text-slate-500">
              {t("assignments.empty")}
            </p>
          ) : (
            <dl className="grid gap-x-6 sm:grid-cols-2">
              <div className="border-b border-slate-100 py-2">
                <dt className="text-xs text-slate-500">
                  {t("employees.assignment.schedule")}
                </dt>
                <dd className="text-sm">
                  {resolved.schedule_code} — {resolved.schedule_name_en}
                </dd>
              </div>
              <div className="border-b border-slate-100 py-2">
                <dt className="text-xs text-slate-500">
                  {t("employees.assignment.shift")}
                </dt>
                <dd className="text-sm">
                  {resolved.shift_id
                    ? `${resolved.shift_code} — ${resolved.shift_name_en}`
                    : "—"}
                </dd>
              </div>
              <div className="border-b border-slate-100 py-2">
                <dt className="text-xs text-slate-500">
                  {t("attendance.date")}
                </dt>
                <dd className="text-sm">{resolvedAt || "—"}</dd>
              </div>
              <div className="border-b border-slate-100 py-2">
                <dt className="text-xs text-slate-500">
                  {t("schedules.startTime")}
                </dt>
                <dd className="text-sm">
                  {resolved.start_time && resolved.end_time
                    ? `${resolved.start_time} — ${resolved.end_time}${
                        resolved.crosses_midnight
                          ? ` (${t("schedules.overnight")})`
                          : ""
                      }`
                    : "—"}
                </dd>
              </div>
            </dl>
          )}

          {form ? (
            <form
              onSubmit={submit}
              className="mt-4 grid gap-3 border-t border-slate-200 pt-4 sm:grid-cols-2"
            >
              <label className="block">
                <span className={labelClass}>
                  {t("employees.assignment.schedule")}
                </span>
                <SearchSelect
                  label=""
                  value={form.schedule_id}
                  onChange={(val) => set("schedule_id", val)}
                  load={async (search) => {
                    const res = await listWorkSchedules({
                      company_id: companyId,
                      search: search || undefined,
                      limit: 20,
                    });
                    return res.items.map((row) => ({
                      id: row.id,
                      label: `${row.code} — ${row.name_en}`,
                    }));
                  }}
                  resolve={async (id) => {
                    const row = await getWorkSchedule(id);
                    return `${row.code} — ${row.name_en}`;
                  }}
                />
              </label>
              <label className="block">
                <span className={labelClass}>
                  {t("employees.assignment.shiftOptional")}
                </span>
                <SearchSelect
                  label=""
                  value={form.shift_id}
                  onChange={(val) => set("shift_id", val)}
                  load={async (search) => {
                    const res = await listShifts({
                      company_id: companyId,
                      search: search || undefined,
                      limit: 20,
                    });
                    return res.items.map((row) => ({
                      id: row.id,
                      label: `${row.code} — ${row.name_en}`,
                    }));
                  }}
                  resolve={async (id) => {
                    const row = await getShift(id);
                    return `${row.code} — ${row.name_en}`;
                  }}
                />
              </label>
              <label className="block">
                <span className={labelClass}>
                  {t("employees.assignment.effectiveFromRequired")}
                </span>
                <input
                  required
                  type="date"
                  value={form.effective_from}
                  onChange={(event) => set("effective_from", event.target.value)}
                  className={inputClass}
                />
              </label>
              <label className="block">
                <span className={labelClass}>
                  {t("employees.assignment.effectiveToOptional")}
                </span>
                <input
                  type="date"
                  value={form.effective_to}
                  onChange={(event) => set("effective_to", event.target.value)}
                  className={inputClass}
                />
              </label>
              <label className="block sm:col-span-2">
                <span className={labelClass}>
                  {t("employees.assignment.notes")}
                </span>
                <input
                  maxLength={500}
                  value={form.notes}
                  onChange={(event) => set("notes", event.target.value)}
                  className={inputClass}
                />
              </label>
              <div className="flex gap-2 sm:col-span-2">
                <button
                  type="submit"
                  disabled={saving || form.schedule_id === ""}
                  className={primaryButtonClass}
                >
                  {saving ? t("common.saving") : t("common.save")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setForm(null);
                    setEditingId(null);
                  }}
                  className={ghostButtonClass}
                >
                  {t("common.cancel")}
                </button>
              </div>
            </form>
          ) : null}
        </section>
      ) : null}

      {canViewAssignments ? (
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {t("employees.assignment.history")}
          </h2>
          {assignmentsLoading ? (
            <p className="py-4 text-center text-sm text-slate-500">
              {t("common.loading")}
            </p>
          ) : assignments.length === 0 ? (
            <p className="py-4 text-center text-sm text-slate-500">
              {t("assignments.empty")}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-start text-slate-500">
                    <th className="py-2 text-start">
                      {t("employees.assignment.schedule")}
                    </th>
                    <th className="py-2 text-start">
                      {t("employees.assignment.shift")}
                    </th>
                    <th className="py-2 text-start">
                      {t("employees.assignment.effectiveFrom")}
                    </th>
                    <th className="py-2 text-start">
                      {t("employees.assignment.effectiveTo")}
                    </th>
                    <th className="py-2 text-start">
                      {t("common.actions")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {assignments.map((row) => (
                    <tr key={row.id} className="border-b border-slate-100">
                      <td className="py-2 font-mono text-xs">
                        #{row.schedule_id}
                      </td>
                      <td className="py-2 font-mono text-xs">
                        {row.shift_id ? `#${row.shift_id}` : "—"}
                      </td>
                      <td className="py-2">{row.effective_from}</td>
                      <td className="py-2">{row.effective_to ?? "—"}</td>
                      <td className="py-2">
                        <div className="flex gap-2">
                          {canUpdateAssignment ? (
                            <button
                              type="button"
                              onClick={() => startEdit(row)}
                              className="text-blue-600 hover:underline"
                            >
                              {t("common.edit")}
                            </button>
                          ) : null}
                          {canDeleteAssignment ? (
                            <button
                              type="button"
                              onClick={() => void remove(row)}
                              className="text-red-600 hover:underline"
                            >
                              {t("common.delete")}
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pagination meta={assignmentMeta} onPage={setAssignmentPage} />
            </div>
          )}
        </section>
      ) : null}

      {can("attendance.view") ? (
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {t("employees.attendance.recent")}
          </h2>
          {attendanceLoading ? (
            <p className="py-4 text-center text-sm text-slate-500">
              {t("common.loading")}
            </p>
          ) : attendance.length === 0 ? (
            <p className="py-4 text-center text-sm text-slate-500">
              {t("attendance.empty")}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-start text-slate-500">
                    <th className="py-2 text-start">
                      {t("attendance.date")}
                    </th>
                    <th className="py-2 text-start">
                      {t("attendance.checkInTime")}
                    </th>
                    <th className="py-2 text-start">
                      {t("attendance.checkOutTime")}
                    </th>
                    <th className="py-2 text-start">
                      {t("attendance.workedHours")}
                    </th>
                    <th className="py-2 text-start">
                      {t("attendance.status")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {attendance.map((row) => (
                    <tr key={row.id} className="border-b border-slate-100">
                      <td className="py-2">{row.work_date}</td>
                      <td className="py-2">{row.check_in.slice(11, 16)}</td>
                      <td className="py-2">
                        {row.check_out
                          ? row.check_out.slice(11, 16)
                          : "—"}
                      </td>
                      <td className="py-2">
                        {row.worked_minutes !== null
                          ? `${Math.floor(row.worked_minutes / 60)}h ${
                              row.worked_minutes % 60
                            }m`
                          : "—"}
                      </td>
                      <td className="py-2">
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                          {t(`attendance.status.${row.status}`)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {can("overtime.view") ? (
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {t("employees.overtime.recent")}
          </h2>
          {overtimeLoading ? (
            <p className="py-4 text-center text-sm text-slate-500">
              {t("common.loading")}
            </p>
          ) : overtime.length === 0 ? (
            <p className="py-4 text-center text-sm text-slate-500">
              {t("overtime.empty")}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-start text-slate-500">
                    <th className="py-2 text-start">
                      {t("overtime.workDate")}
                    </th>
                    <th className="py-2 text-start">
                      {t("overtime.requestedMinutes")}
                    </th>
                    <th className="py-2 text-start">
                      {t("overtime.approvedMinutes")}
                    </th>
                    <th className="py-2 text-start">
                      {t("overtime.status")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {overtime.map((row) => (
                    <tr key={row.id} className="border-b border-slate-100">
                      <td className="py-2">{row.work_date}</td>
                      <td className="py-2">{row.requested_minutes}</td>
                      <td className="py-2">{row.approved_minutes ?? "—"}</td>
                      <td className="py-2">
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                          {t(`overtime.status.${row.status}`)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}
    </div>
  );
}
