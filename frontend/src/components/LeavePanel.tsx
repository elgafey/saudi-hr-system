import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useSession } from "../App";
import {
  cancelLeaveRequest,
  listLeaveBalances,
  listLeaveRequests,
  listLeaveTypes,
  myLeaveBalances,
  submitLeaveRequest,
  type LeaveBalance,
  type LeaveRequest,
  type LeaveType,
} from "../api";
import {
  errorMessage,
  errorTextClass,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../ui";

const pageSize = 10;

const STATUS_LABELS: Record<string, string> = {
  draft: "leaveRequests.status.draft",
  submitted: "leaveRequests.status.submitted",
  approved: "leaveRequests.status.approved",
  rejected: "leaveRequests.status.rejected",
  cancelled: "leaveRequests.status.cancelled",
};

interface Props {
  employeeId: number;
  companyId: number;
}

export default function LeavePanel({ employeeId, companyId }: Props) {
  const { t, can, me } = useSession();

  const [balances, setBalances] = useState<LeaveBalance[]>([]);
  const [showBalances, setShowBalances] = useState(false);
  const [requests, setRequests] = useState<LeaveRequest[]>([]);
  const [types, setTypes] = useState<LeaveType[]>([]);
  const [typeFilter, setTypeFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [balancesLoading, setBalancesLoading] = useState(true);
  const [requestsLoading, setRequestsLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);

  const isOwnRecord = me?.user.employee_id === employeeId;

  const loadTypes = useCallback(async () => {
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

  const loadBalances = useCallback(async () => {
    const canView = can("leave_balance.view");
    if (!canView && !isOwnRecord) {
      setShowBalances(false);
      setBalancesLoading(false);
      return;
    }
    setBalancesLoading(true);
    try {
      const res = canView
        ? await listLeaveBalances({ employee_id: employeeId })
        : await myLeaveBalances();
      setBalances(res.items);
      setShowBalances(true);
      setError(null);
    } catch (err) {
      setShowBalances(false);
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setBalancesLoading(false);
    }
  }, [can, employeeId, isOwnRecord, t]);

  const loadRequests = useCallback(async () => {
    setRequestsLoading(true);
    try {
      const res = await listLeaveRequests({
        company_id: companyId,
        employee_id: employeeId,
        page: 1,
        page_size: pageSize,
      });
      setRequests(res.items);
      setError(null);
    } catch (err) {
      setRequests([]);
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setRequestsLoading(false);
    }
  }, [companyId, employeeId, t]);

  useEffect(() => {
    void loadTypes();
  }, [loadTypes]);

  useEffect(() => {
    void loadBalances();
  }, [loadBalances]);

  useEffect(() => {
    void loadRequests();
  }, [loadRequests]);

  async function runAction(
    id: number,
    action: () => Promise<LeaveRequest>,
  ): Promise<boolean> {
    setBusyId(id);
    setError(null);
    try {
      await action();
      return true;
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
      return false;
    } finally {
      setBusyId(null);
    }
  }

  async function handleSubmit(row: LeaveRequest) {
    const ok = await runAction(row.id, () => submitLeaveRequest(row.id));
    if (ok) {
      await loadRequests();
      await loadBalances();
    }
  }

  async function handleCancel(row: LeaveRequest) {
    if (!window.confirm(t("leaveRequests.cancel"))) {
      return;
    }
    const reason = window.prompt(t("leaveRequests.cancelReason")) ?? "";
    const ok = await runAction(row.id, () =>
      cancelLeaveRequest(row.id, { reason: reason.trim() || null }),
    );
    if (ok) {
      await loadRequests();
      await loadBalances();
    }
  }

  const canSubmit = can("leave_request.submit");
  const canCancel = can("leave_request.cancel");
  const visibleRequests = typeFilter
    ? requests.filter((row) => String(row.leave_type_id) === typeFilter)
    : requests;

  return (
    <div className="space-y-6">
      {error ? <p className={errorTextClass}>{error}</p> : null}

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="mb-3 text-sm font-semibold">
          {t("leavePanel.balances")}
        </h2>
        {balancesLoading ? (
          <p className="py-3 text-center text-sm text-slate-500">
            {t("common.loading")}
          </p>
        ) : !showBalances ? (
          <p className="py-3 text-center text-sm text-slate-500">
            {t("leaveBalances.selectEmployee")}
          </p>
        ) : balances.length === 0 ? (
          <p className="py-3 text-center text-sm text-slate-500">
            {t("leavePanel.noBalances")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("leave.type")}</th>
                  <th className="py-2 text-start">
                    {t("leaveBalances.allocated")}
                  </th>
                  <th className="py-2 text-start">
                    {t("leaveBalances.used")}
                  </th>
                  <th className="py-2 text-start">
                    {t("leaveBalances.pending")}
                  </th>
                  <th className="py-2 text-start">
                    {t("leaveBalances.remaining")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {balances.map((row) => (
                  <tr
                    key={row.leave_type_id}
                    className="border-b border-slate-100"
                  >
                    <td className="py-2">{row.name_en}</td>
                    <td className="py-2">{Number(row.allocated_days)}</td>
                    <td className="py-2">{Number(row.used_days)}</td>
                    <td className="py-2">{Number(row.pending_days)}</td>
                    <td className="py-2 font-medium">
                      {Number(row.remaining_days)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">
            {t("leavePanel.requests")}
          </h2>
          <label className="flex items-center gap-2">
            <span className={labelClass}>
              {t("leave.filters.leaveType")}
            </span>
            <select
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value)}
              className={`${inputClass} w-auto`}
            >
              <option value="">—</option>
              {types.map((type) => (
                <option key={type.id} value={String(type.id)}>
                  {type.name_en}
                </option>
              ))}
            </select>
          </label>
        </div>
        {requestsLoading ? (
          <p className="py-3 text-center text-sm text-slate-500">
            {t("common.loading")}
          </p>
        ) : visibleRequests.length === 0 ? (
          <p className="py-3 text-center text-sm text-slate-500">
            {t("leavePanel.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("leave.type")}</th>
                  <th className="py-2 text-start">{t("leave.period")}</th>
                  <th className="py-2 text-start">{t("leave.days")}</th>
                  <th className="py-2 text-start">{t("leave.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {visibleRequests.map((row) => {
                  const isDraft = row.status === "draft";
                  const isSubmitted = row.status === "submitted";
                  const cancellable =
                    isDraft || isSubmitted || row.status === "approved";
                  const busy = busyId === row.id;
                  const typeName =
                    types.find((type) => type.id === row.leave_type_id)
                      ?.name_en ?? `#${row.leave_type_id}`;
                  return (
                    <tr key={row.id} className="border-b border-slate-100">
                      <td className="py-2">{typeName}</td>
                      <td className="py-2">
                        {row.start_date} → {row.end_date}
                      </td>
                      <td className="py-2">{Number(row.days)}</td>
                      <td className="py-2">
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                          {t(STATUS_LABELS[row.status] ?? row.status)}
                        </span>
                      </td>
                      <td className="py-2">
                        <div className="flex flex-wrap gap-2">
                          {canSubmit && isDraft ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleSubmit(row)}
                              className="text-blue-600 hover:underline disabled:opacity-50"
                            >
                              {t("leaveRequests.submit")}
                            </button>
                          ) : null}
                          {canCancel && cancellable ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleCancel(row)}
                              className="text-slate-500 hover:underline disabled:opacity-50"
                            >
                              {t("leaveRequests.cancel")}
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {can("leave_request.create") && isOwnRecord ? (
        <Link to="/leave-requests" className={primaryButtonClass}>
          + {t("leaveRequests.new")}
        </Link>
      ) : null}
    </div>
  );
}
