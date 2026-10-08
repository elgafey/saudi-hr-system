import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useSession } from "../App";
import {
  exportPayrollRun,
  getPayrollRun,
  getPayslip,
  listPayrollRunLines,
  recalculatePayrollRun,
  type Payslip,
  type PayrollRun,
  type PayrollRunLine,
} from "../api";
import {
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  primaryButtonClass,
} from "../ui";

export default function PayrollRunDetailPage() {
  const { t, can } = useSession();
  const params = useParams<{ id: string }>();
  const runId = params.id ? Number(params.id) : null;

  const [run, setRun] = useState<PayrollRun | null>(null);
  const [lines, setLines] = useState<PayrollRunLine[]>([]);
  const [payslip, setPayslip] = useState<Payslip | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (runId === null) {
      return;
    }
    setLoading(true);
    try {
      const [runRow, linePage] = await Promise.all([
        getPayrollRun(runId),
        listPayrollRunLines(runId, { page_size: 200 }),
      ]);
      setRun(runRow);
      setLines(linePage.items);
      setPayslip(null);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [runId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function openPayslip(lineId: number) {
    if (runId === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const row = await getPayslip(lineId);
      setPayslip(row);
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusy(false);
    }
  }

  async function handleRecalculate() {
    if (runId === null) {
      return;
    }
    if (!window.confirm(t("payrollRun.recalculateConfirm"))) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await recalculatePayrollRun(runId);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusy(false);
    }
  }

  async function handleExport() {
    if (runId === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload = await exportPayrollRun(runId);
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `payroll-run-${runId}-export.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="py-16">
        <p className="text-center text-slate-500">{t("common.loading")}</p>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="space-y-4 py-16">
        <p className={errorTextClass}>{error ?? t("common.error")}</p>
        <Link
          to="/payroll-periods"
          className="text-sm text-blue-600 hover:underline"
        >
          {t("common.back")}
        </Link>
      </div>
    );
  }

  const canCalculate = can("payroll_run.calculate");
  const canExport = can("payroll_export.execute");

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-mono text-xs text-slate-500">
            {t("payrollRun.heading")} #{run.run_number}
          </p>
          <h1 className="text-xl font-semibold">
            {run.period_start ?? ""} — {run.period_end ?? ""}
          </h1>
          <div className="mt-1 flex flex-wrap gap-2 text-xs">
            <span className="rounded bg-slate-100 px-2 py-0.5">
              {t(`runStatus.${run.status}`)}
            </span>
            {run.period_status ? (
              <span className="rounded bg-slate-100 px-2 py-0.5">
                {t(`periodStatus.${run.period_status}`)}
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {canCalculate ? (
            <button
              type="button"
              onClick={() => void handleRecalculate()}
              disabled={busy}
              className={ghostButtonClass}
            >
              {t("payroll.recalculate")}
            </button>
          ) : null}
          {canExport ? (
            <button
              type="button"
              onClick={() => void handleExport()}
              disabled={busy}
              className={primaryButtonClass}
            >
              {t("payroll.export")}
            </button>
          ) : null}
          <Link
            to="/payroll-periods"
            className="text-sm text-blue-600 hover:underline"
          >
            {t("common.back")}
          </Link>
        </div>
      </div>

      {error ? <p className={errorTextClass}>{error}</p> : null}

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <div>
            <p className="text-xs text-slate-500">{t("payroll.employees")}</p>
            <p className="text-sm font-semibold">{run.employee_count}</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">{t("payroll.gross")}</p>
            <p className="text-sm font-semibold">{run.gross_total}</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">{t("payroll.deductions")}</p>
            <p className="text-sm font-semibold">{run.deductions_total}</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">{t("payroll.employer")}</p>
            <p className="text-sm font-semibold">{run.employer_total}</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">{t("payroll.net")}</p>
            <p className="text-sm font-semibold">{run.net_total}</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">{t("payroll.currency")}</p>
            <p className="text-sm font-semibold">SAR</p>
          </div>
        </div>
        <div className="mt-3 grid gap-3 border-t border-slate-100 pt-3 sm:grid-cols-2">
          <p className="font-mono text-xs text-slate-500">
            {t("payroll.engineVersion")}: {run.engine_version ?? "—"}
          </p>
          <p className="break-all font-mono text-xs text-slate-500">
            {t("payroll.inputsHash")}: {run.inputs_hash ?? "—"}
          </p>
        </div>
        {run.warnings && run.warnings.length > 0 ? (
          <div className="mt-3 border-t border-slate-100 pt-3">
            <p className="mb-1 text-xs font-semibold text-amber-700">
              {t("payroll.warnings")}
            </p>
            <ul className="space-y-1">
              {run.warnings.map((warning, index) => (
                <li
                  key={index}
                  className="break-all rounded bg-amber-50 px-2 py-1 font-mono text-xs text-amber-800"
                >
                  {JSON.stringify(warning)}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="mb-3 text-sm font-semibold">{t("payrollRun.lines")}</h2>
        {lines.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {t("payrollRun.noLines")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="py-2 text-start">{t("payroll.employeeId")}</th>
                  <th className="py-2 text-start">{t("payrollRun.basic")}</th>
                  <th className="py-2 text-start">{t("payroll.gross")}</th>
                  <th className="py-2 text-start">{t("payroll.deductions")}</th>
                  <th className="py-2 text-start">{t("payrollRun.netPay")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line) => (
                  <tr key={line.id} className="border-b border-slate-100">
                    <td className="py-2">#{line.employee_id}</td>
                    <td className="py-2">{line.basic_snapshot}</td>
                    <td className="py-2">{line.earnings_total}</td>
                    <td className="py-2">{line.deductions_total}</td>
                    <td className="py-2 font-semibold">{line.net_pay}</td>
                    <td className="py-2">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void openPayslip(line.id)}
                        className="text-blue-600 hover:underline disabled:opacity-50"
                      >
                        {t("payrollRun.viewPayslip")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {payslip ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">
              {t("payrollRun.payslip")} — {t("payroll.employeeId")} #
              {payslip.employee_id}
            </h2>
            <button
              type="button"
              onClick={() => setPayslip(null)}
              className={ghostButtonClass}
            >
              {t("common.cancel")}
            </button>
          </div>
          <div className="mb-3 grid gap-3 sm:grid-cols-4">
            <div>
              <p className="text-xs text-slate-500">{t("payroll.gross")}</p>
              <p className="text-sm font-semibold">{payslip.earnings_total}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">{t("payroll.deductions")}</p>
              <p className="text-sm font-semibold">
                {payslip.deductions_total}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">{t("payroll.employer")}</p>
              <p className="text-sm font-semibold">{payslip.employer_total}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">{t("payrollRun.netPay")}</p>
              <p className="text-sm font-semibold">{payslip.net_pay}</p>
            </div>
          </div>
          <div className="mb-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-5">
            <span>
              {t("payrollRun.workedMinutes")}: {payslip.worked_minutes}
            </span>
            <span>
              {t("payrollRun.overtimeMinutes")}: {payslip.overtime_minutes}
            </span>
            <span>
              {t("payrollRun.paidLeaveDays")}: {payslip.paid_leave_days}
            </span>
            <span>
              {t("payrollRun.unpaidLeaveDays")}: {payslip.unpaid_leave_days}
            </span>
            <span>
              {t("payrollRun.absentDays")}: {payslip.absent_days}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="py-2 text-start">{t("payrollRun.lineLabel")}</th>
                  <th className="py-2 text-start">{t("payrollRun.lineType")}</th>
                  <th className="py-2 text-start">{t("payrollRun.quantity")}</th>
                  <th className="py-2 text-start">{t("payrollRun.rate")}</th>
                  <th className="py-2 text-start">{t("common.amount")}</th>
                </tr>
              </thead>
              <tbody>
                {payslip.lines.map((line) => (
                  <tr key={line.id} className="border-b border-slate-100">
                    <td className="py-2">
                      {line.label_en}{" "}
                      <span dir="rtl" className="text-slate-500">
                        {line.label_ar}
                      </span>
                    </td>
                    <td className="py-2">
                      {t(`componentCategory.${line.line_type}`)}
                    </td>
                    <td className="py-2">{line.quantity ?? "—"}</td>
                    <td className="py-2">{line.rate ?? "—"}</td>
                    <td className="py-2 font-semibold">{line.amount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
