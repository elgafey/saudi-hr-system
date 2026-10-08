import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  approveLeaveAllocation,
  carryForwardAllocations,
  createLeaveAllocation,
  deleteLeaveAllocation,
  generateLeaveAllocations,
  getEmployee,
  listEmployees,
  listLeaveAllocations,
  listLeaveTypes,
  rejectLeaveAllocation,
  updateLeaveAllocation,
  type LeaveAllocation,
  type LeaveAllocationPageParams,
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
  submitted: "leaveAllocations.status.submitted",
  approved: "leaveAllocations.status.approved",
  rejected: "leaveAllocations.status.rejected",
  revoked: "leaveAllocations.status.revoked",
};

const SOURCE_LABELS: Record<string, string> = {
  manual: "leaveAllocations.source.manual",
  generate: "leaveAllocations.source.generate",
  carry_forward: "leaveAllocations.source.carry_forward",
  statutory: "leaveAllocations.source.statutory",
};

interface AllocationFormState {
  employee_id: string;
  leave_type_id: string;
  period_start: string;
  period_end: string;
  allocated_days: string;
  reason: string;
}

const emptyAllocationForm: AllocationFormState = {
  employee_id: "",
  leave_type_id: "",
  period_start: "",
  period_end: "",
  allocated_days: "30",
  reason: "",
};

interface GenerateFormState {
  leave_type_id: string;
  period_start: string;
  period_end: string;
  allocated_days: string;
}

const emptyGenerateForm: GenerateFormState = {
  leave_type_id: "",
  period_start: "",
  period_end: "",
  allocated_days: "",
};

interface CarryFormState {
  period_start: string;
  period_end: string;
}

const emptyCarryForm: CarryFormState = {
  period_start: "",
  period_end: "",
};

