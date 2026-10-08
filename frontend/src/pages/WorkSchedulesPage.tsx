import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  createWorkSchedule,
  deleteWorkSchedule,
  listWorkSchedules,
  listShifts,
  updateWorkSchedule,
  getWorkScheduleDays,
  putWorkScheduleDays,
  type WorkSchedule,
  type BreakPeriodInput,
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

const WEEKDAYS = [
  { index: 0, labelEn: "Monday", labelAr: "الاثنين" },
  { index: 1, labelEn: "Tuesday", labelAr: "الثلاثاء" },
  { index: 2, labelEn: "Wednesday", labelAr: "الأربعاء" },
  { index: 3, labelEn: "Thursday", labelAr: "الخميس" },
  { index: 4, labelEn: "Friday", labelAr: "الجمعة" },
  { index: 5, labelEn: "Saturday", labelAr: "السبت" },
  { index: 6, labelEn: "Sunday", labelAr: "الأحد" },
];

const pageSize = 20;

interface ScheduleFormState {
  code: string;
  name_ar: string;
  name_en: string;
  timezone: string;
  effective_from: string;
  effective_to: string;
  status: string;
  notes: string;
}

const emptyScheduleForm: ScheduleFormState = {
  code: "",
  name_ar: "",
  name_en: "",
  timezone: "Asia/Riyadh",
  effective_from: new Date().toISOString().split("T")[0],
  effective_to: "",
  status: "active",
  notes: "",
};

interface DayFormState {
  weekday: number;
  is_working: boolean;
  start_time: string;
  end_time: string;
  shift_id: string;
  breaks: BreakPeriodInput[];
}

function emptyDayForm(weekday: number): DayFormState {
  return {
    weekday,
    is_working: weekday !== 4 && weekday !== 5,
    start_time: "09:00",
    end_time: "17:00",
    shift_id: "",
    breaks: [],
  };
}

