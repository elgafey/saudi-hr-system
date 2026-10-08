import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../App";
import {
  listDepartments,
  listEmployees,
  type Department,
  type Employee,
  type PageMeta,
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

export default function EmployeesPage() {
  const { t, can, me } = useSession();
  const navigate = useNavigate();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<Employee[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [meta, setMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [departmentFilter, setDepartmentFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await listEmployees({
        company_id: companyId,
        page,
        page_size: pageSize,
        search: search || undefined,
        status: statusFilter || undefined,
        department_id: departmentFilter ? Number(departmentFilter) : undefined,
      });
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error")));
    } finally {
      setLoading(false);
    }
  }, [companyId, page, search, statusFilter, departmentFilter, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (companyId === null) {
      return;
    }
    let cancelled = false;
    listDepartments({ company_id: companyId, page: 1, page_size: 200 })
      .then((res) => {
        if (!cancelled) {
          setDepartments(res.items);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  const departmentName = (id: number | null): string => {
    if (id === null) {
      return "—";
    }
    const found = departments.find((row) => row.id === id);
    return found ? found.name_en : `#${id}`;
  };

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{t("employees.heading")}</h1>
        {can("employee.create") ? (
          <button
            type="button"
            onClick={() => navigate("/employees/new")}
            className={primaryButtonClass}
          >
            + {t("employees.new")}
          </button>
        ) : null}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setSearch(searchInput.trim());
          setPage(1);
        }}
        className="flex flex-wrap items-end gap-3"
      >
        <label className="min-w-48 flex-1">
          <span className={labelClass}>{t("common.search")}</span>
          <input
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            className={inputClass}
            maxLength={100}
          />
        </label>
        <label>
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
            <option value="draft">{t("status.draft")}</option>
            <option value="active">{t("status.active")}</option>
            <option value="suspended">{t("status.suspended")}</option>
            <option value="terminated">{t("status.terminated")}</option>
          </select>
        </label>
        <label>
          <span className={labelClass}>{t("employees.department")}</span>
          <select
            value={departmentFilter}
            onChange={(event) => {
              setDepartmentFilter(event.target.value);
              setPage(1);
            }}
            className={inputClass}
          >
            <option value="">{t("positions.departmentFilter")}</option>
            {departments.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name_en}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className={ghostButtonClass}>
          {t("common.search")}
        </button>
      </form>

      {error ? <p className={errorTextClass}>{error}</p> : null}

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        {loading ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {t("common.loading")}
          </p>
        ) : items.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {search || statusFilter || departmentFilter
              ? t("common.empty")
              : t("employees.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="py-2 text-start">{t("employees.number")}</th>
                  <th className="py-2 text-start">{t("common.nameEn")}</th>
                  <th className="py-2 text-start">
                    {t("employees.department")}
                  </th>
                  <th className="py-2 text-start">{t("employees.position")}</th>
                  <th className="py-2 text-start">{t("common.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2 font-mono text-xs">
                      {row.employee_number}
                    </td>
                    <td className="py-2">{row.first_name_en} {row.last_name_en}</td>
                    <td className="py-2">{departmentName(row.department_id)}</td>
                    <td className="py-2">
                      {row.job_position_id ? `#${row.job_position_id}` : "—"}
                    </td>
                    <td className="py-2">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                        {t(`status.${row.status}`)}
                      </span>
                    </td>
                    <td className="py-2">
                      <button
                        type="button"
                        onClick={() => navigate(`/employees/${row.id}`)}
                        className="text-blue-600 hover:underline"
                      >
                        {t("employees.view")}
                      </button>
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
