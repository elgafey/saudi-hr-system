import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  createPayrollDeduction,
  listEmployees,
  listPayrollDeductions,
  updatePayrollDeduction,
  type Employee,
  type PayrollDeduction,
  type PayrollDeductionInput,
  type PayrollDeductionPageParams,
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

interface DeductionFormState {
  employee_id: string;
  name: string;
  amount: string;
  total_amount: string;
  effective_from: string;
  effective_to: string;
  reason: string;
}

const emptyForm: DeductionFormState = {
  employee_id: "",
  name: "",
  amount: "",
  total_amount: "",
  effective_from: "",
  effective_to: "",
  reason: "",
};

export default function PayrollDeductionsPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<PayrollDeduction[]>([]);
  const [meta, setMeta] = useState<{
    page: number;
    page_size: number;
    total: number;
  }>({ page: 1, page_size: pageSize, total: 0 });
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<PayrollDeduction | null>(null);
  const [form, setForm] = useState<DeductionFormState>(emptyForm);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: PayrollDeductionPageParams = {
        company_id: companyId,
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
      };
      const res = await listPayrollDeductions(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [companyId, page, statusFilter, t]);

  const loadEmployees = useCallback(async () => {
    if (companyId === null) {
      return;
    }
    try {
      const res = await listEmployees({
        company_id: companyId,
        page_size: 200,
      });
      setEmployees(res.items);
    } catch {
      setEmployees([]);
    }
  }, [companyId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadEmployees();
  }, [loadEmployees]);

  function employeeLabel(id: number): string {
    const found = employees.find((row) => row.id === id);
    if (!found) {
      return `#${id}`;
    }
    return `${found.employee_number} — ${found.first_name_en} ${found.last_name_en}`;
  }

  function openCreate() {
    setEditing(null);
    setForm(emptyForm);
    setFormOpen(true);
    setError(null);
  }

  function openEdit(row: PayrollDeduction) {
    setEditing(row);
    setForm({
      employee_id: String(row.employee_id),
      name: row.name,
      amount: String(row.amount),
      total_amount:
        row.total_amount !== null ? String(row.total_amount) : "",
      effective_from: row.effective_from,
      effective_to: row.effective_to ?? "",
      reason: row.reason ?? "",
    });
    setFormOpen(true);
    setError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (companyId === null || !form.employee_id) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await updatePayrollDeduction(editing.id, {
          amount: Number(form.amount),
          effective_to: form.effective_to || null,
          reason: form.reason.trim() || null,
        });
      } else {
        const payload: PayrollDeductionInput = {
          company_id: companyId,
          employee_id: Number(form.employee_id),
          name: form.name.trim(),
          amount: Number(form.amount),
          total_amount: form.total_amount
            ? Number(form.total_amount)
            : null,
          effective_from: form.effective_from,
          effective_to: form.effective_to || null,
          reason: form.reason.trim() || null,
        };
        await createPayrollDeduction(payload);
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

  async function cancelDeduction(row: PayrollDeduction) {
    if (!window.confirm(t("payrollDeductions.cancelConfirm"))) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await updatePayrollDeduction(row.id, { status: "cancelled" });
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSaving(false);
    }
  }

  const canCreate = can("payroll_deduction.create");
  const canUpdate = can("payroll_deduction.update");

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">
          {t("payrollDeductions.heading")}
        </h1>
        {canCreate ? (
          <button
            type="button"
            onClick={openCreate}
            className={primaryButtonClass}
          >
            + {t("payrollDeductions.new")}
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
            <option value="active">{t("deductionStatus.active")}</option>
            <option value="completed">{t("deductionStatus.completed")}</option>
            <option value="cancelled">{t("deductionStatus.cancelled")}</option>
          </select>
        </label>
        <button type="submit" className={ghostButtonClass}>
          {t("common.search")}
        </button>
      </form>

      {formOpen ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {editing ? t("common.edit") : t("payrollDeductions.new")}
          </h2>
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("payroll.employee")}</span>
              <select
                required
                disabled={editing !== null}
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
              <span className={labelClass}>{t("payrollDeductions.name")}</span>
              <input
                required
                disabled={editing !== null}
                maxLength={100}
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
                className={inputClass}
              />
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
                {t("payrollDeductions.totalAmount")}
              </span>
              <input
                type="number"
                min={0.01}
                step="0.01"
                value={form.total_amount}
                onChange={(event) =>
                  setForm({ ...form, total_amount: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("salaryAssignments.effectiveFrom")}
              </span>
              <input
                required
                disabled={editing !== null}
                type="date"
                value={form.effective_from}
                onChange={(event) =>
                  setForm({ ...form, effective_from: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("salaryAssignments.effectiveTo")}
              </span>
              <input
                type="date"
                value={form.effective_to}
                onChange={(event) =>
                  setForm({ ...form, effective_to: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label className="sm:col-span-2">
              <span className={labelClass}>{t("payrollAdjustments.reason")}</span>
              <input
                maxLength={500}
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
            {t("payrollDeductions.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("payroll.employee")}</th>
                  <th className="py-2 text-start">{t("payrollDeductions.name")}</th>
                  <th className="py-2 text-start">{t("common.amount")}</th>
                  <th className="py-2 text-start">
                    {t("payrollDeductions.remaining")}
                  </th>
                  <th className="py-2 text-start">
                    {t("salaryAssignments.effectiveFrom")}
                  </th>
                  <th className="py-2 text-start">
                    {t("salaryAssignments.effectiveTo")}
                  </th>
                  <th className="py-2 text-start">{t("common.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2">{employeeLabel(row.employee_id)}</td>
                    <td className="py-2">{row.name}</td>
                    <td className="py-2">{row.amount}</td>
                    <td className="py-2">{row.remaining_amount ?? "—"}</td>
                    <td className="py-2">{row.effective_from}</td>
                    <td className="py-2">{row.effective_to ?? "—"}</td>
                    <td className="py-2">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                        {t(`deductionStatus.${row.status}`)}
                      </span>
                    </td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-2">
                        {canUpdate && row.status === "active" ? (
                          <>
                            <button
                              type="button"
                              onClick={() => openEdit(row)}
                              className="text-blue-600 hover:underline"
                            >
                              {t("common.edit")}
                            </button>
                            <button
                              type="button"
                              onClick={() => void cancelDeduction(row)}
                              className="text-red-600 hover:underline"
                            >
                              {t("common.cancel")}
                            </button>
                          </>
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
