import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  approveOvertime,
  cancelOvertime,
  correctOvertime,
  createOvertime,
  getEmployee,
  listEmployees,
  listOvertime,
  rejectOvertime,
  submitOvertime,
  updateOvertime,
  type OvertimeRecord,
  type OvertimePageParams,
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

const STATUS_LABELS: Record<string, string> = {
  draft: "overtime.status.draft",
  submitted: "overtime.status.submitted",
  approved: "overtime.status.approved",
  rejected: "overtime.status.rejected",
  cancelled: "overtime.status.cancelled",
};

interface OvertimeFormState {
  employee_id: string;
  work_date: string;
  requested_minutes: string;
  reason: string;
  notes: string;
}

const emptyForm: OvertimeFormState = {
  employee_id: "",
  work_date: "",
  requested_minutes: "60",
  reason: "",
  notes: "",
};

export default function OvertimePage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<OvertimeRecord[]>([]);
  const [meta, setMeta] = useState<{
    page: number;
    page_size: number;
    total: number;
  }>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<OvertimeRecord | null>(null);
  const [form, setForm] = useState<OvertimeFormState>(emptyForm);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: OvertimePageParams = {
        company_id: companyId,
        page,
        page_size: pageSize,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        status: statusFilter || undefined,
        employee_id: employeeId ? Number(employeeId) : undefined,
      };
      const res = await listOvertime(params);
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
    t,
  ]);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditing(null);
    setForm({
      ...emptyForm,
      employee_id: employeeId,
    });
    setFormOpen(true);
    setError(null);
  }

  function openEdit(row: OvertimeRecord) {
    setEditing(row);
    setForm({
      employee_id: String(row.employee_id),
      work_date: row.work_date,
      requested_minutes: String(row.requested_minutes),
      reason: row.reason ?? "",
      notes: row.notes ?? "",
    });
    setFormOpen(true);
    setError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (companyId === null) {
      return;
    }
    const minutes = Number(form.requested_minutes);
    if (!Number.isFinite(minutes) || minutes < 1 || minutes > 1440) {
      setError(t("overtime.invalidMinutes"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await updateOvertime(editing.id, {
          work_date: form.work_date,
          requested_minutes: minutes,
          reason: form.reason.trim() || null,
          notes: form.notes.trim() || null,
        });
      } else {
        await createOvertime({
          employee_id: Number(form.employee_id),
          work_date: form.work_date,
          requested_minutes: minutes,
          reason: form.reason.trim() || null,
          notes: form.notes.trim() || null,
        });
      }
      setFormOpen(false);
      setEditing(null);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSaving(false);
    }
  }

  async function runAction(
    id: number,
    action: () => Promise<OvertimeRecord>,
    fallback: string,
  ): Promise<boolean> {
    setBusyId(id);
    setError(null);
    try {
      await action();
      return true;
    } catch (err) {
      setError(errorMessage(err, fallback, t));
      return false;
    } finally {
      setBusyId(null);
    }
  }

  async function handleSubmit(row: OvertimeRecord) {
    const ok = await runAction(
      row.id,
      () => submitOvertime(row.id),
      t("common.failed"),
    );
    if (ok) {
      await load();
    }
  }

  async function handleApprove(row: OvertimeRecord) {
    const minutesText = window.prompt(
      t("overtime.approvedMinutesLabel"),
      String(row.requested_minutes),
    );
    if (minutesText === null) {
      return;
    }
    const minutes = Number(minutesText);
    if (!Number.isFinite(minutes) || minutes < 1 || minutes > 1440) {
      setError(t("overtime.invalidMinutes"));
      return;
    }
    if (minutes > row.requested_minutes) {
      setError(t("overtime.approvedExceedsRequested"));
      return;
    }
    const reason = window.prompt(t("overtime.decisionReason")) ?? "";
    const ok = await runAction(
      row.id,
      () =>
        approveOvertime(row.id, {
          approved_minutes: minutes,
          reason: reason.trim() || null,
        }),
      t("common.failed"),
    );
    if (ok) {
      await load();
    }
  }

  async function handleReject(row: OvertimeRecord) {
    if (!window.confirm(t("overtime.reject"))) {
      return;
    }
    const reason = window.prompt(t("overtime.decisionReason")) ?? "";
    const ok = await runAction(
      row.id,
      () => rejectOvertime(row.id, { reason: reason.trim() || null }),
      t("common.failed"),
    );
    if (ok) {
      await load();
    }
  }

  async function handleCancel(row: OvertimeRecord) {
    if (!window.confirm(t("overtime.cancel"))) {
      return;
    }
    const reason = window.prompt(t("overtime.decisionReason")) ?? "";
    const ok = await runAction(
      row.id,
      () => cancelOvertime(row.id, { reason: reason.trim() || null }),
      t("common.failed"),
    );
    if (ok) {
      await load();
    }
  }

  async function handleCorrect(row: OvertimeRecord) {
    const minutesText = window.prompt(
      t("overtime.approvedMinutesLabel"),
      String(row.approved_minutes ?? row.requested_minutes),
    );
    if (minutesText === null) {
      return;
    }
    const minutes = Number(minutesText);
    if (!Number.isFinite(minutes) || minutes < 1 || minutes > 1440) {
      setError(t("overtime.invalidMinutes"));
      return;
    }
    if (minutes > row.requested_minutes) {
      setError(t("overtime.approvedExceedsRequested"));
      return;
    }
    const reason = window.prompt(t("overtime.correctionReasonRequired"));
    if (reason === null || !reason.trim()) {
      setError(t("overtime.correctionReasonRequired"));
      return;
    }
    const ok = await runAction(
      row.id,
      () =>
        correctOvertime(row.id, {
          approved_minutes: minutes,
          reason: reason.trim(),
        }),
      t("common.failed"),
    );
    if (ok) {
      await load();
    }
  }

  const canCreate = can("overtime.create");
  const canUpdate = can("overtime.update");
  const canSubmit = can("overtime.submit");
  const canApprove = can("overtime.approve");
  const canReject = can("overtime.reject");
  const canCancel = can("overtime.cancel");
  const canCorrect = can("overtime.approve");

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{t("overtime.heading")}</h1>
        {canCreate ? (
          <button
            type="button"
            onClick={openCreate}
            className={primaryButtonClass}
          >
            + {t("overtime.new")}
          </button>
        ) : null}
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
            <span className={labelClass}>
              {t("overtime.filters.dateFrom")}
            </span>
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
              className={inputClass}
            />
          </label>
          <label className="min-w-40 flex-1">
            <span className={labelClass}>{t("overtime.filters.dateTo")}</span>
            <input
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
              className={inputClass}
            />
          </label>
          <label className="min-w-40 flex-1">
            <span className={labelClass}>
              {t("overtime.filters.status")}
            </span>
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setPage(1);
              }}
              className={inputClass}
            >
              <option value="">—</option>
              <option value="draft">{t("overtime.status.draft")}</option>
              <option value="submitted">
                {t("overtime.status.submitted")}
              </option>
              <option value="approved">
                {t("overtime.status.approved")}
              </option>
              <option value="rejected">
                {t("overtime.status.rejected")}
              </option>
              <option value="cancelled">
                {t("overtime.status.cancelled")}
              </option>
            </select>
          </label>
          <button type="submit" className={ghostButtonClass}>
            {t("common.search")}
          </button>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-64 flex-1">
            <SearchSelect
              label={t("overtime.filters.employee")}
              value={employeeId}
              onChange={(val) => {
                setEmployeeId(val);
                setPage(1);
              }}
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
          </div>
        </div>
      </form>

      {formOpen ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {editing ? t("overtime.edit") : t("overtime.new")}
          </h2>
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>
                {t("overtime.filters.employee")}
              </span>
              <SearchSelect
                label=""
                value={form.employee_id}
                onChange={(val) =>
                  setForm({ ...form, employee_id: val })
                }
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
              <span className={labelClass}>{t("overtime.workDate")}</span>
              <input
                required
                type="date"
                value={form.work_date}
                onChange={(event) =>
                  setForm({ ...form, work_date: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("overtime.requestedMinutes")}
              </span>
              <input
                required
                type="number"
                min={1}
                max={1440}
                value={form.requested_minutes}
                onChange={(event) =>
                  setForm({
                    ...form,
                    requested_minutes: event.target.value,
                  })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("overtime.reason")}</span>
              <input
                maxLength={500}
                value={form.reason}
                onChange={(event) =>
                  setForm({ ...form, reason: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label className="sm:col-span-2">
              <span className={labelClass}>{t("common.description")}</span>
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
                  setEditing(null);
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
              : t("overtime.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">
                    {t("overtime.filters.employee")}
                  </th>
                  <th className="py-2 text-start">
                    {t("overtime.workDate")}
                  </th>
                  <th className="py-2 text-start">
                    {t("overtime.requestedMinutes")}
                  </th>
                  <th className="py-2 text-start">
                    {t("overtime.approvedMinutes")}
                  </th>
                  <th className="py-2 text-start">{t("overtime.status")}</th>
                  <th className="py-2 text-start">{t("overtime.reason")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => {
                  const isApproved = row.status === "approved";
                  const isDraft = row.status === "draft";
                  const isSubmitted = row.status === "submitted";
                  const busy = busyId === row.id;
                  return (
                    <tr
                      key={row.id}
                      className={`border-b border-slate-100 ${
                        isApproved ? "bg-slate-50" : ""
                      }`}
                    >
                      <td className="py-2 font-mono text-xs">
                        #{row.employee_id}
                      </td>
                      <td className="py-2">{row.work_date}</td>
                      <td className="py-2">{row.requested_minutes}</td>
                      <td className="py-2">{row.approved_minutes ?? "—"}</td>
                      <td className="py-2">
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                          {t(STATUS_LABELS[row.status] ?? row.status)}
                        </span>
                      </td>
                      <td className="py-2">{row.reason ?? "—"}</td>
                      <td className="py-2">
                        <div className="flex flex-wrap gap-2">
                          {canUpdate && isDraft ? (
                            <button
                              type="button"
                              onClick={() => openEdit(row)}
                              className="text-blue-600 hover:underline"
                            >
                              {t("common.edit")}
                            </button>
                          ) : null}
                          {canSubmit && isDraft ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleSubmit(row)}
                              className="text-blue-600 hover:underline disabled:opacity-50"
                            >
                              {t("overtime.submit")}
                            </button>
                          ) : null}
                          {canApprove && isSubmitted ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleApprove(row)}
                              className="text-green-700 hover:underline disabled:opacity-50"
                            >
                              {t("overtime.approve")}
                            </button>
                          ) : null}
                          {canReject && isSubmitted ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleReject(row)}
                              className="text-red-600 hover:underline disabled:opacity-50"
                            >
                              {t("overtime.reject")}
                            </button>
                          ) : null}
                          {canCancel &&
                          (isDraft || isSubmitted || isApproved) ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleCancel(row)}
                              className="text-slate-500 hover:underline disabled:opacity-50"
                            >
                              {t("overtime.cancel")}
                            </button>
                          ) : null}
                          {canCorrect && isApproved ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleCorrect(row)}
                              className="text-amber-700 hover:underline disabled:opacity-50"
                            >
                              {t("overtime.correct")}
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <Pagination meta={meta} onPage={setPage} />
          </div>
        )}
      </section>
    </div>
  );
}
