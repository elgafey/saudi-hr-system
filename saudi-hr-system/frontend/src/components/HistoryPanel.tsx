import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSession } from "../App";
import {
  createEmploymentHistory,
  getDepartment,
  getEmployee,
  getJobGrade,
  getJobPosition,
  listBranches,
  listDepartments,
  listEmploymentHistory,
  listEmployees,
  listJobGrades,
  listJobPositions,
  type Branch,
  type EmploymentHistory,
  type PageMeta,
} from "../api";
import SearchSelect, { type SearchOption } from "./SearchSelect";
import Pagination from "./Pagination";
import {
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../ui";

const pageSize = 10;

interface HistoryFormState {
  effective_from: string;
  effective_to: string;
  employment_status: string;
  employment_type: string;
  branch_id: string;
  department_id: string;
  position_id: string;
  grade_id: string;
  manager_id: string;
  change_reason: string;
  notes: string;
  apply_to_employee: boolean;
}

const emptyForm: HistoryFormState = {
  effective_from: "",
  effective_to: "",
  employment_status: "active",
  employment_type: "full_time",
  branch_id: "",
  department_id: "",
  position_id: "",
  grade_id: "",
  manager_id: "",
  change_reason: "",
  notes: "",
  apply_to_employee: true,
};

function nullable(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function optionalId(value: string): number | null {
  return value === "" ? null : Number(value);
}

interface NameMaps {
  branches: Record<number, string>;
  departments: Record<number, string>;
  positions: Record<number, string>;
  grades: Record<number, string>;
  managers: Record<number, string>;
}

const emptyNames: NameMaps = {
  branches: {},
  departments: {},
  positions: {},
  grades: {},
  managers: {},
};

interface Props {
  employeeId: number;
  companyId: number;
}

export default function HistoryPanel({ employeeId, companyId }: Props) {
  const { t, can } = useSession();
  const [rows, setRows] = useState<EmploymentHistory[]>([]);
  const [names, setNames] = useState<NameMaps>(emptyNames);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [meta, setMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<HistoryFormState | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (key: keyof HistoryFormState, value: string | boolean) =>
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listEmploymentHistory(employeeId, {
        page,
        page_size: pageSize,
      });
      setRows(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [employeeId, page, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    listBranches(companyId)
      .then((items) => {
        if (!cancelled) {
          setBranches(items);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  useEffect(() => {
    if (rows.length === 0) {
      return;
    }
    let cancelled = false;
    const unique = (values: (number | null)[]) => [
      ...new Set(values.filter((value): value is number => value !== null)),
    ];
    const deptIds = unique(rows.map((row) => row.department_id));
    const positionIds = unique(rows.map((row) => row.position_id));
    const gradeIds = unique(rows.map((row) => row.grade_id));
    const managerIds = unique(rows.map((row) => row.manager_id));

    const jobs: Promise<void>[] = [];
    const collected: NameMaps = {
      branches: {},
      departments: {},
      positions: {},
      grades: {},
      managers: {},
    };

    for (const id of deptIds) {
      jobs.push(
        getDepartment(id)
          .then((row) => {
            collected.departments[id] = row.name_en;
          })
          .catch(() => undefined),
      );
    }
    for (const id of positionIds) {
      jobs.push(
        getJobPosition(id)
          .then((row) => {
            collected.positions[id] = row.name_en;
          })
          .catch(() => undefined),
      );
    }
    for (const id of gradeIds) {
      jobs.push(
        getJobGrade(id)
          .then((row) => {
            collected.grades[id] = `L${row.level} — ${row.name_en}`;
          })
          .catch(() => undefined),
      );
    }
    for (const id of managerIds) {
      jobs.push(
        getEmployee(id)
          .then((row) => {
            collected.managers[id] = `${row.employee_number} — ${row.first_name_en} ${row.last_name_en}`;
          })
          .catch(() => undefined),
      );
    }

    void Promise.all(jobs).then(() => {
      if (!cancelled) {
        setNames(collected);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [rows, companyId]);

  function nameOf(map: Record<number, string>, id: number | null): string {
    if (id === null) {
      return "—";
    }
    return map[id] ?? `#${id}`;
  }

  function loadOptions<T extends { id: number; name_en: string }>(
    loader: (params: {
      company_id: number;
      search: string;
      page: number;
      page_size: number;
    }) => Promise<{ items: T[] }>,
    search: string,
    label: (row: T) => string,
  ): Promise<SearchOption[]> {
    if (companyId === null) {
      return Promise.resolve([]);
    }
    return loader({
      company_id: companyId,
      search,
      page: 1,
      page_size: 10,
    }).then((page) => page.items.map((row) => ({ id: row.id, label: label(row) })));
  }

  const loadDepartments = (search: string) =>
    loadOptions(listDepartments, search, (row) => row.name_en);
  const loadPositions = (search: string) =>
    loadOptions(listJobPositions, search, (row) => row.name_en);
  const loadGrades = (search: string) =>
    loadOptions(listJobGrades, search, (row) => `L${row.level} — ${row.name_en}`);
  function loadManagers(search: string): Promise<SearchOption[]> {
    if (companyId === null) {
      return Promise.resolve([]);
    }
    return listEmployees({
      company_id: companyId,
      search,
      page: 1,
      page_size: 10,
    }).then((page) =>
      page.items.map((row) => ({
        id: row.id,
        label: `${row.employee_number} — ${row.first_name_en} ${row.last_name_en}`,
      })),
    );
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (form === null || form.effective_from === "") {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createEmploymentHistory(employeeId, {
        company_id: companyId,
        effective_from: form.effective_from,
        effective_to: nullable(form.effective_to),
        employment_status: form.employment_status,
        employment_type: form.employment_type,
        branch_id: optionalId(form.branch_id),
        department_id: optionalId(form.department_id),
        position_id: optionalId(form.position_id),
        grade_id: optionalId(form.grade_id),
        manager_id: optionalId(form.manager_id),
        change_reason: nullable(form.change_reason),
        notes: nullable(form.notes),
        apply_to_employee: form.apply_to_employee,
      });
      setForm(null);
      setPage(1);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t("history.title")}</h2>
        {can("employee_history.create") && form === null ? (
          <button type="button" onClick={() => setForm({ ...emptyForm })} className={primaryButtonClass}>
            {t("history.new")}
          </button>
        ) : null}
      </div>

      {error ? <p className={errorTextClass}>{error}</p> : null}

      {form ? (
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-3">
          <label className="block">
            <span className={labelClass}>{t("history.from")}</span>
            <input
              type="date"
              required
              value={form.effective_from}
              onChange={(event) => set("effective_from", event.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block">
            <span className={labelClass}>{t("history.to")}</span>
            <input
              type="date"
              value={form.effective_to}
              onChange={(event) => set("effective_to", event.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block">
            <span className={labelClass}>{t("common.status")}</span>
            <select
              value={form.employment_status}
              onChange={(event) => set("employment_status", event.target.value)}
              className={inputClass}
            >
              <option value="draft">{t("status.draft")}</option>
              <option value="active">{t("status.active")}</option>
              <option value="suspended">{t("status.suspended")}</option>
              <option value="terminated">{t("status.terminated")}</option>
            </select>
          </label>
          <label className="block">
            <span className={labelClass}>{t("employees.employmentType")}</span>
            <select
              value={form.employment_type}
              onChange={(event) => set("employment_type", event.target.value)}
              className={inputClass}
            >
              <option value="full_time">{t("empType.full_time")}</option>
              <option value="part_time">{t("empType.part_time")}</option>
              <option value="temporary">{t("empType.temporary")}</option>
              <option value="intern">{t("empType.intern")}</option>
            </select>
          </label>
          <label className="block">
            <span className={labelClass}>{t("employees.branch")}</span>
            <select
              value={form.branch_id}
              onChange={(event) => set("branch_id", event.target.value)}
              className={inputClass}
            >
              <option value="">—</option>
              {branches.map((row) => (
                <option key={row.id} value={String(row.id)}>
                  {row.code} — {row.name}
                </option>
              ))}
            </select>
          </label>
          <SearchSelect
            label={t("employees.department")}
            value={form.department_id}
            onChange={(value) => set("department_id", value)}
            load={loadDepartments}
            resolve={(id) => getDepartment(id).then((row) => row.name_en)}
          />
          <SearchSelect
            label={t("employees.position")}
            value={form.position_id}
            onChange={(value) => set("position_id", value)}
            load={loadPositions}
            resolve={(id) => getJobPosition(id).then((row) => row.name_en)}
          />
          <SearchSelect
            label={t("employees.grade")}
            value={form.grade_id}
            onChange={(value) => set("grade_id", value)}
            load={loadGrades}
            resolve={(id) =>
              getJobGrade(id).then((row) => `L${row.level} — ${row.name_en}`)
            }
          />
          <SearchSelect
            label={t("employees.manager")}
            value={form.manager_id}
            onChange={(value) => set("manager_id", value)}
            load={loadManagers}
            resolve={(id) =>
              getEmployee(id).then(
                (row) =>
                  `${row.employee_number} — ${row.first_name_en} ${row.last_name_en}`,
              )
            }
          />
          <label className="block sm:col-span-2">
            <span className={labelClass}>{t("history.reason")}</span>
            <input
              type="text"
              maxLength={100}
              value={form.change_reason}
              onChange={(event) => set("change_reason", event.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block sm:col-span-2">
            <span className={labelClass}>{t("employees.notes")}</span>
            <textarea
              rows={2}
              maxLength={2000}
              value={form.notes}
              onChange={(event) => set("notes", event.target.value)}
              className={inputClass}
            />
          </label>
          <label className="flex items-center gap-2 text-sm sm:col-span-3">
            <input
              type="checkbox"
              checked={form.apply_to_employee}
              onChange={(event) => set("apply_to_employee", event.target.checked)}
            />
            {t("history.apply")}
          </label>
          <div className="flex gap-2 sm:col-span-3">
            <button type="submit" disabled={saving} className={primaryButtonClass}>
              {saving ? t("common.saving") : t("common.save")}
            </button>
            <button
              type="button"
              onClick={() => setForm(null)}
              className={ghostButtonClass}
            >
              {t("common.cancel")}
            </button>
          </div>
        </form>
      ) : null}

      {loading ? (
        <p className="text-sm text-slate-500">{t("common.loading")}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500">{t("history.empty")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-2 pr-3">{t("history.range")}</th>
                <th className="py-2 pr-3">{t("common.status")}</th>
                <th className="py-2 pr-3">{t("employees.employmentType")}</th>
                <th className="py-2 pr-3">{t("employees.department")}</th>
                <th className="py-2 pr-3">{t("employees.position")}</th>
                <th className="py-2 pr-3">{t("history.reason")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-slate-100">
                  <td className="py-2 pr-3 text-xs">
                    {row.effective_from} → {row.effective_to ?? "…"}
                  </td>
                  <td className="py-2 pr-3">
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                      {t(`status.${row.employment_status}`)}
                    </span>
                  </td>
                  <td className="py-2 pr-3">{t(`empType.${row.employment_type}`)}</td>
                  <td className="py-2 pr-3">
                    {nameOf(names.departments, row.department_id)}
                  </td>
                  <td className="py-2 pr-3">
                    {nameOf(names.positions, row.position_id)}
                  </td>
                  <td className="py-2 pr-3 text-xs">{row.change_reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Pagination meta={meta} onPage={setPage} />
    </section>
  );
}