export default function WorkSchedulesPage() {
  const { t, can, me, locale } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<WorkSchedule[]>([]);
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
  const [editing, setEditing] = useState<WorkSchedule | null>(null);
  const [scheduleForm, setScheduleForm] = useState<ScheduleFormState>(emptyScheduleForm);
  const [saving, setSaving] = useState(false);

  const [daysEditing, setDaysEditing] = useState<WorkSchedule | null>(null);
  const [dayForms, setDayForms] = useState<DayFormState[]>(
    WEEKDAYS.map((d) => emptyDayForm(d.index)),
  );
  const [daysLoading, setDaysLoading] = useState(false);
  const [daysSaving, setDaysSaving] = useState(false);
  const [shiftOptions, setShiftOptions] = useState<Shift[]>([]);

  useEffect(() => {
    if (companyId === null) {
      return;
    }
    let cancelled = false;
    listShifts({
      company_id: companyId,
      status: "active",
      page: 1,
      page_size: 100,
    })
      .then((res) => {
        if (!cancelled) {
          setShiftOptions(res.items);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await listWorkSchedules({
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
    setScheduleForm(emptyScheduleForm);
    setFormOpen(true);
    setError(null);
  }

  function openEdit(row: WorkSchedule) {
    setEditing(row);
    setScheduleForm({
      code: row.code,
      name_ar: row.name_ar,
      name_en: row.name_en,
      timezone: row.timezone,
      effective_from: row.effective_from,
      effective_to: row.effective_to ?? "",
      status: row.status,
      notes: row.notes ?? "",
    });
    setFormOpen(true);
    setError(null);
  }

  async function submitSchedule(event: FormEvent) {
    event.preventDefault();
    if (companyId === null) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await updateWorkSchedule(editing.id, {
          code: scheduleForm.code.trim(),
          name_ar: scheduleForm.name_ar.trim(),
          name_en: scheduleForm.name_en.trim(),
          timezone: scheduleForm.timezone.trim(),
          effective_from: scheduleForm.effective_from,
          effective_to: scheduleForm.effective_to || null,
          status: scheduleForm.status,
          notes: scheduleForm.notes.trim() || null,
        });
      } else {
        await createWorkSchedule({
          company_id: companyId,
          code: scheduleForm.code.trim(),
          name_ar: scheduleForm.name_ar.trim(),
          name_en: scheduleForm.name_en.trim(),
          timezone: scheduleForm.timezone.trim(),
          effective_from: scheduleForm.effective_from,
          effective_to: scheduleForm.effective_to || null,
          status: scheduleForm.status,
          notes: scheduleForm.notes.trim() || null,
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

  async function removeSchedule(row: WorkSchedule) {
    if (!window.confirm(t("schedules.deleteConfirm"))) {
      return;
    }
    try {
      await deleteWorkSchedule(row.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  async function openDays(row: WorkSchedule) {
    setDaysEditing(row);
    setDaysLoading(true);
    try {
      const res = await getWorkScheduleDays(row.id);
      const dayMap = new Map(res.items.map((d) => [d.weekday, d]));
      const forms: DayFormState[] = WEEKDAYS.map((d) => {
        const existing = dayMap.get(d.index);
        if (existing) {
          return {
            weekday: existing.weekday,
            is_working: existing.is_working,
            start_time: existing.start_time ?? "",
            end_time: existing.end_time ?? "",
            shift_id: existing.shift_id ? String(existing.shift_id) : "",
            breaks: (existing.breaks ?? []).map((brk) => ({
              start_time: brk.start_time,
              end_time: brk.end_time,
              is_paid: brk.is_paid,
            })),
          };
        }
        return emptyDayForm(d.index);
      });
      setDayForms(forms);
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setDaysLoading(false);
    }
  }

  function updateDayForm(weekday: number, field: keyof DayFormState, value: unknown) {
    setDayForms((prev) =>
      prev.map((d) => (d.weekday === weekday ? { ...d, [field]: value } : d)),
    );
  }

  function addBreak(weekday: number) {
    setDayForms((prev) =>
      prev.map((d) =>
        d.weekday === weekday
          ? { ...d, breaks: [...d.breaks, { start_time: "12:00", end_time: "13:00", is_paid: true }] }
          : d,
      ),
    );
  }

  function removeBreak(weekday: number, index: number) {
    setDayForms((prev) =>
      prev.map((d) =>
        d.weekday === weekday
          ? { ...d, breaks: d.breaks.filter((_, i) => i !== index) }
          : d,
      ),
    );
  }

  function updateBreak(weekday: number, index: number, field: keyof BreakPeriodInput, value: unknown) {
    setDayForms((prev) =>
      prev.map((d) =>
        d.weekday === weekday
          ? {
              ...d,
              breaks: d.breaks.map((b, i) =>
                i === index ? { ...b, [field]: value } : b,
              ),
            }
          : d,
      ),
    );
  }

  async function submitDays(event: FormEvent) {
    event.preventDefault();
    if (daysEditing === null) {
      return;
    }
    for (const d of dayForms) {
      if (
        d.is_working &&
        !d.shift_id &&
        Boolean(d.start_time) !== Boolean(d.end_time)
      ) {
        setError(t("error.SCHEDULE_INVALID_TIME_RANGE"));
        return;
      }
    }
    setDaysSaving(true);
    setError(null);
    try {
      const days = dayForms.map((d) => {
        if (!d.is_working) {
          return {
            weekday: d.weekday,
            is_working: false,
            start_time: null,
            end_time: null,
            shift_id: null,
            breaks: [],
          };
        }
        const hasShift = Boolean(d.shift_id);
        return {
          weekday: d.weekday,
          is_working: true,
          start_time: hasShift
            ? null
            : d.start_time
              ? d.start_time
              : null,
          end_time: hasShift ? null : d.end_time ? d.end_time : null,
          shift_id: hasShift ? Number(d.shift_id) : null,
          breaks: d.breaks,
        };
      });
      await putWorkScheduleDays(daysEditing.id, { days });
      setDaysEditing(null);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setDaysSaving(false);
    }
  }

  const canCreate = can("work_schedule.create");
  const canUpdate = can("work_schedule.update");
  const canDelete = can("work_schedule.delete");

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{t("schedules.heading")}</h1>
        {canCreate ? (
          <button type="button" onClick={openCreate} className={primaryButtonClass}>
            + {t("schedules.new")}
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
            {editing ? t("schedules.edit") : t("schedules.new")}
          </h2>
          <form onSubmit={submitSchedule} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("common.code")}</span>
              <input
                required
                maxLength={50}
                value={scheduleForm.code}
                onChange={(event) =>
                  setScheduleForm({ ...scheduleForm, code: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("common.status")}</span>
              <select
                value={scheduleForm.status}
                onChange={(event) =>
                  setScheduleForm({ ...scheduleForm, status: event.target.value })
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
                value={scheduleForm.name_en}
                onChange={(event) =>
                  setScheduleForm({ ...scheduleForm, name_en: event.target.value })
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
                value={scheduleForm.name_ar}
                onChange={(event) =>
                  setScheduleForm({ ...scheduleForm, name_ar: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("schedules.timezone")}</span>
              <input
                required
                maxLength={64}
                value={scheduleForm.timezone}
                onChange={(event) =>
                  setScheduleForm({ ...scheduleForm, timezone: event.target.value })
                }
                className={inputClass}
                placeholder="Asia/Riyadh"
              />
            </label>
            <label>
              <span className={labelClass}>{t("schedules.effectiveFrom")}</span>
              <input
                type="date"
                required
                value={scheduleForm.effective_from}
                onChange={(event) =>
                  setScheduleForm({ ...scheduleForm, effective_from: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("schedules.effectiveTo")}</span>
              <input
                type="date"
                value={scheduleForm.effective_to}
                onChange={(event) =>
                  setScheduleForm({ ...scheduleForm, effective_to: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label className="sm:col-span-2">
              <span className={labelClass}>{t("common.description")}</span>
              <input
                maxLength={500}
                value={scheduleForm.notes}
                onChange={(event) =>
                  setScheduleForm({ ...scheduleForm, notes: event.target.value })
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

      {daysEditing ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {t("schedules.days")} — {daysEditing.name_en}
          </h2>
          <form onSubmit={submitDays} className="space-y-4">
            {daysLoading ? (
              <p className="text-center text-slate-500">{t("common.loading")}</p>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 text-start text-slate-500">
                        <th className="py-2 text-start">{t("schedules.day")}</th>
                        <th className="py-2 text-start">{t("schedules.isWorking")}</th>
                        <th className="py-2 text-start">{t("schedules.startTime")}</th>
                        <th className="py-2 text-start">{t("schedules.endTime")}</th>
                        <th className="py-2 text-start">{t("schedules.shift")}</th>
                        <th className="py-2 text-start">{t("schedules.breaks")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dayForms.map((day) => (
                        <tr key={day.weekday} className="border-b border-slate-100">
                          <td className="py-2 font-medium">
                            {locale === "ar"
                              ? WEEKDAYS.find((d) => d.index === day.weekday)
                                  ?.labelAr
                              : WEEKDAYS.find((d) => d.index === day.weekday)
                                  ?.labelEn}
                          </td>
                          <td className="py-2">
                            <input
                              type="checkbox"
                              checked={day.is_working}
                              onChange={(event) =>
                                updateDayForm(day.weekday, "is_working", event.target.checked)
                              }
                            />
                          </td>
                          <td className="py-2">
                            <input
                              type="time"
                              value={day.start_time}
                              onChange={(event) =>
                                updateDayForm(day.weekday, "start_time", event.target.value)
                              }
                              disabled={!day.is_working}
                              className={inputClass}
                            />
                          </td>
                          <td className="py-2">
                            <input
                              type="time"
                              value={day.end_time}
                              onChange={(event) =>
                                updateDayForm(day.weekday, "end_time", event.target.value)
                              }
                              disabled={!day.is_working}
                              className={inputClass}
                            />
                          </td>
                          <td className="py-2">
                            <select
                              value={day.shift_id}
                              onChange={(event) =>
                                updateDayForm(day.weekday, "shift_id", event.target.value)
                              }
                              disabled={!day.is_working}
                              className={inputClass}
                            >
                              <option value="">—</option>
                              {shiftOptions.map((shift) => (
                                <option key={shift.id} value={shift.id}>
                                  {shift.code} — {shift.name_en}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="py-2">
                            <div className="space-y-1">
                              {day.breaks.map((brk, i) => (
                                <div key={i} className="flex gap-1 items-center">
                                  <input
                                    type="time"
                                    value={brk.start_time}
                                    onChange={(event) =>
                                      updateBreak(day.weekday, i, "start_time", event.target.value)
                                    }
                                    className={inputClass}
                                  />
                                  <span>–</span>
                                  <input
                                    type="time"
                                    value={brk.end_time}
                                    onChange={(event) =>
                                      updateBreak(day.weekday, i, "end_time", event.target.value)
                                    }
                                    className={inputClass}
                                  />
                                  <label className="flex items-center gap-1 text-sm">
                                    <input
                                      type="checkbox"
                                      checked={brk.is_paid}
                                      onChange={(event) =>
                                        updateBreak(day.weekday, i, "is_paid", event.target.checked)
                                      }
                                    />
                                    {t("schedules.breakPaid")}
                                  </label>
                                  <button
                                    type="button"
                                    onClick={() => removeBreak(day.weekday, i)}
                                    className="text-red-600 hover:underline text-sm"
                                  >
                                    ×
                                  </button>
                                </div>
                              ))}
                              <button
                                type="button"
                                onClick={() => addBreak(day.weekday)}
                                className="text-sm text-blue-600 hover:underline"
                              >
                                + {t("schedules.breaks")}
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={daysSaving}
                    className={primaryButtonClass}
                  >
                    {daysSaving ? t("common.saving") : t("common.save")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setDaysEditing(null)}
                    className={ghostButtonClass}
                  >
                    {t("common.cancel")}
                  </button>
                </div>
              </>
            )}
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
            {search || statusFilter ? t("common.empty") : t("schedules.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("common.code")}</th>
                  <th className="py-2 text-start">{t("common.nameEn")}</th>
                  <th className="py-2 text-start">{t("common.nameAr")}</th>
                  <th className="py-2 text-start">{t("schedules.timezone")}</th>
                  <th className="py-2 text-start">{t("schedules.effectiveFrom")}</th>
                  <th className="py-2 text-start">{t("schedules.effectiveTo")}</th>
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
                    <td className="py-2 font-mono text-xs">{row.timezone}</td>
                    <td className="py-2">{row.effective_from}</td>
                    <td className="py-2">{row.effective_to ?? "—"}</td>
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
                            onClick={() => void removeSchedule(row)}
                            className="text-red-600 hover:underline"
                          >
                            {t("common.delete")}
                          </button>
                        ) : null}
                        {can("work_schedule.update") ? (
                          <button
                            type="button"
                            onClick={() => openDays(row)}
                            className="text-slate-600 hover:underline"
                          >
                            {t("schedules.days")}
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