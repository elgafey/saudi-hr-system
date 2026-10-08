import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  approveLeaveRequest,
  cancelLeaveRequest,
  createLeaveRequest,
  deleteLeaveRequest,
  deleteLeaveRequestAttachment,
  downloadLeaveRequestAttachment,
  getEmployee,
  listEmployees,
  listLeaveRequests,
  listLeaveTypes,
  previewLeaveRequest,
  rejectLeaveRequest,
  submitLeaveRequest,
  updateLeaveRequest,
  uploadLeaveRequestAttachment,
  type LeaveRequest,
  type LeaveRequestPageParams,
  type LeaveRequestPreview,
  type LeaveType,
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
  draft: "leaveRequests.status.draft",
  submitted: "leaveRequests.status.submitted",
  approved: "leaveRequests.status.approved",
  rejected: "leaveRequests.status.rejected",
  cancelled: "leaveRequests.status.cancelled",
};

interface RequestFormState {
  employee_id: string;
  leave_type_id: string;
  start_date: string;
  end_date: string;
  start_time: string;
  end_time: string;
  reason: string;
}

const emptyForm: RequestFormState = {
  employee_id: "",
  leave_type_id: "",
  start_date: "",
  end_date: "",
  start_time: "",
  end_time: "",
  reason: "",
};

