import { useCallback, useEffect, useState } from "react";
import { useSession } from "../App";
import {
  myAttendance,
  type AttendanceRecord,
  type PageMeta,
} from "../api";
import Pagination from "../components/Pagination";
import {
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  inputClass,
  labelClass,
} from "../ui";

const pageSize = 20;

const STATUS_LABELS: Record<string, string> = {
  open: "attendance.status.open",
  completed: "attendance.status.completed",
  missing_checkout: "attendance.status.missing_checkout",
};

export default function EssAttendancePage() {
  const { t } = useSession();
  const [rows, setRows] = useState<AttendanceRecord[]>([]);
  const [meta, setMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await myAttendance({
        page,
        page_size: pageSize,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      setRows(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [page, dateFrom, dateTo, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const minutesLabel = (minutes: number | null): string =>
    minutes == null ? "—" : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className={labelClass}>
            {t("attendance.filters.dateFrom")}
          </span>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => {
              setDateFrom(e.target.value);
              setPage(1);
            }}
            className={inputClass}
          />
        </label>
        <label className="text-sm">
          <span className={labelClass}>
            {t("attendance.filters.dateTo")}
          </span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => {
              setDateTo(e.target.value);
              setPage(1);
            }}
            className={inputClass}
          />
        </label>
        <button
          type="button"
          className={ghostButtonClass}
          onClick={() => {
            setDateFrom("");
            setDateTo("");
            setPage(1);
          }}
        >
          {t("common.clear")}
        </button>
      </div>

      {error ? <p className={errorTextClass}>{error}</p> : null}

      {loading ? (
        <p className="text-sm text-slate-500">{t("common.loading")}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500">{t("ess.attendance.empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-4">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-2 pr-3">{t("attendance.date")}</th>
                <th className="py-2 pr-3">{t("attendance.checkInTime")}</th>
                <th className="py-2 pr-3">{t("attendance.checkOutTime")}</th>
                <th className="py-2 pr-3">{t("attendance.workedHours")}</th>
                <th className="py-2 pr-3">{t("attendance.lateMinutes")}</th>
                <th className="py-2 pr-3">{t("attendance.status")}</th>
                <th className="py-2 pr-3">{t("attendance.source")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const statusLabel = t(
                  STATUS_LABELS[row.status] ?? row.status,
                );
                const time = (value: string | null): string =>
                  value ? value.slice(11, 16) : "—";
                return (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2 pr-3">{row.work_date}</td>
                    <td className="py-2 pr-3">{time(row.check_in)}</td>
                    <td className="py-2 pr-3">{time(row.check_out)}</td>
                    <td className="py-2 pr-3">
                      {minutesLabel(row.worked_minutes)}
                    </td>
                    <td className="py-2 pr-3">
                      {minutesLabel(row.late_minutes)}
                    </td>
                    <td className="py-2 pr-3">{statusLabel}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{row.source}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pagination meta={meta} onPage={setPage} />
        </div>
      )}
    </section>
  );
}
