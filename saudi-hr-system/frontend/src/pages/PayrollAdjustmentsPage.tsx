import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  createPayrollAdjustment,
  decidePayrollAdjustment,
  listEmployees,
  listPayrollAdjustments,
  listPayrollPeriods,
  type Employee,
  type PayrollAdjustment,
  type PayrollAdjustmentInput,
  type PayrollAdjustmentPageParams,
  type PayrollPeriod,
} from "../api";
import Pagination from "../components/Pagination";
import {
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../ui";

const pageSize = 20;

interface AdjustmentFormState {
  employee_id: string;
  period_id: string;
  amount: string;
  direction: string;
  reason: string;
}

const emptyForm: AdjustmentFormState = {
  employee_id: "",
  period_id: "",
  amount: "",
  direction: "earning",
  reason: "",
};

export default function PayrollAdjustmentsPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<PayrollAdjustment[]>([]);
  const [meta, setMeta] = useState<{
    page: number;
    page_size: number;
    total: number;
  }>({ page: 1, page_size: pageSize, total: 0 });
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [periods, setPeriods] = useState<PayrollPeriod[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<AdjustmentFormState>(emptyForm);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: PayrollAdjustmentPageParams = {
        company_id: companyId,
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
      };
      const res = await listPayrollAdjustments(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [companyId, page, statusFilter, t]);

  const loadRefs = useCallback(async () => {
    if (companyId === null) {
      return;
    }
    try {
      const [empRes, perRes] = await Promise.all([
        listEmployees({ company_id: companyId, page_size: 200 }),
        listPayrollPeriods({ company_id: companyId, page_size: 100 }),
      ]);
      setEmployees(empRes.items);
      setPeriods(perRes.items);
    } catch {
      setEmployees([]);
      setPeriods([]);
    }
  }, [companyId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadRefs();
  }, [loadRefs]);

  function employeeLabel(id: number): string {
    const found = employees.find((row) => row.id === id);
    if (!found) {
      return `#${id}`;
    }
    return `${found.employee_number} — ${found.first_name_en} ${found.last_name_en}`;
  }

  function periodLabel(id: number): string {
    const found = periods.find((row) => row.id === id);
    return found ? found.name : `#${id}`;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (companyId === null || !form.employee_id || !form.period_id) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload: PayrollAdjustmentInput = {
        company_id: companyId,
        employee_id: Number(form.employee_id),
        period_id: Number(form.period_id),
        amount: Number(form.amount),
        direction: form.direction,
        reason: form.reason.trim(),
      };
      await createPayrollAdjustment(payload);
      setFormOpen(false);
      setForm(emptyForm);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSaving(false);
    }
  }

  async function decide(
    row: PayrollAdjustment,
    decision: "approve" | "reject" | "void",
  ) {
    const reason =
      window.prompt(t("payrollAdjustments.decisionPrompt"), "") ?? "";
    if (reason.trim() === "" && decision !== "void") {
      return;
    }
    setBusyId(row.id);
    setError(null);
    try {
      await decidePayrollAdjustment(row.id, decision, {
        decision_reason: reason.trim() || null,
      });
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusyId(null);
    }
  }

  const canCreate = can("payroll_adjustment.create");
  const canApprove = can("payroll_adjustment.approve");
  const canReject = can("payroll_adjustment.reject");
  const canVoid = can("payroll_adjustment.void");

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">
          {t("payrollAdjustments.heading")}
        </h1>
        {canCreate ? (
          <button
            type="button"
            onClick={() => {
              setFormOpen(!formOpen);
              setError(null);
            }}
            className={primaryButtonClass}
          >
            + {t("payrollAdjustments.new")}
          </button>
        ) : null}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setPage(1);
        }}
        className="flex flex-wrap items-end gap-3"
      >
        <label className="min-w-40 flex-1">
          <span className={labelClass}>{t("common.status")}</span>
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value);
              setPage(1);
            }}
            className={inputClass}
          >
            <option value="">—</option>
            <option value="draft">{t("adjustmentStatus.draft")}</option>
            <option value="pending">{t("adjustmentStatus.pending")}</option>
            <option value="approved">{t("adjustmentStatus.approved")}</option>
            <option value="rejected">{t("adjustmentStatus.rejected")}</option>
            <option value="void">{t("adjustmentStatus.void")}</option>
          </select>
        </label>
        <button type="submit" className={ghostButtonClass}>
          {t("common.search")}
        </button>
      </form>

      {formOpen ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {t("payrollAdjustments.new")}
          </h2>
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("payroll.employee")}</span>
              <select
                required
                value={form.employee_id}
                onChange={(event) =>
                  setForm({ ...form, employee_id: event.target.value })
                }
                className={inputClass}
              >
                <option value="">—</option>
                {employees.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.employee_number} — {row.first_name_en}{" "}
                    {row.last_name_en}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className={labelClass}>{t("payrollAdjustments.period")}</span>
              <select
                required
                value={form.period_id}
                onChange={(event) =>
                  setForm({ ...form, period_id: event.target.value })
                }
                className={inputClass}
              >
                <option value="">—</option>
                {periods.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className={labelClass}>{t("common.amount")}</span>
              <input
                required
                type="number"
                min={0.01}
                step="0.01"
                value={form.amount}
                onChange={(event) =>
                  setForm({ ...form, amount: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("payrollAdjustments.direction")}
              </span>
              <select
                value={form.direction}
                onChange={(event) =>
                  setForm({ ...form, direction: event.target.value })
                }
                className={inputClass}
              >
                <option value="earning">
                  {t("adjustmentDirection.earning")}
                </option>
                <option value="deduction">
                  {t("adjustmentDirection.deduction")}
                </option>
              </select>
            </label>
            <label className="sm:col-span-2">
              <span className={labelClass}>
                {t("payrollAdjustments.reason")}
              </span>
              <input
                required
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
                onClick={() => setFormOpen(false)}
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
            {t("payrollAdjustments.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("payroll.employee")}</th>
                  <th className="py-2 text-start">
                    {t("payrollAdjustments.period")}
                  </th>
                  <th className="py-2 text-start">{t("common.amount")}</th>
                  <th className="py-2 text-start">
                    {t("payrollAdjustments.direction")}
                  </th>
                  <th className="py-2 text-start">
                    {t("payrollAdjustments.reason")}
                  </th>
                  <th className="py-2 text-start">{t("common.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2">{employeeLabel(row.employee_id)}</td>
                    <td className="py-2">{periodLabel(row.period_id)}</td>
                    <td className="py-2">{row.amount}</td>
                    <td className="py-2">
                      {t(`adjustmentDirection.${row.direction}`)}
                    </td>
                    <td className="py-2">{row.reason}</td>
                    <td className="py-2">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                        {t(`adjustmentStatus.${row.status}`)}
                      </span>
                    </td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-2">
                        {canApprove && row.status === "pending" ? (
                          <button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void decide(row, "approve")}
                            className="text-emerald-700 hover:underline disabled:opacity-50"
                          >
                            {t("common.approve")}
                          </button>
                        ) : null}
                        {canReject && row.status === "pending" ? (
                          <button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void decide(row, "reject")}
                            className="text-red-600 hover:underline disabled:opacity-50"
                          >
                            {t("common.reject")}
                          </button>
                        ) : null}
                        {canVoid &&
                        ["draft", "pending", "approved"].includes(
                          row.status,
                        ) ? (
                          <button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void decide(row, "void")}
                            className="text-amber-700 hover:underline disabled:opacity-50"
                          >
                            {t("common.void")}
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
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
