import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSession } from "../App";
import {
  createJobGrade,
  deleteJobGrade,
  listJobGrades,
  updateJobGrade,
  type JobGrade,
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

interface FormState {
  code: string;
  name_ar: string;
  name_en: string;
  level: string;
  description: string;
  status: string;
}

const emptyForm: FormState = {
  code: "",
  name_ar: "",
  name_en: "",
  level: "1",
  description: "",
  status: "active",
};

const pageSize = 20;

export default function JobGradesPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<JobGrade[]>([]);
  const [meta, setMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<JobGrade | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await listJobGrades({
        company_id: companyId,
        page,
        page_size: pageSize,
        search: search || undefined,
        status: statusFilter || undefined,
      });
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error")));
    } finally {
      setLoading(false);
    }
  }, [companyId, page, search, statusFilter, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditing(null);
    setForm(emptyForm);
    setFormOpen(true);
    setError(null);
  }

  function openEdit(row: JobGrade) {
    setEditing(row);
    setForm({
      code: row.code,
      name_ar: row.name_ar,
      name_en: row.name_en,
      level: String(row.level),
      description: row.description ?? "",
      status: row.status,
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
      const common = {
        code: form.code.trim(),
        name_ar: form.name_ar.trim(),
        name_en: form.name_en.trim(),
        level: Number(form.level),
        description: form.description.trim() || null,
        status: form.status,
      };
      if (editing) {
        await updateJobGrade(editing.id, common);
      } else {
        await createJobGrade({ company_id: companyId, ...common });
      }
      setFormOpen(false);
      setEditing(null);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed")));
    } finally {
      setSaving(false);
    }
  }

  async function remove(row: JobGrade) {
    if (!window.confirm(t("common.deleteConfirm"))) {
      return;
    }
    try {
      await deleteJobGrade(row.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed")));
    }
  }

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{t("grades.heading")}</h1>
        {can("job_grade.create") ? (
          <button type="button" onClick={openCreate} className={primaryButtonClass}>
            + {t("grades.new")}
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
            <option value="active">{t("status.active")}</option>
            <option value="inactive">{t("status.inactive")}</option>
          </select>
        </label>
        <button type="submit" className={ghostButtonClass}>
          {t("common.search")}
        </button>
      </form>

      {formOpen ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {editing ? t("grades.edit") : t("grades.new")}
          </h2>
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("common.code")}</span>
              <input
                required
                maxLength={50}
                value={form.code}
                onChange={(event) =>
                  setForm({ ...form, code: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("grades.level")}</span>
              <input
                required
                type="number"
                min={1}
                max={999}
                value={form.level}
                onChange={(event) =>
                  setForm({ ...form, level: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("common.nameEn")}</span>
              <input
                required
                maxLength={255}
                value={form.name_en}
                onChange={(event) =>
                  setForm({ ...form, name_en: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("common.nameAr")}</span>
              <input
                required
                maxLength={255}
                dir="rtl"
                value={form.name_ar}
                onChange={(event) =>
                  setForm({ ...form, name_ar: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("common.status")}</span>
              <select
                value={form.status}
                onChange={(event) =>
                  setForm({ ...form, status: event.target.value })
                }
                className={inputClass}
              >
                <option value="active">{t("status.active")}</option>
                <option value="inactive">{t("status.inactive")}</option>
              </select>
            </label>
            <label>
              <span className={labelClass}>{t("common.description")}</span>
              <input
                maxLength={500}
                value={form.description}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
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
            {search || statusFilter ? t("common.empty") : t("grades.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="py-2 text-start">{t("common.code")}</th>
                  <th className="py-2 text-start">{t("grades.level")}</th>
                  <th className="py-2 text-start">{t("common.nameEn")}</th>
                  <th className="py-2 text-start">{t("common.nameAr")}</th>
                  <th className="py-2 text-start">{t("common.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2 font-mono text-xs">{row.code}</td>
                    <td className="py-2">{row.level}</td>
                    <td className="py-2">{row.name_en}</td>
                    <td className="py-2" dir="rtl">
                      {row.name_ar}
                    </td>
                    <td className="py-2">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                        {t(`status.${row.status}`)}
                      </span>
                    </td>
                    <td className="py-2">
                      <div className="flex gap-2">
                        {can("job_grade.update") ? (
                          <button
                            type="button"
                            onClick={() => openEdit(row)}
                            className="text-blue-600 hover:underline"
                          >
                            {t("common.edit")}
                          </button>
                        ) : null}
                        {can("job_grade.delete") ? (
                          <button
                            type="button"
                            onClick={() => void remove(row)}
                            className="text-red-600 hover:underline"
                          >
                            {t("common.delete")}
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
