import {
  Fragment,
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  checkInAttendance,
  checkOutAttendance,
  createAttendance,
  deleteAttendance,
  listAttendance,
  listEmployees,
  getEmployee,
  listDepartments,
  getDepartment,
  listBranches,
  listWorkSchedules,
  getWorkSchedule,
  listShifts,
  getShift,
  type AttendanceRecord,
} from "../api";
import Pagination from "../components/Pagination";
import SearchSelect from "../components/SearchSelect";
import {
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../ui";

const pageSize = 20;

const STATUS_LABELS = {
  open: "attendance.status.open",
  completed: "attendance.status.completed",
  missing_checkout: "attendance.status.missing_checkout",
};

function formatTime(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    return date.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    return dateStr;
  }
}

function formatMinutes(min: number | null): string {
  if (min === null || min === undefined) {
    return "—";
  }
  const hours = Math.floor(min / 60);
  const minutes = min % 60;
  return `${hours}h ${minutes}m`;
}

interface CreateFormState {
  employee_id: string;
  date: string;
  check_in: string;
  check_out: string;
  notes: string;
}

const emptyCreateForm: CreateFormState = {
  employee_id: "",
  date: "",
  check_in: "09:00",
  check_out: "",
  notes: "",
};

export default function AttendancePage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<AttendanceRecord[]>([]);
  const [meta, setMeta] = useState<{ page: number; page_size: number; total: number }>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [branchId, setBranchId] = useState("");
  const [scheduleId, setScheduleId] = useState("");
  const [shiftId, setShiftId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [viewingId, setViewingId] = useState<number | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<CreateFormState>(emptyCreateForm);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await listAttendance({
        company_id: companyId,
        page,
        page_size: pageSize,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        status: statusFilter || undefined,
        employee_id: employeeId ? Number(employeeId) : undefined,
        department_id: departmentId ? Number(departmentId) : undefined,
        branch_id: branchId ? Number(branchId) : undefined,
        schedule_id: scheduleId ? Number(scheduleId) : undefined,
        shift_id: shiftId ? Number(shiftId) : undefined,
      });
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [
    companyId,
    page,
    dateFrom,
    dateTo,
    statusFilter,
    employeeId,
    departmentId,
    branchId,
    scheduleId,
    shiftId,
    t,
  ]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCheckIn() {
    if (!employeeId) {
      setError(t("attendance.filters.employee") + " " + t("common.error"));
      return;
    }
    try {
      await checkInAttendance({ employee_id: Number(employeeId), source: "api" });
      await load();
    } catch (err) {
      setError(errorMessage(err, t("attendance.checkInFailed"), t));
    }
  }

  async function handleCheckOut() {
    if (!employeeId) {
      setError(t("attendance.filters.employee") + " " + t("common.error"));
      return;
    }
    try {
      await checkOutAttendance({ employee_id: Number(employeeId) });
      await load();
    } catch (err) {
      setError(errorMessage(err, t("attendance.checkOutFailed"), t));
    }
  }

  async function handleCreateAttendance(event: FormEvent) {
    event.preventDefault();
    if (!form.employee_id || !form.date || !form.check_in) {
      setError(t("common.error"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      let checkOut: string | null = null;
      if (form.check_out) {
        if (form.check_out > form.check_in) {
          checkOut = `${form.date}T${form.check_out}:00`;
        } else {
          const next = new Date(`${form.date}T12:00:00`);
          next.setDate(next.getDate() + 1);
          const iso = `${next.getFullYear()}-${String(
            next.getMonth() + 1,
          ).padStart(2, "0")}-${String(next.getDate()).padStart(2, "0")}`;
          checkOut = `${iso}T${form.check_out}:00`;
        }
      }
      await createAttendance({
        employee_id: Number(form.employee_id),
        check_in: `${form.date}T${form.check_in}:00`,
        check_out: checkOut,
        source: "manual",
        notes: form.notes.trim() || null,
      });
      setFormOpen(false);
      setForm(emptyCreateForm);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(record: AttendanceRecord) {
    if (!window.confirm(t("attendance.deleteConfirm"))) {
      return;
    }
    const reason = window.prompt(t("attendance.deleteReasonRequired"));
    if (reason === null) {
      return;
    }
    if (!reason.trim() && record.status !== "open") {
      setError(t("attendance.deleteReasonRequired"));
      return;
    }
    try {
      await deleteAttendance(record.id, reason.trim() || null);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  const canCreate = can("attendance.create");
  const canDelete = can("attendance.delete");

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{t("attendance.heading")}</h1>
        <div className="flex gap-2">
          {canCreate ? (
            <button
              type="button"
              onClick={() => setFormOpen((open) => !open)}
              className={primaryButtonClass}
            >
              + {t("attendance.new")}
            </button>
          ) : null}
          {canCreate ? (
            <button
              type="button"
              onClick={handleCheckIn}
              className={ghostButtonClass}
            >
              {t("attendance.checkIn")}
            </button>
          ) : null}
          {canCreate ? (
            <button
              type="button"
              onClick={handleCheckOut}
              className={ghostButtonClass}
            >
              {t("attendance.checkOut")}
            </button>
          ) : null}
        </div>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setPage(1);
        }}
        className="space-y-3"
      >
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-40 flex-1">
            <span className={labelClass}>{t("attendance.filters.dateFrom")}</span>
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
              className={inputClass}
            />
          </label>
          <label className="min-w-40 flex-1">
            <span className={labelClass}>{t("attendance.filters.dateTo")}</span>
            <input
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
              className={inputClass}
            />
          </label>
          <label className="min-w-40 flex-1">
            <span className={labelClass}>{t("attendance.filters.status")}</span>
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setPage(1);
              }}
              className={inputClass}
            >
              <option value="">—</option>
              <option value="open">{t("attendance.status.open")}</option>
              <option value="completed">{t("attendance.status.completed")}</option>
              <option value="missing_checkout">
                {t("attendance.status.missing_checkout")}
              </option>
            </select>
          </label>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <SearchSelect
            label={t("attendance.filters.employee")}
            value={employeeId}
            onChange={(val) => setEmployeeId(val)}
            load={async (search) => {
              if (!companyId) return [];
              const res = await listEmployees({
                company_id: companyId,
                search: search || undefined,
                limit: 20,
              });
              return res.items.map((e) => ({
                id: e.id,
                label: `${e.employee_number} — ${e.first_name_en} ${e.last_name_en}`,
              }));
            }}
            resolve={async (id) => {
              const emp = await getEmployee(id);
              return `${emp.employee_number} — ${emp.first_name_en} ${emp.last_name_en}`;
            }}
            placeholder={t("common.search")}
          />
          <label className="min-w-40 flex-1">
            <span className={labelClass}>{t("attendance.filters.department")}</span>
            <SearchSelect
              label=""
              value={departmentId}
              onChange={(val) => setDepartmentId(val)}
              load={async (search) => {
                if (!companyId) return [];
                const res = await listDepartments({
                  company_id: companyId,
                  search: search || undefined,
                  limit: 20,
                });
                return res.items.map((d) => ({
                  id: d.id,
                  label: d.name_en,
                }));
              }}
              resolve={async (id) => {
                const dep = await getDepartment(id);
                return dep.name_en;
              }}
            />
          </label>
          <label className="min-w-40 flex-1">
            <span className={labelClass}>{t("attendance.filters.branch")}</span>
            <SearchSelect
              label=""
              value={branchId}
              onChange={(val) => setBranchId(val)}
              load={async (search) => {
                if (!companyId) return [];
                const res = await listBranches(companyId);
                return res
                  .filter((b) =>
                    b.name.toLowerCase().includes(search.toLowerCase()),
                  )
                  .map((b) => ({
                    id: b.id,
                    label: `${b.code} — ${b.name}`,
                  }));
              }}
              resolve={async (id) => {
                if (!companyId) return `#${id}`;
                const res = await listBranches(companyId);
                const found = res.find((b) => b.id === id);
                return found ? `${found.code} — ${found.name}` : `#${id}`;
              }}
            />
          </label>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-40 flex-1">
            <span className={labelClass}>{t("attendance.filters.schedule")}</span>
            <SearchSelect
              label=""
              value={scheduleId}
              onChange={(val) => setScheduleId(val)}
              load={async (search) => {
                if (!companyId) return [];
                const res = await listWorkSchedules({
                  company_id: companyId,
                  search: search || undefined,
                  limit: 20,
                });
                return res.items.map((s) => ({
                  id: s.id,
                  label: `${s.code} — ${s.name_en}`,
                }));
              }}
              resolve={async (id) => {
                const sched = await getWorkSchedule(id);
                return `${sched.code} — ${sched.name_en}`;
              }}
            />
          </label>
          <label className="min-w-40 flex-1">
            <span className={labelClass}>{t("attendance.filters.shift")}</span>
            <SearchSelect
              label=""
              value={shiftId}
              onChange={(val) => setShiftId(val)}
              load={async (search) => {
                if (!companyId) return [];
                const res = await listShifts({
                  company_id: companyId,
                  search: search || undefined,
                  limit: 20,
                });
                return res.items.map((s) => ({
                  id: s.id,
                  label: `${s.code} — ${s.name_en}`,
                }));
              }}
              resolve={async (id) => {
                const shift = await getShift(id);
                return `${shift.code} — ${shift.name_en}`;
              }}
            />
          </label>
          <button type="submit" className={ghostButtonClass}>
            {t("common.search")}
          </button>
        </div>
      </form>

      {formOpen ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {t("attendance.new")}
          </h2>
          <form onSubmit={handleCreateAttendance} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>
                {t("attendance.filters.employee")}
              </span>
              <SearchSelect
                label=""
                value={form.employee_id}
                onChange={(val) => setForm({ ...form, employee_id: val })}
                load={async (search) => {
                  if (!companyId) return [];
                  const res = await listEmployees({
                    company_id: companyId,
                    search: search || undefined,
                    limit: 20,
                  });
                  return res.items.map((e) => ({
                    id: e.id,
                    label: `${e.employee_number} — ${e.first_name_en} ${e.last_name_en}`,
                  }));
                }}
                resolve={async (id) => {
                  const emp = await getEmployee(id);
                  return `${emp.employee_number} — ${emp.first_name_en} ${emp.last_name_en}`;
                }}
              />
            </label>
            <label>
              <span className={labelClass}>{t("attendance.date")}</span>
              <input
                required
                type="date"
                value={form.date}
                onChange={(event) =>
                  setForm({ ...form, date: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("attendance.checkInLabel")}
              </span>
              <input
                required
                type="time"
                value={form.check_in}
                onChange={(event) =>
                  setForm({ ...form, check_in: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("attendance.checkOutLabel")}
              </span>
              <input
                type="time"
                value={form.check_out}
                onChange={(event) =>
                  setForm({ ...form, check_out: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label className="sm:col-span-2">
              <span className={labelClass}>{t("attendance.notes")}</span>
              <input
                maxLength={500}
                value={form.notes}
                onChange={(event) =>
                  setForm({ ...form, notes: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <div className="flex gap-2 sm:col-span-2">
              <button
                type="submit"
                disabled={saving}
                className={primaryButtonClass}
              >
                {saving ? t("common.saving") : t("common.save")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setFormOpen(false);
                  setForm(emptyCreateForm);
                }}
                className={ghostButtonClass}
              >
                {t("common.cancel")}
              </button>
            </div>
          </form>
        </section>
      ) : null}

      {error ? <p className={errorTextClass}>{error}</p> : null}

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        {loading ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {t("common.loading")}
          </p>
        ) : items.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {dateFrom || dateTo || statusFilter || employeeId
              ? t("common.empty")
              : t("attendance.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("attendance.date")}</th>
                  <th className="py-2 text-start">{t("attendance.filters.employee")}</th>
                  <th className="py-2 text-start">{t("attendance.checkInTime")}</th>
                  <th className="py-2 text-start">{t("attendance.checkOutTime")}</th>
                  <th className="py-2 text-start">{t("attendance.scheduledHours")}</th>
                  <th className="py-2 text-start">{t("attendance.workedHours")}</th>
                  <th className="py-2 text-start">{t("attendance.breakMinutes")}</th>
                  <th className="py-2 text-start">{t("attendance.lateMinutes")}</th>
                  <th className="py-2 text-start">{t("attendance.earlyLeaveMinutes")}</th>
                  <th className="py-2 text-start">{t("attendance.overtimeCandidateMinutes")}</th>
                  <th className="py-2 text-start">{t("attendance.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <Fragment key={row.id}>
                    <tr className="border-b border-slate-100">
                      <td className="py-2">{row.work_date}</td>
                      <td className="py-2 font-mono text-xs">
                        {row.employee_id}
                      </td>
                      <td className="py-2">{formatTime(row.check_in)}</td>
                      <td className="py-2">
                        {row.check_out ? formatTime(row.check_out) : "—"}
                      </td>
                      <td className="py-2">{formatMinutes(row.scheduled_minutes)}</td>
                      <td className="py-2">{formatMinutes(row.worked_minutes)}</td>
                      <td className="py-2">{row.break_minutes ?? "—"}</td>
                      <td className="py-2">{row.late_minutes ?? "—"}</td>
                      <td className="py-2">{row.early_leave_minutes ?? "—"}</td>
                      <td className="py-2">
                        {row.overtime_candidate_minutes ?? "—"}
                      </td>
                      <td className="py-2">
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                          {t(
                            STATUS_LABELS[row.status as keyof typeof STATUS_LABELS] ??
                              row.status,
                          )}
                        </span>
                      </td>
                      <td className="py-2">
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() =>
                              setViewingId(viewingId === row.id ? null : row.id)
                            }
                            className="text-blue-600 hover:underline"
                          >
                            {t("attendance.view")}
                          </button>
                          {canDelete ? (
                            <button
                              type="button"
                              onClick={() => void handleDelete(row)}
                              className="text-red-600 hover:underline"
                            >
                              {t("common.delete")}
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                    {viewingId === row.id ? (
                      <tr className="border-b border-slate-100 bg-slate-50">
                        <td colSpan={12} className="py-3">
                          <dl className="flex flex-wrap gap-x-8 gap-y-1 text-xs">
                            <div>
                              <dt className="text-slate-500">
                                {t("attendance.source")}
                              </dt>
                              <dd>
                                {t(`attendance.source.${row.source}`)}
                              </dd>
                            </div>
                            <div>
                              <dt className="text-slate-500">
                                {t("attendance.notes")}
                              </dt>
                              <dd>{row.notes ?? "—"}</dd>
                            </div>
                            <div>
                              <dt className="text-slate-500">
                                {t("attendance.correctionReason")}
                              </dt>
                              <dd>{row.correction_reason ?? "—"}</dd>
                            </div>
                            <div>
                              <dt className="text-slate-500">
                                {t("attendance.filters.schedule")}
                              </dt>
                              <dd>
                                {row.schedule_id ? `#${row.schedule_id}` : "—"}
                              </dd>
                            </div>
                            <div>
                              <dt className="text-slate-500">
                                {t("attendance.filters.shift")}
                              </dt>
                              <dd>
                                {row.shift_id ? `#${row.shift_id}` : "—"}
                              </dd>
                            </div>
                          </dl>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                ))}
              </tbody>
            </table>
            <Pagination meta={meta} onPage={setPage} />
          </div>
        )}
      </section>
    </div>
  );
}