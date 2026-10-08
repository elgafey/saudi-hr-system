import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  createShift,
  deleteShift,
  listShifts,
  updateShift,
  type Shift,
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

interface ShiftFormState {
  code: string;
  name_ar: string;
  name_en: string;
  start_time: string;
  end_time: string;
  status: string;
  notes: string;
}

const emptyShiftForm: ShiftFormState = {
  code: "",
  name_ar: "",
  name_en: "",
  start_time: "09:00",
  end_time: "17:00",
  status: "active",
  notes: "",
};

export default function ShiftsPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<Shift[]>([]);
  const [meta, setMeta] = useState<{ page: number; page_size: number; total: number }>({
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
  const [editing, setEditing] = useState<Shift | null>(null);
  const [shiftForm, setShiftForm] = useState<ShiftFormState>(emptyShiftForm);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await listShifts({
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
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [companyId, page, search, statusFilter, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditing(null);
    setShiftForm(emptyShiftForm);
    setFormOpen(true);
    setError(null);
  }

  function openEdit(row: Shift) {
    setEditing(row);
    setShiftForm({
      code: row.code,
      name_ar: row.name_ar,
      name_en: row.name_en,
      start_time: row.start_time,
      end_time: row.end_time,
      status: row.status,
      notes: row.notes ?? "",
    });
    setFormOpen(true);
    setError(null);
  }

  async function submitShift(event: FormEvent) {
    event.preventDefault();
    if (companyId === null) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await updateShift(editing.id, {
          code: shiftForm.code.trim(),
          name_ar: shiftForm.name_ar.trim(),
          name_en: shiftForm.name_en.trim(),
          start_time: shiftForm.start_time,
          end_time: shiftForm.end_time,
          status: shiftForm.status,
          notes: shiftForm.notes.trim() || null,
        });
      } else {
        await createShift({
          company_id: companyId,
          code: shiftForm.code.trim(),
          name_ar: shiftForm.name_ar.trim(),
          name_en: shiftForm.name_en.trim(),
          start_time: shiftForm.start_time,
          end_time: shiftForm.end_time,
          status: shiftForm.status,
          notes: shiftForm.notes.trim() || null,
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

  async function removeShift(row: Shift) {
    if (!window.confirm(t("shifts.deleteConfirm"))) {
      return;
    }
    try {
      await deleteShift(row.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  const canCreate = can("shift.create");
  const canUpdate = can("shift.update");
  const canDelete = can("shift.delete");

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{t("shifts.heading")}</h1>
        {canCreate ? (
          <button type="button" onClick={openCreate} className={primaryButtonClass}>
            + {t("shifts.new")}
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
            <option value="archived">{t("status.archived")}</option>
          </select>
        </label>
        <button type="submit" className={ghostButtonClass}>
          {t("common.search")}
        </button>
      </form>

      {formOpen ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {editing ? t("shifts.edit") : t("shifts.new")}
          </h2>
          <form onSubmit={submitShift} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("common.code")}</span>
              <input
                required
                maxLength={50}
                value={shiftForm.code}
                onChange={(event) =>
                  setShiftForm({ ...shiftForm, code: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("common.status")}</span>
              <select
                value={shiftForm.status}
                onChange={(event) =>
                  setShiftForm({ ...shiftForm, status: event.target.value })
                }
                className={inputClass}
              >
                <option value="active">{t("status.active")}</option>
                <option value="archived">{t("status.archived")}</option>
              </select>
            </label>
            <label>
              <span className={labelClass}>{t("common.nameEn")}</span>
              <input
                required
                maxLength={255}
                value={shiftForm.name_en}
                onChange={(event) =>
                  setShiftForm({ ...shiftForm, name_en: event.target.value })
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
                value={shiftForm.name_ar}
                onChange={(event) =>
                  setShiftForm({ ...shiftForm, name_ar: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("schedules.startTime")}</span>
              <input
                type="time"
                required
                value={shiftForm.start_time}
                onChange={(event) =>
                  setShiftForm({ ...shiftForm, start_time: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("schedules.endTime")}</span>
              <input
                type="time"
                required
                value={shiftForm.end_time}
                onChange={(event) =>
                  setShiftForm({ ...shiftForm, end_time: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label className="sm:col-span-2">
              <span className={labelClass}>{t("shifts.crossesMidnight")}</span>
              <input
                type="checkbox"
                checked={shiftForm.end_time < shiftForm.start_time}
                disabled
                className="rounded border border-slate-300"
              />
            </label>
            <label className="sm:col-span-2">
              <span className={labelClass}>{t("common.description")}</span>
              <input
                maxLength={500}
                value={shiftForm.notes}
                onChange={(event) =>
                  setShiftForm({ ...shiftForm, notes: event.target.value })
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
            {search || statusFilter ? t("common.empty") : t("shifts.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("common.code")}</th>
                  <th className="py-2 text-start">{t("common.nameEn")}</th>
                  <th className="py-2 text-start">{t("common.nameAr")}</th>
                  <th className="py-2 text-start">{t("schedules.startTime")}</th>
                  <th className="py-2 text-start">{t("schedules.endTime")}</th>
                  <th className="py-2 text-start">{t("shifts.crossesMidnight")}</th>
                  <th className="py-2 text-start">{t("common.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2 font-mono text-xs">{row.code}</td>
                    <td className="py-2">{row.name_en}</td>
                    <td className="py-2" dir="rtl">{row.name_ar}</td>
                    <td className="py-2">{row.start_time}</td>
                    <td className="py-2">{row.end_time}</td>
                    <td className="py-2">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                        {row.crosses_midnight ? t("schedules.overnight") : "—"}
                      </span>
                    </td>
                    <td className="py-2">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                        {t(`status.${row.status}`)}
                      </span>
                    </td>
                    <td className="py-2">
                      <div className="flex gap-2">
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
                            onClick={() => void removeShift(row)}
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