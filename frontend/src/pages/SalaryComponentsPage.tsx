import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  createSalaryComponent,
  deactivateSalaryComponent,
  listSalaryComponents,
  updateSalaryComponent,
  type SalaryComponent,
  type SalaryComponentInput,
  type SalaryComponentPageParams,
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

interface ComponentFormState {
  code: string;
  name_ar: string;
  name_en: string;
  description: string;
  category: string;
  calculation_basis: string;
  default_amount: string;
  default_rate: string;
  is_statutory: boolean;
  statutory_key: string;
  status: string;
  sort_order: string;
}

const emptyForm: ComponentFormState = {
  code: "",
  name_ar: "",
  name_en: "",
  description: "",
  category: "earning",
  calculation_basis: "fixed",
  default_amount: "",
  default_rate: "",
  is_statutory: false,
  statutory_key: "",
  status: "active",
  sort_order: "0",
};

function numOrNull(value: string): number | null {
  if (value.trim() === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildPayload(
  companyId: number,
  form: ComponentFormState,
): SalaryComponentInput {
  return {
    company_id: companyId,
    code: form.code.trim(),
    name_ar: form.name_ar.trim(),
    name_en: form.name_en.trim(),
    description: form.description.trim() || null,
    category: form.category,
    calculation_basis: form.calculation_basis,
    default_amount: numOrNull(form.default_amount),
    default_rate: numOrNull(form.default_rate),
    is_statutory: form.is_statutory,
    statutory_key: form.statutory_key.trim() || null,
    status: form.status,
    sort_order: Number(form.sort_order) || 0,
  };
}

export default function SalaryComponentsPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<SalaryComponent[]>([]);
  const [meta, setMeta] = useState<{
    page: number;
    page_size: number;
    total: number;
  }>({ page: 1, page_size: pageSize, total: 0 });
  const [page, setPage] = useState(1);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<SalaryComponent | null>(null);
  const [form, setForm] = useState<ComponentFormState>(emptyForm);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: SalaryComponentPageParams = {
        company_id: companyId,
        page,
        page_size: pageSize,
        category: categoryFilter || undefined,
        status: statusFilter || undefined,
      };
      const res = await listSalaryComponents(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [companyId, page, categoryFilter, statusFilter, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditing(null);
    setForm(emptyForm);
    setFormOpen(true);
    setError(null);
  }

  function openEdit(row: SalaryComponent) {
    setEditing(row);
    setForm({
      code: row.code,
      name_ar: row.name_ar,
      name_en: row.name_en,
      description: row.description ?? "",
      category: row.category,
      calculation_basis: row.calculation_basis,
      default_amount:
        row.default_amount !== null ? String(row.default_amount) : "",
      default_rate: row.default_rate !== null ? String(row.default_rate) : "",
      is_statutory: row.is_statutory,
      statutory_key: row.statutory_key ?? "",
      status: row.status,
      sort_order: String(row.sort_order),
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
      const payload = buildPayload(companyId, form);
      if (editing) {
        const { company_id: _ignored, ...patch } = payload;
        void _ignored;
        await updateSalaryComponent(editing.id, patch);
      } else {
        await createSalaryComponent(payload);
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

  async function handleDeactivate(row: SalaryComponent) {
    if (!window.confirm(t("salaryComponents.deactivateConfirm"))) {
      return;
    }
    setError(null);
    try {
      await deactivateSalaryComponent(row.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  const canCreate = can("salary_component.create");
  const canUpdate = can("salary_component.update");
  const canDeactivate = can("salary_component.deactivate");

  const set = <K extends keyof ComponentFormState>(
    key: K,
    value: ComponentFormState[K],
  ) => setForm((prev) => ({ ...prev, [key]: value }));

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">
          {t("salaryComponents.heading")}
        </h1>
        {canCreate ? (
          <button
            type="button"
            onClick={openCreate}
            className={primaryButtonClass}
          >
            + {t("salaryComponents.new")}
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
        <label className="min-w-40 flex-1">
          <span className={labelClass}>{t("salaryComponents.category")}</span>
          <select
            value={categoryFilter}
            onChange={(event) => {
              setCategoryFilter(event.target.value);
              setPage(1);
            }}
            className={inputClass}
          >
            <option value="">—</option>
            <option value="earning">
              {t("componentCategory.earning")}
            </option>
            <option value="deduction">
              {t("componentCategory.deduction")}
            </option>
            <option value="employer_contribution">
              {t("componentCategory.employer_contribution")}
            </option>
          </select>
        </label>
        <label className="min-w-40 flex-1">
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
            {editing ? t("salaryComponents.edit") : t("salaryComponents.new")}
          </h2>
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("common.code")}</span>
              <input
                required
                maxLength={50}
                value={form.code}
                onChange={(event) => set("code", event.target.value)}
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("common.nameAr")}</span>
              <input
                required
                maxLength={255}
                value={form.name_ar}
                onChange={(event) => set("name_ar", event.target.value)}
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("common.nameEn")}</span>
              <input
                required
                maxLength={255}
                value={form.name_en}
                onChange={(event) => set("name_en", event.target.value)}
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("common.description")}</span>
              <input
                maxLength={500}
                value={form.description}
                onChange={(event) => set("description", event.target.value)}
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("salaryComponents.category")}
              </span>
              <select
                value={form.category}
                onChange={(event) => set("category", event.target.value)}
                className={inputClass}
              >
                <option value="earning">
                  {t("componentCategory.earning")}
                </option>
                <option value="deduction">
                  {t("componentCategory.deduction")}
                </option>
                <option value="employer_contribution">
                  {t("componentCategory.employer_contribution")}
                </option>
              </select>
            </label>
            <label>
              <span className={labelClass}>
                {t("salaryComponents.calculationBasis")}
              </span>
              <select
                value={form.calculation_basis}
                onChange={(event) =>
                  set("calculation_basis", event.target.value)
                }
                className={inputClass}
              >
                <option value="fixed">{t("componentBasis.fixed")}</option>
                <option value="percent_of_basic">
                  {t("componentBasis.percent_of_basic")}
                </option>
                <option value="engine_derived">
                  {t("componentBasis.engine_derived")}
                </option>
              </select>
            </label>
            <label>
              <span className={labelClass}>
                {t("salaryComponents.defaultAmount")}
              </span>
              <input
                type="number"
                min={0}
                step="0.01"
                value={form.default_amount}
                onChange={(event) => set("default_amount", event.target.value)}
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("salaryComponents.defaultRate")}
              </span>
              <input
                type="number"
                min={0}
                max={1}
                step="0.0001"
                value={form.default_rate}
                onChange={(event) => set("default_rate", event.target.value)}
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("common.status")}</span>
              <select
                value={form.status}
                onChange={(event) => set("status", event.target.value)}
                className={inputClass}
              >
                <option value="active">{t("status.active")}</option>
                <option value="inactive">{t("status.inactive")}</option>
              </select>
            </label>
            <label>
              <span className={labelClass}>
                {t("salaryComponents.statutoryKey")}
              </span>
              <input
                maxLength={50}
                value={form.statutory_key}
                onChange={(event) => set("statutory_key", event.target.value)}
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("common.sortOrder")}</span>
              <input
                type="number"
                value={form.sort_order}
                onChange={(event) => set("sort_order", event.target.value)}
                className={inputClass}
              />
            </label>
            <label className="flex items-center gap-2 self-end py-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={form.is_statutory}
                onChange={(event) =>
                  set("is_statutory", event.target.checked)
                }
              />
              {t("salaryComponents.isStatutory")}
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
            {t("salaryComponents.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("common.code")}</th>
                  <th className="py-2 text-start">{t("common.nameEn")}</th>
                  <th className="py-2 text-start">
                    {t("salaryComponents.category")}
                  </th>
                  <th className="py-2 text-start">
                    {t("salaryComponents.calculationBasis")}
                  </th>
                  <th className="py-2 text-start">
                    {t("salaryComponents.defaultAmount")}
                  </th>
                  <th className="py-2 text-start">
                    {t("salaryComponents.defaultRate")}
                  </th>
                  <th className="py-2 text-start">{t("common.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2 font-mono text-xs">
                      {row.code}
                      {row.is_statutory ? " ★" : ""}
                    </td>
                    <td className="py-2">{row.name_en}</td>
                    <td className="py-2">{t(`componentCategory.${row.category}`)}</td>
                    <td className="py-2">
                      {t(`componentBasis.${row.calculation_basis}`)}
                    </td>
                    <td className="py-2">{row.default_amount ?? "—"}</td>
                    <td className="py-2">{row.default_rate ?? "—"}</td>
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
                        {canDeactivate && row.status === "active" ? (
                          <button
                            type="button"
                            onClick={() => void handleDeactivate(row)}
                            className="text-amber-700 hover:underline"
                          >
                            {t("common.deactivate")}
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
