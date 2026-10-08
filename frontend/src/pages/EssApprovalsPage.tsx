import { useCallback, useEffect, useState } from "react";
import { useSession } from "../App";
import {
  listApprovals,
  type ApprovalsPageParams,
  type EmployeeRequest,
  type PageMeta,
} from "../api";
import EmployeeRequestDetail from "../components/EmployeeRequestDetail";
import Pagination from "../components/Pagination";
import {
  errorMessage,
  errorTextClass,
  inputClass,
  labelClass,
} from "../ui";

const pageSize = 20;

const STATUS_OPTIONS = ["submitted", "approved", "rejected", "cancelled"];

export default function EssApprovalsPage() {
  const { t, can } = useSession();
  const mayDecide =
    can("employee_request.approve") ||
    can("employee_request.manage") ||
    can("employee_request.view");

  const [items, setItems] = useState<EmployeeRequest[]>([]);
  const [meta, setMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("submitted");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!mayDecide) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: ApprovalsPageParams = {
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
      };
      const res = await listApprovals(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, t, mayDecide]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!mayDecide) {
    return <p className={errorTextClass}>{t("error.forbidden")}</p>;
  }

  const statusLabel = (status: string): string => {
    const key = `requests.status.${status}`;
    const label = t(key);
    return label === key ? status : label;
  };
  const typeLabel = (type: string): string => {
    const key = `requests.type.${type}`;
    const label = t(key);
    return label === key ? type : label;
  };

  return (
    <div className="space-y-6 py-8">
      <h1 className="text-xl font-semibold">{t("approvals.heading")}</h1>

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className={labelClass}>{t("approvals.filters.status")}</span>
          <select
            className={inputClass}
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="">—</option>
            {STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>
                {statusLabel(status)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error ? <p className={errorTextClass}>{error}</p> : null}

      {loading ? (
        <p className="text-sm text-slate-500">{t("common.loading")}</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-500">{t("approvals.empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-4">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-2 pr-3">{t("requests.employee")}</th>
                <th className="py-2 pr-3">{t("requests.subject")}</th>
                <th className="py-2 pr-3">{t("requests.type")}</th>
                <th className="py-2 pr-3">{t("common.status")}</th>
                <th className="py-2 pr-3">{t("requests.submittedAt")}</th>
                <th className="py-2 pr-3 text-right">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.id} className="border-b border-slate-100">
                  <td className="py-2 pr-3 font-mono text-xs">
                    #{row.employee_id}
                  </td>
                  <td className="py-2 pr-3">{row.subject}</td>
                  <td className="py-2 pr-3">{typeLabel(row.request_type)}</td>
                  <td className="py-2 pr-3">{statusLabel(row.status)}</td>
                  <td className="py-2 pr-3">
                    {row.submitted_at
                      ? row.submitted_at.slice(0, 16).replace("T", " ")
                      : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <button
                      type="button"
                      className="text-blue-600 hover:underline"
                      onClick={() => setSelectedId(row.id)}
                    >
                      {t("requests.detail")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination meta={meta} onPage={setPage} />
        </div>
      )}

      <EmployeeRequestDetail
        requestId={selectedId}
        actions={{
          canSubmit: false,
          canCancel: false,
          canDecide:
            can("employee_request.approve") || can("employee_request.manage"),
        }}
        onClose={() => setSelectedId(null)}
        onChanged={() => void load()}
      />
    </div>
  );
}
