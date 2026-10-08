import { useCallback, useEffect, useState } from "react";
import { useSession } from "../App";
import {
  getEmployee,
  listEmployees,
  listLeaveBalances,
  listLeaveTypes,
  type LeaveBalance,
  type LeaveType,
} from "../api";
import SearchSelect from "../components/SearchSelect";
import {
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  inputClass,
  labelClass,
} from "../ui";

export default function LeaveBalancesPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [employeeId, setEmployeeId] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [asOf, setAsOf] = useState("");
  const [balances, setBalances] = useState<LeaveBalance[]>([]);
  const [types, setTypes] = useState<LeaveType[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const loadTypes = useCallback(async () => {
    if (companyId === null) {
      return;
    }
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

  useEffect(() => {
    void loadTypes();
  }, [loadTypes]);

  const load = useCallback(async () => {
    if (!employeeId) {
      setBalances([]);
      setLoaded(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await listLeaveBalances({
        employee_id: Number(employeeId),
        leave_type_id: typeFilter ? Number(typeFilter) : undefined,
        as_of: asOf || undefined,
      });
      setBalances(res.items);
      setLoaded(true);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [employeeId, typeFilter, asOf, t]);

  if (!can("leave_balance.view")) {
    return (
      <div className="py-8">
        <p className={errorTextClass}>{t("error.forbidden")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 py-8">
      <h1 className="text-xl font-semibold">
        {t("leaveBalances.heading")}
      </h1>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void load();
        }}
        className="flex flex-wrap items-end gap-3"
      >
        <div className="min-w-64 flex-1">
          <SearchSelect
            label={t("leaveBalances.employee")}
            value={employeeId}
            onChange={setEmployeeId}
            load={async (search) => {
              if (!companyId) return [];
              const res = await listEmployees({
                company_id: companyId,
                search: search || undefined,
                limit: 20,
              });
              return res.items.map((e) => ({
                id: e.id,
                label: `${e.employee_number} — ${e.first_name_en} ${e.last_name_en}`,
              }));
            }}
            resolve={async (id) => {
              const emp = await getEmployee(id);
              return `${emp.employee_number} — ${emp.first_name_en} ${emp.last_name_en}`;
            }}
            placeholder={t("common.search")}
          />
        </div>
        <label className="min-w-40 flex-1">
          <span className={labelClass}>{t("leave.filters.leaveType")}</span>
          <select
            value={typeFilter}
            onChange={(event) => setTypeFilter(event.target.value)}
            className={inputClass}
          >
            <option value="">—</option>
            {types.map((type) => (
              <option key={type.id} value={String(type.id)}>
                {type.name_en}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-40 flex-1">
          <span className={labelClass}>{t("leaveBalances.asOf")}</span>
          <input
            type="date"
            value={asOf}
            onChange={(event) => setAsOf(event.target.value)}
            className={inputClass}
          />
        </label>
        <button type="submit" className={ghostButtonClass}>
          {t("common.search")}
        </button>
      </form>

      {error ? <p className={errorTextClass}>{error}</p> : null}

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        {!employeeId ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {t("leaveBalances.selectEmployee")}
          </p>
        ) : loading ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {t("common.loading")}
          </p>
        ) : loaded && balances.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {t("leaveBalances.empty")}
          </p>
        ) : balances.length > 0 ? (
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
                  <th className="py-2 text-start">
                    {t("leaveBalances.negativeAllowed")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {balances.map((row) => (
                  <tr key={row.leave_type_id} className="border-b border-slate-100">
                    <td className="py-2">
                      {row.name_en}{" "}
                      <span className="font-mono text-xs text-slate-400">
                        {row.code}
                      </span>
                    </td>
                    <td className="py-2">{Number(row.allocated_days)}</td>
                    <td className="py-2">{Number(row.used_days)}</td>
                    <td className="py-2">{Number(row.pending_days)}</td>
                    <td className="py-2 font-medium">
                      {Number(row.remaining_days)}
                    </td>
                    <td className="py-2">
                      {row.negative_balance_allowed ? "✓" : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="py-6 text-center text-sm text-slate-500">
            {t("common.empty")}
          </p>
        )}
      </section>
    </div>
  );
}
