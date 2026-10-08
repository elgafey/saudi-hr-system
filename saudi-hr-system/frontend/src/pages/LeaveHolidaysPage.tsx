import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  createCompanyHoliday,
  deleteCompanyHoliday,
  listCompanyHolidays,
  updateCompanyHoliday,
  type CompanyHoliday,
  type HolidayPageParams,
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

interface HolidayFormState {
  date: string;
  name_ar: string;
  name_en: string;
  status: string;
  notes: string;
}

const emptyForm: HolidayFormState = {
  date: "",
  name_ar: "",
  name_en: "",
  status: "active",
  notes: "",
};

export default function LeaveHolidaysPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<CompanyHoliday[]>([]);
  const [meta, setMeta] = useState<{
    page: number;
    page_size: number;
    total: number;
  }>({ page: 1, page_size: pageSize, total: 0 });
  const [page, setPage] = useState(1);
  const [yearFilter, setYearFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<CompanyHoliday | null>(null);
  const [form, setForm] = useState<HolidayFormState>(emptyForm);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: HolidayPageParams = {
        company_id: companyId,
        page,
        page_size: pageSize,
        year: yearFilter ? Number(yearFilter) : undefined,
        status: statusFilter || undefined,
      };
      const res = await listCompanyHolidays(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [companyId, page, yearFilter, statusFilter, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditing(null);
    setForm(emptyForm);
    setFormOpen(true);
    setError(null);
  }

  function openEdit(row: CompanyHoliday) {
    setEditing(row);
    setForm({
      date: row.date,
      name_ar: row.name_ar,
      name_en: row.name_en,
      status: row.status,
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
        await updateCompanyHoliday(editing.id, {
          date: form.date,
          name_ar: form.name_ar.trim(),
          name_en: form.name_en.trim(),
          status: form.status,
          notes: form.notes.trim() || null,
        });
      } else {
        await createCompanyHoliday({
          company_id: companyId,
          date: form.date,
          name_ar: form.name_ar.trim(),
          name_en: form.name_en.trim(),
          status: form.status,
          notes: form.notes.trim() || null,
        });
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

  async function handleDelete(row: CompanyHoliday) {
    if (!window.confirm(t("leaveHolidays.deleteConfirm"))) {
      return;
    }
    setError(null);
    try {
      await deleteCompanyHoliday(row.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  const canCreate = can("leave_holiday.create");
  const canUpdate = can("leave_holiday.update");
  const canDelete = can("leave_holiday.delete");

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">
          {t("leaveHolidays.heading")}
        </h1>
        {canCreate ? (
          <button
            type="button"
            onClick={openCreate}
            className={primaryButtonClass}
          >
            + {t("leaveHolidays.new")}
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
        <label className="min-w-32 flex-1">
          <span className={labelClass}>
            {t("leaveHolidays.filters.year")}
          </span>
          <input
            type="number"
            min={1970}
            max={9999}
            value={yearFilter}
            onChange={(event) => {
              setYearFilter(event.target.value);
              setPage(1);
            }}
            className={inputClass}
          />
        </label>
        <label className="min-w-40 flex-1">
          <span className={labelClass}>{t("leave.filters.status")}</span>
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
            {editing ? t("leaveHolidays.edit") : t("leaveHolidays.new")}
          </h2>
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("leaveHolidays.date")}</span>
              <input
                required
                type="date"
                value={form.date}
                onChange={(event) =>
                  setForm({ ...form, date: event.target.value })
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
              <span className={labelClass}>{t("common.nameAr")}</span>
              <input
                required
                maxLength={255}
                value={form.name_ar}
                onChange={(event) =>
                  setForm({ ...form, name_ar: event.target.value })
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
            <label className="sm:col-span-2">
              <span className={labelClass}>{t("employees.notes")}</span>
              <input
                maxLength={1000}
                value={form.notes}
                onChange={(event) =>
                  setForm({ ...form, notes: event.target.value })
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
            {yearFilter || statusFilter
              ? t("common.empty")
              : t("leaveHolidays.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("leaveHolidays.date")}</th>
                  <th className="py-2 text-start">{t("common.nameEn")}</th>
                  <th className="py-2 text-start">{t("common.nameAr")}</th>
                  <th className="py-2 text-start">{t("common.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2">{row.date}</td>
                    <td className="py-2">{row.name_en}</td>
                    <td className="py-2">{row.name_ar}</td>
                    <td className="py-2">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                        {row.status === "active"
                          ? t("status.active")
                          : t("status.inactive")}
                      </span>
                    </td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-2">
                        {canUpdate ? (
                          <button
                            type="button"
                            onClick={() => openEdit(row)}
                            className="text-blue-600 hover:underline"
                          >
                            {t("common.edit")}
                          </button>
                        ) : null}
                        {canDelete ? (
                          <button
                            type="button"
                            onClick={() => void handleDelete(row)}
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
