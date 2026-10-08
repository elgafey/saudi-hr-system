import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSession } from "../App";
import {
  createSalaryAssignment,
  listSalaryAssignments,
  seedSalaryAssignments,
  updateSalaryAssignment,
  type SalaryAssignment,
} from "../api";
import {
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../ui";

interface Props {
  employeeId: number;
  companyId: number;
}

interface AssignmentFormState {
  basic_salary: string;
  effective_from: string;
  effective_to: string;
  reason: string;
}

const emptyForm: AssignmentFormState = {
  basic_salary: "",
  effective_from: "",
  effective_to: "",
  reason: "",
};

export default function CompensationPanel({ employeeId, companyId }: Props) {
  const { t, can } = useSession();

  const [items, setItems] = useState<SalaryAssignment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<SalaryAssignment | null>(null);
  const [form, setForm] = useState<AssignmentFormState>(emptyForm);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listSalaryAssignments({
        company_id: companyId,
        employee_id: employeeId,
        page_size: 50,
      });
      setItems(res.items);
      setError(null);
    } catch (err) {
      setItems([]);
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [companyId, employeeId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditing(null);
    setForm(emptyForm);
    setFormOpen(true);
    setNotice(null);
    setError(null);
  }

  function openEdit(row: SalaryAssignment) {
    setEditing(row);
    setForm({
      basic_salary: String(row.basic_salary),
      effective_from: row.effective_from,
      effective_to: row.effective_to ?? "",
      reason: row.reason ?? "",
    });
    setFormOpen(true);
    setNotice(null);
    setError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (editing) {
        await updateSalaryAssignment(editing.id, {
          basic_salary: Number(form.basic_salary),
          effective_to: form.effective_to || null,
          reason: form.reason.trim() || null,
        });
      } else {
        await createSalaryAssignment({
          company_id: companyId,
          employee_id: employeeId,
          effective_from: form.effective_from,
          effective_to: form.effective_to || null,
          basic_salary: Number(form.basic_salary),
          reason: form.reason.trim() || null,
        });
      }
      setFormOpen(false);
      setEditing(null);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusy(false);
    }
  }

  async function handleSeed() {
    if (!window.confirm(t("salaryAssignments.seedConfirm"))) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await seedSalaryAssignments(companyId);
      setNotice(
        t("salaryAssignments.seedResult")
          .replace("{created}", String(res.created))
          .replace("{skipped}", String(res.skipped)),
      );
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusy(false);
    }
  }

  const canCreate = can("salary_assignment.create");
  const canUpdate = can("salary_assignment.update");

  return (
    <div className="space-y-6">
      {error ? <p className={errorTextClass}>{error}</p> : null}
      {notice ? (
        <p className="rounded bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {notice}
        </p>
      ) : null}

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">
            {t("salaryAssignments.heading")}
          </h2>
          <div className="flex flex-wrap gap-2">
            {canCreate ? (
              <>
                <button
                  type="button"
                  onClick={openCreate}
                  className={primaryButtonClass}
                >
                  + {t("salaryAssignments.new")}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleSeed()}
                  className={ghostButtonClass}
                >
                  {t("salaryAssignments.seedFromContracts")}
                </button>
              </>
            ) : null}
          </div>
        </div>

        {formOpen ? (
          <form
            onSubmit={submit}
            className="mb-4 grid gap-3 rounded-lg border border-slate-200 p-3 sm:grid-cols-2"
          >
            <label>
              <span className={labelClass}>
                {t("salaryAssignments.basicSalary")}
              </span>
              <input
                required
                type="number"
                min={0.01}
                step="0.01"
                value={form.basic_salary}
                onChange={(event) =>
                  setForm({ ...form, basic_salary: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("payroll.currency")}</span>
              <input
                disabled
                value={items[0]?.currency ?? "SAR"}
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
              <span className={labelClass}>
                {t("salaryAssignments.reason")}
              </span>
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
                disabled={busy}
                className={primaryButtonClass}
              >
                {busy ? t("common.saving") : t("common.save")}
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
        ) : null}

        {loading ? (
          <p className="py-3 text-center text-sm text-slate-500">
            {t("common.loading")}
          </p>
        ) : items.length === 0 ? (
          <p className="py-3 text-center text-sm text-slate-500">
            {t("salaryAssignments.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
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
                  <th className="py-2 text-start">
                    {t("salaryAssignments.reason")}
                  </th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2">{row.effective_from}</td>
                    <td className="py-2">{row.effective_to ?? "—"}</td>
                    <td className="py-2 font-medium">{row.basic_salary}</td>
                    <td className="py-2">{row.currency}</td>
                    <td className="py-2">{row.reason ?? "—"}</td>
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
          </div>
        )}
      </section>
    </div>
  );
}
