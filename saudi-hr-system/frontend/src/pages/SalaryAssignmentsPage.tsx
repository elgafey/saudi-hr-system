import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  createSalaryAssignment,
  listEmployees,
  listSalaryAssignments,
  seedSalaryAssignments,
  updateSalaryAssignment,
  type Employee,
  type SalaryAssignment,
  type SalaryAssignmentInput,
  type SalaryAssignmentPageParams,
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

interface AssignmentFormState {
  employee_id: string;
  effective_from: string;
  effective_to: string;
  basic_salary: string;
  currency: string;
  reason: string;
}

const emptyForm: AssignmentFormState = {
  employee_id: "",
  effective_from: "",
  effective_to: "",
  basic_salary: "",
  currency: "SAR",
  reason: "",
};

export default function SalaryAssignmentsPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<SalaryAssignment[]>([]);
  const [meta, setMeta] = useState<{
    page: number;
    page_size: number;
    total: number;
  }>({ page: 1, page_size: pageSize, total: 0 });
  const [page, setPage] = useState(1);
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<SalaryAssignment | null>(null);
  const [form, setForm] = useState<AssignmentFormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [seeding, setSeeding] = useState(false);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: SalaryAssignmentPageParams = {
        company_id: companyId,
        page,
        page_size: pageSize,
        employee_id: employeeFilter ? Number(employeeFilter) : undefined,
      };
      const res = await listSalaryAssignments(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [companyId, page, employeeFilter, t]);

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
    setNotice(null);
  }

  function openEdit(row: SalaryAssignment) {
    setEditing(row);
    setForm({
      employee_id: String(row.employee_id),
      effective_from: row.effective_from,
      effective_to: row.effective_to ?? "",
      basic_salary: String(row.basic_salary),
      currency: row.currency,
      reason: row.reason ?? "",
    });
    setFormOpen(true);
    setError(null);
    setNotice(null);
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
        await updateSalaryAssignment(editing.id, {
          basic_salary: Number(form.basic_salary),
          currency: form.currency,
          effective_to: form.effective_to || null,
          reason: form.reason.trim() || null,
        });
      } else {
        const payload: SalaryAssignmentInput = {
          company_id: companyId,
          employee_id: Number(form.employee_id),
          effective_from: form.effective_from,
          effective_to: form.effective_to || null,
          basic_salary: Number(form.basic_salary),
          currency: form.currency,
          reason: form.reason.trim() || null,
        };
        await createSalaryAssignment(payload);
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

  async function handleSeed() {
    if (companyId === null) {
      return;
    }
    if (!window.confirm(t("salaryAssignments.seedConfirm"))) {
      return;
    }
    setSeeding(true);
    setError(null);
    setNotice(null);
    try {
      const result = await seedSalaryAssignments(companyId);
      setNotice(t("salaryAssignments.seedResult").replace("{created}", String(result.created)).replace("{skipped}", String(result.skipped)));
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSeeding(false);
    }
  }

  const canCreate = can("salary_assignment.create");
  const canUpdate = can("salary_assignment.update");

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">
          {t("salaryAssignments.heading")}
        </h1>
        <div className="flex flex-wrap gap-2">
          {canCreate ? (
            <button
              type="button"
              onClick={handleSeed}
              disabled={seeding}
              className={ghostButtonClass}
            >
              {seeding
                ? t("common.saving")
                : t("salaryAssignments.seedFromContracts")}
            </button>
          ) : null}
          {canCreate ? (
            <button
              type="button"
              onClick={openCreate}
              className={primaryButtonClass}
            >
              + {t("salaryAssignments.new")}
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
        <label className="min-w-60 flex-1">
          <span className={labelClass}>{t("payroll.employee")}</span>
          <select
            value={employeeFilter}
            onChange={(event) => {
              setEmployeeFilter(event.target.value);
              setPage(1);
            }}
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
        <button type="submit" className={ghostButtonClass}>
          {t("common.search")}
        </button>
      </form>

      {formOpen ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {editing
              ? t("salaryAssignments.edit")
              : t("salaryAssignments.new")}
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
              <span className={labelClass}>
                {t("salaryAssignments.basicSalary")}
              </span>
              <input
                required
                type="number"
                min={0}
                step="0.01"
                value={form.basic_salary}
                onChange={(event) =>
                  setForm({ ...form, basic_salary: event.target.value })
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
            <label>
              <span className={labelClass}>{t("payroll.currency")}</span>
              <input
                required
                maxLength={3}
                value={form.currency}
                onChange={(event) =>
                  setForm({ ...form, currency: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("salaryAssignments.reason")}</span>
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
      {notice ? (
        <p className="text-sm text-emerald-700">{notice}</p>
      ) : null}

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        {loading ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {t("common.loading")}
          </p>
        ) : items.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {t("salaryAssignments.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("payroll.employee")}</th>
                  <th className="py-2 text-start">
                    {t("salaryAssignments.effectiveFrom")}
                  </th>
                  <th className="py-2 text-start">
                    {t("salaryAssignments.effectiveTo")}
                  </th>
                  <th className="py-2 text-start">
                    {t("salaryAssignments.basicSalary")}
                  </th>
                  <th className="py-2 text-start">{t("payroll.currency")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2">{employeeLabel(row.employee_id)}</td>
                    <td className="py-2">{row.effective_from}</td>
                    <td className="py-2">{row.effective_to ?? "—"}</td>
                    <td className="py-2">{row.basic_salary}</td>
                    <td className="py-2">{row.currency}</td>
                    <td className="py-2">
                      {canUpdate ? (
                        <button
                          type="button"
                          onClick={() => openEdit(row)}
                          className="text-blue-600 hover:underline"
                        >
                          {t("common.edit")}
                        </button>
                      ) : null}
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
