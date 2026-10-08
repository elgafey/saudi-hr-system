import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../App";
import {
  approvePayrollPeriod,
  calculatePayrollPeriod,
  createPayrollPeriod,
  listPayrollPeriods,
  listPayrollRuns,
  lockPayrollPeriod,
  markPayrollPeriodPaid,
  reviewPayrollPeriod,
  updatePayrollPeriod,
  type PayrollPeriod,
  type PayrollPeriodInput,
  type PayrollPeriodPageParams,
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

interface PeriodFormState {
  name: string;
  period_start: string;
  period_end: string;
  notes: string;
}

const emptyForm: PeriodFormState = {
  name: "",
  period_start: "",
  period_end: "",
  notes: "",
};

export default function PayrollPeriodsPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;
  const navigate = useNavigate();

  const [items, setItems] = useState<PayrollPeriod[]>([]);
  const [meta, setMeta] = useState<{
    page: number;
    page_size: number;
    total: number;
  }>({ page: 1, page_size: pageSize, total: 0 });
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<PayrollPeriod | null>(null);
  const [form, setForm] = useState<PeriodFormState>(emptyForm);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: PayrollPeriodPageParams = {
        company_id: companyId,
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
      };
      const res = await listPayrollPeriods(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [companyId, page, statusFilter, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditing(null);
    setForm(emptyForm);
    setFormOpen(true);
    setError(null);
  }

  function openEdit(row: PayrollPeriod) {
    setEditing(row);
    setForm({
      name: row.name,
      period_start: row.period_start,
      period_end: row.period_end,
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
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await updatePayrollPeriod(editing.id, {
          name: form.name.trim(),
          notes: form.notes.trim() || null,
        });
      } else {
        const payload: PayrollPeriodInput = {
          company_id: companyId,
          name: form.name.trim(),
          period_start: form.period_start,
          period_end: form.period_end,
          notes: form.notes.trim() || null,
        };
        await createPayrollPeriod(payload);
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
    row: PayrollPeriod,
    action: "calculate" | "review" | "approve" | "mark-paid" | "lock",
  ) {
    setBusyId(row.id);
    setError(null);
    try {
      if (action === "calculate") {
        const run = await calculatePayrollPeriod(row.id);
        navigate(`/payroll-runs/${run.id}`);
        return;
      }
      if (action === "review") {
        await reviewPayrollPeriod(row.id);
      } else if (action === "approve") {
        await approvePayrollPeriod(row.id);
      } else if (action === "mark-paid") {
        await markPayrollPeriodPaid(row.id);
      } else {
        await lockPayrollPeriod(row.id);
      }
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusyId(null);
    }
  }

  async function openRun(row: PayrollPeriod) {
    setBusyId(row.id);
    setError(null);
    try {
      const res = await listPayrollRuns({
        company_id: row.company_id,
        period_id: row.id,
        page_size: 5,
      });
      const active =
        res.items.find((run) => run.status === "active") ?? res.items[0];
      if (active) {
        navigate(`/payroll-runs/${active.id}`);
      } else {
        setError(t("payrollPeriods.noRun"));
      }
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusyId(null);
    }
  }

  const canCreate = can("payroll_period.create");
  const canUpdate = can("payroll_period.update");
  const canCalculate = can("payroll_run.calculate");
  const canReview = can("payroll_run.review");
  const canApprove = can("payroll_run.approve");
  const canMarkPaid = can("payroll_run.mark_paid");
  const canLock = can("payroll_run.lock");

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">
          {t("payrollPeriods.heading")}
        </h1>
        {canCreate ? (
          <button
            type="button"
            onClick={openCreate}
            className={primaryButtonClass}
          >
            + {t("payrollPeriods.new")}
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
            <option value="draft">{t("periodStatus.draft")}</option>
            <option value="calculated">{t("periodStatus.calculated")}</option>
            <option value="reviewed">{t("periodStatus.reviewed")}</option>
            <option value="approved">{t("periodStatus.approved")}</option>
            <option value="paid">{t("periodStatus.paid")}</option>
            <option value="locked">{t("periodStatus.locked")}</option>
          </select>
        </label>
        <button type="submit" className={ghostButtonClass}>
          {t("common.search")}
        </button>
      </form>

      {formOpen ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {editing ? t("payrollPeriods.edit") : t("payrollPeriods.new")}
          </h2>
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("payrollPeriods.name")}</span>
              <input
                required
                maxLength={100}
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("payrollPeriods.notes")}</span>
              <input
                value={form.notes}
                onChange={(event) =>
                  setForm({ ...form, notes: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("payrollPeriods.startDate")}
              </span>
              <input
                required
                disabled={editing !== null}
                type="date"
                value={form.period_start}
                onChange={(event) =>
                  setForm({ ...form, period_start: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("payrollPeriods.endDate")}
              </span>
              <input
                required
                disabled={editing !== null}
                type="date"
                value={form.period_end}
                onChange={(event) =>
                  setForm({ ...form, period_end: event.target.value })
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
            {t("payrollPeriods.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("payrollPeriods.name")}</th>
                  <th className="py-2 text-start">
                    {t("payrollPeriods.startDate")}
                  </th>
                  <th className="py-2 text-start">
                    {t("payrollPeriods.endDate")}
                  </th>
                  <th className="py-2 text-start">{t("common.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2">{row.name}</td>
                    <td className="py-2">{row.period_start}</td>
                    <td className="py-2">{row.period_end}</td>
                    <td className="py-2">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                        {t(`periodStatus.${row.status}`)}
                      </span>
                    </td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-2">
                        {canUpdate && row.status === "draft" ? (
                          <button
                            type="button"
                            onClick={() => openEdit(row)}
                            className="text-blue-600 hover:underline"
                          >
                            {t("common.edit")}
                          </button>
                        ) : null}
                        {row.status !== "draft" ? (
                          <button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void openRun(row)}
                            className="text-blue-600 hover:underline disabled:opacity-50"
                          >
                            {t("payrollPeriods.viewRun")}
                          </button>
                        ) : null}
                        {canCalculate &&
                        (row.status === "draft" ||
                          row.status === "calculated") ? (
                          <button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void runAction(row, "calculate")}
                            className="text-emerald-700 hover:underline disabled:opacity-50"
                          >
                            {t("payroll.calculate")}
                          </button>
                        ) : null}
                        {canReview && row.status === "calculated" ? (
                          <button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void runAction(row, "review")}
                            className="text-blue-600 hover:underline disabled:opacity-50"
                          >
                            {t("payroll.review")}
                          </button>
                        ) : null}
                        {canApprove && row.status === "reviewed" ? (
                          <button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void runAction(row, "approve")}
                            className="text-amber-700 hover:underline disabled:opacity-50"
                          >
                            {t("payroll.approve")}
                          </button>
                        ) : null}
                        {canMarkPaid && row.status === "approved" ? (
                          <button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void runAction(row, "mark-paid")}
                            className="text-blue-600 hover:underline disabled:opacity-50"
                          >
                            {t("payroll.markPaid")}
                          </button>
                        ) : null}
                        {canLock && row.status === "paid" ? (
                          <button
                            type="button"
                            disabled={busyId === row.id}
                            onClick={() => void runAction(row, "lock")}
                            className="text-red-700 hover:underline disabled:opacity-50"
                          >
                            {t("payroll.lock")}
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