export default function LeaveAllocationsPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<LeaveAllocation[]>([]);
  const [meta, setMeta] = useState<{
    page: number;
    page_size: number;
    total: number;
  }>({ page: 1, page_size: pageSize, total: 0 });
  const [page, setPage] = useState(1);
  const [employeeId, setEmployeeId] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);

  const [types, setTypes] = useState<LeaveType[]>([]);
  const [mode, setMode] = useState<"none" | "create" | "generate" | "carry">(
    "none",
  );
  const [form, setForm] = useState<AllocationFormState>(emptyAllocationForm);
  const [editing, setEditing] = useState<LeaveAllocation | null>(null);
  const [generateForm, setGenerateForm] =
    useState<GenerateFormState>(emptyGenerateForm);
  const [carryForm, setCarryForm] = useState<CarryFormState>(emptyCarryForm);
  const [saving, setSaving] = useState(false);

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
      const params: LeaveAllocationPageParams = {
        company_id: companyId,
        page,
        page_size: pageSize,
        employee_id: employeeId ? Number(employeeId) : undefined,
        leave_type_id: typeFilter ? Number(typeFilter) : undefined,
        status: statusFilter || undefined,
      };
      const res = await listLeaveAllocations(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [companyId, page, employeeId, typeFilter, statusFilter, t]);

  useEffect(() => {
    void loadTypes();
  }, [loadTypes]);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditing(null);
    setForm({
      ...emptyAllocationForm,
      employee_id: employeeId,
      leave_type_id: typeFilter,
    });
    setMode("create");
    setError(null);
    setNotice(null);
  }

  function openEdit(row: LeaveAllocation) {
    setEditing(row);
    setForm({
      employee_id: String(row.employee_id),
      leave_type_id: String(row.leave_type_id),
      period_start: row.period_start,
      period_end: row.period_end,
      allocated_days: String(row.allocated_days),
      reason: row.reason ?? "",
    });
    setMode("create");
    setError(null);
    setNotice(null);
  }

  async function submitCreate(event: FormEvent) {
    event.preventDefault();
    if (form.period_start && form.period_end && form.period_end < form.period_start) {
      setError(t("error.LEAVE_ALLOCATION_INVALID_DAYS"));
      return;
    }
    const days = Number(form.allocated_days);
    if (!Number.isFinite(days) || days <= 0) {
      setError(t("error.LEAVE_ALLOCATION_INVALID_DAYS"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await updateLeaveAllocation(editing.id, {
          period_start: form.period_start,
          period_end: form.period_end,
          allocated_days: days,
          reason: form.reason.trim() || null,
        });
      } else {
        await createLeaveAllocation({
          employee_id: Number(form.employee_id),
          leave_type_id: Number(form.leave_type_id),
          period_start: form.period_start,
          period_end: form.period_end,
          allocated_days: days,
          reason: form.reason.trim() || null,
        });
      }
      setMode("none");
      setEditing(null);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSaving(false);
    }
  }

  async function submitGenerate(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const days = generateForm.allocated_days
        ? Number(generateForm.allocated_days)
        : null;
      const rows = await generateLeaveAllocations({
        leave_type_id: Number(generateForm.leave_type_id),
        period_start: generateForm.period_start,
        period_end: generateForm.period_end,
        allocated_days: days,
      });
      setNotice(`${t("leaveAllocations.generateDone")} (${rows.length})`);
      setMode("none");
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSaving(false);
    }
  }

  async function submitCarry(event: FormEvent) {
    event.preventDefault();
    if (companyId === null) {
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const rows = await carryForwardAllocations({
        company_id: companyId,
        period_start: carryForm.period_start,
        period_end: carryForm.period_end,
      });
      setNotice(`${t("leaveAllocations.carryForwardDone")} (${rows.length})`);
      setMode("none");
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSaving(false);
    }
  }

  async function runAction(
    id: number,
    action: () => Promise<unknown>,
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

  async function handleApprove(row: LeaveAllocation) {
    if (!window.confirm(t("leaveAllocations.approve"))) {
      return;
    }
    const reason = window.prompt(t("leaveAllocations.decisionReason")) ?? "";
    const ok = await runAction(
      row.id,
      () => approveLeaveAllocation(row.id, { reason: reason.trim() || null }),
      t("common.failed"),
    );
    if (ok) {
      await load();
    }
  }

  async function handleReject(row: LeaveAllocation) {
    const reason = window.prompt(t("leaveAllocations.decisionReason")) ?? "";
    if (!reason.trim()) {
      setError(t("error.LEAVE_DECISION_REASON_REQUIRED"));
      return;
    }
    const ok = await runAction(
      row.id,
      () => rejectLeaveAllocation(row.id, { reason: reason.trim() }),
      t("common.failed"),
    );
    if (ok) {
      await load();
    }
  }

  async function handleDelete(row: LeaveAllocation) {
    if (!window.confirm(t("leaveAllocations.deleteConfirm"))) {
      return;
    }
    setBusyId(row.id);
    setError(null);
    try {
      await deleteLeaveAllocation(row.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusyId(null);
    }
  }

  const canCreate = can("leave_allocation.create");
  const canUpdate = can("leave_allocation.update");
  const canApprove = can("leave_allocation.approve");
  const canReject = can("leave_allocation.reject");
  const canDelete = can("leave_allocation.delete");
  const canCarry = can("leave_allocation.carry_forward");

  const employeeSearch = async (search: string) => {
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
  };

  const employeeResolve = async (id: number) => {
    const emp = await getEmployee(id);
    return `${emp.employee_number} — ${emp.first_name_en} ${emp.last_name_en}`;
  };

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">
          {t("leaveAllocations.heading")}
        </h1>
        <div className="flex flex-wrap gap-2">
          {canCreate ? (
            <button
              type="button"
              onClick={openCreate}
              className={primaryButtonClass}
            >
              + {t("leaveAllocations.new")}
            </button>
          ) : null}
          {canCreate ? (
            <button
              type="button"
              onClick={() => {
                setMode(mode === "generate" ? "none" : "generate");
                setError(null);
                setNotice(null);
              }}
              className={ghostButtonClass}
            >
              {t("leaveAllocations.generate")}
            </button>
          ) : null}
          {canCarry ? (
            <button
              type="button"
              onClick={() => {
                setMode(mode === "carry" ? "none" : "carry");
                setError(null);
                setNotice(null);
              }}
              className={ghostButtonClass}
            >
              {t("leaveAllocations.carryForward")}
            </button>
          ) : null}
        </div>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setPage(1);
        }}
        className="flex flex-wrap items-end gap-3"
      >
        <label className="min-w-40 flex-1">
          <span className={labelClass}>{t("leave.filters.leaveType")}</span>
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
        <label className="min-w-40 flex-1">
          <span className={labelClass}>{t("leave.filters.status")}</span>
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value);
              setPage(1);
            }}
            className={inputClass}
          >
            <option value="">—</option>
            <option value="submitted">
              {t("leaveAllocations.status.submitted")}
            </option>
            <option value="approved">
              {t("leaveAllocations.status.approved")}
            </option>
            <option value="rejected">
              {t("leaveAllocations.status.rejected")}
            </option>
            <option value="revoked">
              {t("leaveAllocations.status.revoked")}
            </option>
          </select>
        </label>
        <button type="submit" className={ghostButtonClass}>
          {t("common.search")}
        </button>
      </form>

      <div className="min-w-64">
        <SearchSelect
          label={t("leave.filters.employee")}
          value={employeeId}
          onChange={(val) => {
            setEmployeeId(val);
            setPage(1);
          }}
          load={employeeSearch}
          resolve={employeeResolve}
          placeholder={t("common.search")}
        />
      </div>

      {mode === "create" ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {editing ? t("common.edit") : t("leaveAllocations.new")}
          </h2>
          <form onSubmit={submitCreate} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("leave.employee")}</span>
              <SearchSelect
                label=""
                value={form.employee_id}
                onChange={(val) =>
                  setForm({ ...form, employee_id: val })
                }
                load={employeeSearch}
                resolve={employeeResolve}
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
                value={form.period_start}
                onChange={(event) =>
                  setForm({ ...form, period_start: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("leave.endDate")}</span>
              <input
                required
                type="date"
                value={form.period_end}
                onChange={(event) =>
                  setForm({ ...form, period_end: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("leaveAllocations.allocatedDays")}
              </span>
              <input
                required
                type="number"
                min={1}
                step="0.5"
                value={form.allocated_days}
                onChange={(event) =>
                  setForm({ ...form, allocated_days: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
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
                  setMode("none");
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

      {mode === "generate" ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-1 text-sm font-semibold">
            {t("leaveAllocations.generate")}
          </h2>
          <p className="mb-3 text-xs text-slate-500">
            {t("leaveAllocations.generateHint")}
          </p>
          <form onSubmit={submitGenerate} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("leave.type")}</span>
              <select
                required
                value={generateForm.leave_type_id}
                onChange={(event) =>
                  setGenerateForm({
                    ...generateForm,
                    leave_type_id: event.target.value,
                  })
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
              <span className={labelClass}>
                {t("leaveAllocations.allocatedDays")}
              </span>
              <input
                type="number"
                min={1}
                step="0.5"
                value={generateForm.allocated_days}
                onChange={(event) =>
                  setGenerateForm({
                    ...generateForm,
                    allocated_days: event.target.value,
                  })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("leave.startDate")}</span>
              <input
                required
                type="date"
                value={generateForm.period_start}
                onChange={(event) =>
                  setGenerateForm({
                    ...generateForm,
                    period_start: event.target.value,
                  })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("leave.endDate")}</span>
              <input
                required
                type="date"
                value={generateForm.period_end}
                onChange={(event) =>
                  setGenerateForm({
                    ...generateForm,
                    period_end: event.target.value,
                  })
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
                {saving ? t("common.saving") : t("common.create")}
              </button>
              <button
                type="button"
                onClick={() => setMode("none")}
                className={ghostButtonClass}
              >
                {t("common.cancel")}
              </button>
            </div>
          </form>
        </section>
      ) : null}

      {mode === "carry" ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-1 text-sm font-semibold">
            {t("leaveAllocations.carryForward")}
          </h2>
          <p className="mb-3 text-xs text-slate-500">
            {t("leaveAllocations.carryForwardHint")}
          </p>
          <form onSubmit={submitCarry} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("leave.startDate")}</span>
              <input
                required
                type="date"
                value={carryForm.period_start}
                onChange={(event) =>
                  setCarryForm({
                    ...carryForm,
                    period_start: event.target.value,
                  })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("leave.endDate")}</span>
              <input
                required
                type="date"
                value={carryForm.period_end}
                onChange={(event) =>
                  setCarryForm({
                    ...carryForm,
                    period_end: event.target.value,
                  })
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
                {saving ? t("common.saving") : t("common.create")}
              </button>
              <button
                type="button"
                onClick={() => setMode("none")}
                className={ghostButtonClass}
              >
                {t("common.cancel")}
              </button>
            </div>
          </form>
        </section>
      ) : null}

      {error ? <p className={errorTextClass}>{error}</p> : null}
      {notice ? <p className="text-sm text-green-700">{notice}</p> : null}

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        {loading ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {t("common.loading")}
          </p>
        ) : items.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {employeeId || typeFilter || statusFilter
              ? t("common.empty")
              : t("leaveAllocations.empty")}
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
                  <th className="py-2 text-start">
                    {t("leaveAllocations.allocatedDays")}
                  </th>
                  <th className="py-2 text-start">
                    {t("leaveAllocations.usedDays")}
                  </th>
                  <th className="py-2 text-start">
                    {t("leaveAllocations.source")}
                  </th>
                  <th className="py-2 text-start">{t("leave.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => {
                  const isSubmitted = row.status === "submitted";
                  const isApproved = row.status === "approved";
                  const editable =
                    isApproved && Number(row.used_days) === 0;
                  const busy = busyId === row.id;
                  const typeName =
                    types.find((type) => type.id === row.leave_type_id)
                      ?.name_en ?? `#${row.leave_type_id}`;
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
                        {row.period_start} → {row.period_end}
                      </td>
                      <td className="py-2">{Number(row.allocated_days)}</td>
                      <td className="py-2">{Number(row.used_days)}</td>
                      <td className="py-2">
                        {t(SOURCE_LABELS[row.source] ?? row.source)}
                      </td>
                      <td className="py-2">
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                          {t(STATUS_LABELS[row.status] ?? row.status)}
                        </span>
                      </td>
                      <td className="py-2">
                        <div className="flex flex-wrap gap-2">
                          {canUpdate && editable ? (
                            <button
                              type="button"
                              onClick={() => openEdit(row)}
                              className="text-blue-600 hover:underline"
                            >
                              {t("common.edit")}
                            </button>
                          ) : null}
                          {canApprove && isSubmitted ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleApprove(row)}
                              className="text-green-700 hover:underline disabled:opacity-50"
                            >
                              {t("leaveAllocations.approve")}
                            </button>
                          ) : null}
                          {canReject && isSubmitted ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleReject(row)}
                              className="text-red-600 hover:underline disabled:opacity-50"
                            >
                              {t("leaveAllocations.reject")}
                            </button>
                          ) : null}
                          {canDelete ? (
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