export default function LeaveRequestsPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;
  const ownEmployeeId = me?.user.employee_id;

  const [items, setItems] = useState<LeaveRequest[]>([]);
  const [meta, setMeta] = useState<{
    page: number;
    page_size: number;
    total: number;
  }>({ page: 1, page_size: pageSize, total: 0 });
  const [page, setPage] = useState(1);
  const [employeeId, setEmployeeId] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);

  const [types, setTypes] = useState<LeaveType[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<LeaveRequest | null>(null);
  const [form, setForm] = useState<RequestFormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState<LeaveRequestPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const loadTypes = useCallback(async () => {
    if (companyId === null) {
      return;
    }
    try {
      const res = await listLeaveTypes({
        company_id: companyId,
        page_size: 200,
      });
      setTypes(res.items);
    } catch {
      setTypes([]);
    }
  }, [companyId]);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: LeaveRequestPageParams = {
        company_id: companyId,
        page,
        page_size: pageSize,
        employee_id: employeeId ? Number(employeeId) : undefined,
        leave_type_id: typeFilter ? Number(typeFilter) : undefined,
        status: statusFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      };
      const res = await listLeaveRequests(params);
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
    employeeId,
    typeFilter,
    statusFilter,
    dateFrom,
    dateTo,
    t,
  ]);

  useEffect(() => {
    void loadTypes();
  }, [loadTypes]);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditing(null);
    setForm({
      ...emptyForm,
      employee_id: employeeId || (ownEmployeeId ? String(ownEmployeeId) : ""),
      leave_type_id: typeFilter,
    });
    setPreview(null);
    setFormOpen(true);
    setError(null);
  }

  function openEdit(row: LeaveRequest) {
    setEditing(row);
    setForm({
      employee_id: String(row.employee_id),
      leave_type_id: String(row.leave_type_id),
      start_date: row.start_date,
      end_date: row.end_date,
      start_time: row.start_time ? row.start_time.slice(0, 5) : "",
      end_time: row.end_time ? row.end_time.slice(0, 5) : "",
      reason: row.reason ?? "",
    });
    setPreview(null);
    setFormOpen(true);
    setError(null);
  }

  function validateForm(): boolean {
    if (form.start_date && form.end_date && form.end_date < form.start_date) {
      setError(t("leaveRequests.invalidRange"));
      return false;
    }
    if (Boolean(form.start_time) !== Boolean(form.end_time)) {
      setError(t("error.LEAVE_REQUEST_INVALID_TIMES"));
      return false;
    }
    return true;
  }

  async function runPreview() {
    if (!form.employee_id || !form.leave_type_id || !validateForm()) {
      return;
    }
    setPreviewing(true);
    setError(null);
    try {
      const result = await previewLeaveRequest({
        employee_id: Number(form.employee_id),
        leave_type_id: Number(form.leave_type_id),
        start_date: form.start_date,
        end_date: form.end_date,
        start_time: form.start_time || null,
        end_time: form.end_time || null,
        exclude_request_id: editing?.id ?? null,
      });
      setPreview(result);
    } catch (err) {
      setPreview(null);
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setPreviewing(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!validateForm()) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        leave_type_id: Number(form.leave_type_id),
        start_date: form.start_date,
        end_date: form.end_date,
        start_time: form.start_time || null,
        end_time: form.end_time || null,
        reason: form.reason.trim() || null,
      };
      if (editing) {
        await updateLeaveRequest(editing.id, payload);
      } else {
        await createLeaveRequest({
          ...payload,
          employee_id: Number(form.employee_id),
        });
      }
      setFormOpen(false);
      setEditing(null);
      setPreview(null);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSaving(false);
    }
  }

  async function runAction(
    id: number,
    action: () => Promise<LeaveRequest>,
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

  async function handleSubmit(row: LeaveRequest) {
    const ok = await runAction(
      row.id,
      () => submitLeaveRequest(row.id),
      t("common.failed"),
    );
    if (ok) {
      await load();
    }
  }

  async function handleApprove(row: LeaveRequest) {
    if (!window.confirm(t("leaveRequests.approve"))) {
      return;
    }
    const reason = window.prompt(t("leaveRequests.decisionReason")) ?? "";
    const ok = await runAction(
      row.id,
      () => approveLeaveRequest(row.id, { reason: reason.trim() || null }),
      t("common.failed"),
    );
    if (ok) {
      await load();
    }
  }

  async function handleReject(row: LeaveRequest) {
    const reason = window.prompt(t("leaveRequests.decisionReason")) ?? "";
    if (!reason.trim()) {
      setError(t("error.LEAVE_DECISION_REASON_REQUIRED"));
      return;
    }
    const ok = await runAction(
      row.id,
      () => rejectLeaveRequest(row.id, { reason: reason.trim() }),
      t("common.failed"),
    );
    if (ok) {
      await load();
    }
  }

  async function handleCancel(row: LeaveRequest) {
    if (!window.confirm(t("leaveRequests.cancel"))) {
      return;
    }
    const reason = window.prompt(t("leaveRequests.cancelReason")) ?? "";
    const ok = await runAction(
      row.id,
      () => cancelLeaveRequest(row.id, { reason: reason.trim() || null }),
      t("common.failed"),
    );
    if (ok) {
      await load();
    }
  }

  async function handleDelete(row: LeaveRequest) {
    if (!window.confirm(t("leaveRequests.deleteConfirm"))) {
      return;
    }
    setBusyId(row.id);
    setError(null);
    try {
      await deleteLeaveRequest(row.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusyId(null);
    }
  }

  async function handleUpload(row: LeaveRequest, file: File | undefined) {
    if (!file) {
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    setBusyId(row.id);
    setError(null);
    try {
      await uploadLeaveRequestAttachment(row.id, formData);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusyId(null);
    }
  }

  async function handleDownload(row: LeaveRequest) {
    setBusyId(row.id);
    setError(null);
    try {
      const { blob, filename } = await downloadLeaveRequestAttachment(row.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusyId(null);
    }
  }

  async function handleRemoveAttachment(row: LeaveRequest) {
    if (!window.confirm(t("leaveRequests.attachmentConfirm"))) {
      return;
    }
    const ok = await runAction(
      row.id,
      async () => {
        await deleteLeaveRequestAttachment(row.id);
        return row;
      },
      t("common.failed"),
    );
    if (ok) {
      await load();
    }
  }

  const canCreate = can("leave_request.create");
  const canUpdate = can("leave_request.update");
  const canSubmit = can("leave_request.submit");
  const canApprove = can("leave_request.approve");
  const canReject = can("leave_request.reject");
  const canCancel = can("leave_request.cancel");
  const canDelete = can("leave_request.delete");

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">
          {t("leaveRequests.heading")}
        </h1>
        {canCreate ? (
          <button
            type="button"
            onClick={openCreate}
            className={primaryButtonClass}
          >
            + {t("leaveRequests.new")}
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
              {t("leave.filters.dateFrom")}
            </span>
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
              className={inputClass}
            />
          </label>
          <label className="min-w-40 flex-1">
            <span className={labelClass}>{t("leave.filters.dateTo")}</span>
            <input
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
              className={inputClass}
            />
          </label>
          <label className="min-w-40 flex-1">
            <span className={labelClass}>
              {t("leave.filters.status")}
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
              <option value="draft">
                {t("leaveRequests.status.draft")}
              </option>
              <option value="submitted">
                {t("leaveRequests.status.submitted")}
              </option>
              <option value="approved">
                {t("leaveRequests.status.approved")}
              </option>
              <option value="rejected">
                {t("leaveRequests.status.rejected")}
              </option>
              <option value="cancelled">
                {t("leaveRequests.status.cancelled")}
              </option>
            </select>
          </label>
          <label className="min-w-40 flex-1">
            <span className={labelClass}>
              {t("leave.filters.leaveType")}
            </span>
            <select
              value={typeFilter}
              onChange={(event) => {
                setTypeFilter(event.target.value);
                setPage(1);
              }}
              className={inputClass}
            >
              <option value="">—</option>
              {types.map((type) => (
                <option key={type.id} value={String(type.id)}>
                  {type.name_en}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className={ghostButtonClass}>
            {t("common.search")}
          </button>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-64 flex-1">
            <SearchSelect
              label={t("leave.filters.employee")}
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
            {editing ? t("leaveRequests.edit") : t("leaveRequests.new")}
          </h2>
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("leave.employee")}</span>
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
              <span className={labelClass}>{t("leave.type")}</span>
              <select
                required
                value={form.leave_type_id}
                onChange={(event) =>
                  setForm({ ...form, leave_type_id: event.target.value })
                }
                className={inputClass}
              >
                <option value="">—</option>
                {types.map((type) => (
                  <option key={type.id} value={String(type.id)}>
                    {type.name_en}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className={labelClass}>{t("leave.startDate")}</span>
              <input
                required
                type="date"
                value={form.start_date}
                onChange={(event) =>
                  setForm({ ...form, start_date: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("leave.endDate")}</span>
              <input
                required
                type="date"
                value={form.end_date}
                onChange={(event) =>
                  setForm({ ...form, end_date: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("leave.startTime")}</span>
              <input
                type="time"
                value={form.start_time}
                onChange={(event) =>
                  setForm({ ...form, start_time: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("leave.endTime")}</span>
              <input
                type="time"
                value={form.end_time}
                onChange={(event) =>
                  setForm({ ...form, end_time: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label className="sm:col-span-2">
              <span className={labelClass}>{t("leave.reason")}</span>
              <input
                maxLength={2000}
                value={form.reason}
                onChange={(event) =>
                  setForm({ ...form, reason: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <div className="flex flex-wrap gap-2 sm:col-span-2">
              <button
                type="button"
                disabled={previewing}
                onClick={() => void runPreview()}
                className={ghostButtonClass}
              >
                {previewing ? t("common.loading") : t("leaveRequests.preview")}
              </button>
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
                  setPreview(null);
                }}
                className={ghostButtonClass}
              >
                {t("common.cancel")}
              </button>
            </div>
          </form>
          {preview ? (
            <div className="mt-3 rounded border border-slate-200 bg-slate-50 p-3 text-sm">
              <h3 className="mb-2 font-semibold">
                {t("leaveRequests.previewResult")}
              </h3>
              <div className="grid gap-1 sm:grid-cols-3">
                <span>
                  {t("leaveRequests.previewDays")}:{" "}
                  <strong>{Number(preview.days)}</strong>
                </span>
                <span>
                  {t("leaveRequests.previewMode")}:{" "}
                  {preview.day_counting_mode === "working_days"
                    ? t("dayCounting.working_days")
                    : t("dayCounting.calendar_days")}
                </span>
                <span>
                  {t("leaveRequests.previewBalance")}:{" "}
                  <strong>
                    {preview.balance
                      ? Number(preview.balance.remaining_days)
                      : "—"}
                  </strong>
                </span>
              </div>
              <div className="mt-2 space-y-1">
                {preview.would_be_negative ? (
                  <p className="text-amber-700">
                    {t("leaveRequests.previewNegative")}
                  </p>
                ) : null}
                {preview.has_open_attendance_conflict ? (
                  <p className="text-amber-700">
                    {t("leaveRequests.previewAttendanceConflict")}
                  </p>
                ) : null}
                {preview.has_approved_overtime_conflict ? (
                  <p className="text-amber-700">
                    {t("leaveRequests.previewOvertimeConflict")}
                  </p>
                ) : null}
              </div>
            </div>
          ) : null}
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
            {employeeId || typeFilter || statusFilter || dateFrom || dateTo
              ? t("common.empty")
              : t("leaveRequests.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">
                    {t("leave.employee")}
                  </th>
                  <th className="py-2 text-start">{t("leave.type")}</th>
                  <th className="py-2 text-start">{t("leave.period")}</th>
                  <th className="py-2 text-start">{t("leave.days")}</th>
                  <th className="py-2 text-start">{t("leave.status")}</th>
                  <th className="py-2 text-start">
                    {t("leaveRequests.attachment")}
                  </th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => {
                  const isDraft = row.status === "draft";
                  const isSubmitted = row.status === "submitted";
                  const isApproved = row.status === "approved";
                  const cancellable = isDraft || isSubmitted || isApproved;
                  const busy = busyId === row.id;
                  const typeName =
                    types.find((type) => type.id === row.leave_type_id)
                      ?.name_en ?? `#${row.leave_type_id}`;
                  const canAttach =
                    (isDraft || isSubmitted) &&
                    (canUpdate || canCreate);
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
                      <td className="py-2">{typeName}</td>
                      <td className="py-2">
                        {row.start_date} → {row.end_date}
                      </td>
                      <td className="py-2">{Number(row.days)}</td>
                      <td className="py-2">
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                          {t(STATUS_LABELS[row.status] ?? row.status)}
                        </span>
                      </td>
                      <td className="py-2">
                        {row.attachment_name ? (
                          <div className="flex flex-wrap gap-2 text-xs">
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleDownload(row)}
                              className="text-blue-600 hover:underline disabled:opacity-50"
                            >
                              {row.attachment_name}
                            </button>
                            {canAttach ? (
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() =>
                                  void handleRemoveAttachment(row)
                                }
                                className="text-red-600 hover:underline disabled:opacity-50"
                              >
                                {t("leaveRequests.attachmentDelete")}
                              </button>
                            ) : null}
                          </div>
                        ) : canAttach ? (
                          <label className="cursor-pointer text-xs text-blue-600 hover:underline">
                            {t("leaveRequests.attachmentUpload")}
                            <input
                              type="file"
                              className="hidden"
                              onChange={(event) =>
                                void handleUpload(row, event.target.files?.[0])
                              }
                            />
                          </label>
                        ) : (
                          "—"
                        )}
                      </td>
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
                              {t("leaveRequests.submit")}
                            </button>
                          ) : null}
                          {canApprove && isSubmitted ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleApprove(row)}
                              className="text-green-700 hover:underline disabled:opacity-50"
                            >
                              {t("leaveRequests.approve")}
                            </button>
                          ) : null}
                          {canReject && isSubmitted ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleReject(row)}
                              className="text-red-600 hover:underline disabled:opacity-50"
                            >
                              {t("leaveRequests.reject")}
                            </button>
                          ) : null}
                          {canCancel && cancellable ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleCancel(row)}
                              className="text-slate-500 hover:underline disabled:opacity-50"
                            >
                              {t("leaveRequests.cancel")}
                            </button>
                          ) : null}
                          {canDelete && isDraft ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleDelete(row)}
                              className="text-red-600 hover:underline disabled:opacity-50"
                            >
                              {t("common.delete")}
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
