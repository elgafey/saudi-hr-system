import { useCallback, useEffect, useState } from "react";
import { useSession } from "../App";
import {
  myPayslip,
  myPayslips,
  type PageMeta,
  type Payslip,
  type PayslipSummary,
} from "../api";
import Pagination from "../components/Pagination";
import { errorMessage, errorTextClass } from "../ui";

const pageSize = 20;

function formatAmount(value: string): string {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(2) : value;
}

export default function EssPayslipsPage() {
  const { t, locale } = useSession();
  const [rows, setRows] = useState<PayslipSummary[]>([]);
  const [meta, setMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<Payslip | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await myPayslips({ page, page_size: pageSize });
      setRows(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [page, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function openDetail(runLineId: number) {
    setBusy(true);
    setDetailError(null);
    try {
      setDetail(await myPayslip(runLineId));
    } catch (err) {
      setDetail(null);
      setDetailError(errorMessage(err, t("common.error"), t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-4">
      <p className="text-xs text-slate-500">{t("ess.payslips.gatingNote")}</p>
      {error ? <p className={errorTextClass}>{error}</p> : null}
      {loading ? (
        <p className="text-sm text-slate-500">{t("common.loading")}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500">{t("ess.payslips.empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-4">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-2 pr-3">{t("ess.payslips.period")}</th>
                <th className="py-2 pr-3">{t("ess.payslips.range")}</th>
                <th className="py-2 pr-3">{t("ess.payslips.earnings")}</th>
                <th className="py-2 pr-3">{t("ess.payslips.deductions")}</th>
                <th className="py-2 pr-3">{t("ess.payslips.netPay")}</th>
                <th className="py-2 pr-3">{t("common.status")}</th>
                <th className="py-2 pr-3 text-right">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const statusKey = `periodStatus.${row.period_status}`;
                const statusLabel =
                  t(statusKey) === statusKey ? row.period_status : t(statusKey);
                return (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2 pr-3">{row.period_name}</td>
                    <td className="py-2 pr-3">
                      {row.period_start} → {row.period_end}
                    </td>
                    <td className="py-2 pr-3">
                      {formatAmount(row.earnings_total)} {row.currency}
                    </td>
                    <td className="py-2 pr-3">
                      {formatAmount(row.deductions_total)} {row.currency}
                    </td>
                    <td className="py-2 pr-3 font-medium">
                      {formatAmount(row.net_pay)} {row.currency}
                    </td>
                    <td className="py-2 pr-3">{statusLabel}</td>
                    <td className="py-2 pr-3 text-right">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void openDetail(row.id)}
                        className="text-blue-600 hover:underline disabled:opacity-50"
                      >
                        {t("ess.payslips.view")}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pagination meta={meta} onPage={setPage} />
        </div>
      )}

      {detailError ? <p className={errorTextClass}>{detailError}</p> : null}
      {detail ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between gap-4">
            <h3 className="text-sm font-semibold">
              {t("ess.payslips.detail")} — {detail.run_number}
            </h3>
            <button
              type="button"
              className="text-sm text-slate-500 hover:underline"
              onClick={() => setDetail(null)}
            >
              {t("common.close")}
            </button>
          </div>
          <div className="grid gap-4 sm:grid-cols-4">
            <p className="text-sm">
              <span className="block text-xs uppercase text-slate-500">
                {t("ess.payslips.earnings")}
              </span>
              {formatAmount(String(detail.earnings_total))}{" "}
              {detail.currency}
            </p>
            <p className="text-sm">
              <span className="block text-xs uppercase text-slate-500">
                {t("ess.payslips.deductions")}
              </span>
              {formatAmount(String(detail.deductions_total))}{" "}
              {detail.currency}
            </p>
            <p className="text-sm">
              <span className="block text-xs uppercase text-slate-500">
                {t("ess.payslips.netPay")}
              </span>
              <span className="font-medium">
                {formatAmount(String(detail.net_pay))} {detail.currency}
              </span>
            </p>
            <p className="text-sm">
              <span className="block text-xs uppercase text-slate-500">
                {t("ess.payslips.period")}
              </span>
              {detail.period_start ?? "—"} → {detail.period_end ?? "—"}
            </p>
          </div>
          <table className="mt-4 w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-2 pr-3">{t("payrollRun.lineLabel")}</th>
                <th className="py-2 pr-3">{t("payrollRun.lineType")}</th>
                <th className="py-2 pr-3 text-right">
                  {t("common.amount")}
                </th>
              </tr>
            </thead>
            <tbody>
              {detail.lines.map((line) => (
                <tr key={line.id} className="border-b border-slate-100">
                  <td className="py-2 pr-3">
                    {locale === "ar" ? line.label_ar : line.label_en}
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs">
                    {line.line_type}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    {formatAmount(String(line.amount))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
