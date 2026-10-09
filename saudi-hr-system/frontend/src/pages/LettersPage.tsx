import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSession } from "../App";
import {
  createHrLetter,
  listEmployees,
  listHrLetters,
  type Employee,
  type HrLetterListItem,
  type HrLettersPageParams,
  type PageMeta,
} from "../api";
import HrLetterDetail from "../components/HrLetterDetail";
import Pagination from "../components/Pagination";
import {
  errorMessage,
  errorTextClass,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../ui";

const pageSize = 20;

const STATUS_OPTIONS = ["draft", "issued", "void", "cancelled"];

const TYPE_OPTIONS = [
  "employment",
  "salary",
  "experience",
  "work_address",
];

interface FormState {
  employee_id: string;
  letter_type: string;
  language: string;
  purpose: string;
}

const emptyForm: FormState = {
  employee_id: "",
  letter_type: "employment",
  language: "en",
  purpose: "",
};

export default function LettersPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;
  const mayView = can("hr_letter.view") || can("hr_letter.create");
  const mayCreate = can("hr_letter.create");

  const [items, setItems] = useState<HrLetterListItem[]>([]);
  const [meta, setMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [employees, setEmployees] = useState<Employee[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);

  const [selectedId, setSelectedId] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!mayView) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: HrLettersPageParams = {
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
        letter_type: typeFilter || undefined,
      };
      const res = await listHrLetters(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, typeFilter, t, mayView]);

  const loadEmployees = useCallback(async () => {
    if (companyId === null || !mayCreate) {
      return;
    }
    try {
      const res = await listEmployees({
        company_id: companyId,
        page_size: 200,
      });
      setEmployees(res.items);
    } catch {
      setEmployees([]);
    }
  }, [companyId, mayCreate]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadEmployees();
  }, [loadEmployees]);

  function setField(key: keyof FormState, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form.employee_id) {
      setError(t("letters.selectEmployee"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await createHrLetter({
        employee_id: Number(form.employee_id),
        letter_type: form.letter_type,
        language: form.language,
        purpose: form.purpose.trim() || null,
      });
      setForm(emptyForm);
      setFormOpen(false);
      setSelectedId(created.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSaving(false);
    }
  }

  if (!mayView) {
    return <p className={errorTextClass}>{t("error.forbidden")}</p>;
  }

  const statusLabel = (status: string): string => {
    const key = `letters.status.${status}`;
    const label = t(key);
    return label === key ? status : label;
  };

  const typeLabel = (type: string): string => {
    const key = `letters.type.${type}`;
    const label = t(key);
    return label === key ? type : label;
  };

  return (
    <div className="space-y-6 py-8">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold">{t("letters.heading")}</h1>
        {mayCreate ? (
          <button
            type="button"
            className={primaryButtonClass}
            onClick={() => setFormOpen((open) => !open)}
          >
            {formOpen ? t("common.cancel") : t("letters.new")}
          </button>
        ) : null}
      </div>

      {formOpen ? (
        <form
          onSubmit={(event) => void save(event)}
          className="space-y-3 rounded-xl border border-slate-200 bg-white p-4"
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block text-sm">
              <span className={labelClass}>{t("letters.selectEmployee")}</span>
              <select
                className={inputClass}
                value={form.employee_id}
                required
                onChange={(e) => setField("employee_id", e.target.value)}
              >
                <option value="">—</option>
                {employees.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.employee_number} — {employee.first_name_en}{" "}
                    {employee.last_name_en}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className={labelClass}>{t("letters.type")}</span>
              <select
                className={inputClass}
                value={form.letter_type}
                onChange={(e) => setField("letter_type", e.target.value)}
              >
                {TYPE_OPTIONS.map((type) => (
                  <option key={type} value={type}>
                    {typeLabel(type)}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className={labelClass}>{t("letters.language")}</span>
              <select
                className={inputClass}
                value={form.language}
                onChange={(e) => setField("language", e.target.value)}
              >
                <option value="en">EN</option>
                <option value="ar">AR</option>
              </select>
            </label>
          </div>
          <label className="block text-sm">
            <span className={labelClass}>{t("letters.purpose")}</span>
            <input
              className={inputClass}
              maxLength={500}
              value={form.purpose}
              onChange={(e) => setField("purpose", e.target.value)}
            />
          </label>
          <p className="text-xs text-slate-500">{t("letters.createHint")}</p>
          <button type="submit" className={primaryButtonClass} disabled={saving}>
            {saving ? t("common.saving") : t("common.save")}
          </button>
        </form>
      ) : null}

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className={labelClass}>{t("letters.filters.status")}</span>
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
        <label className="text-sm">
          <span className={labelClass}>{t("letters.filters.type")}</span>
          <select
            className={inputClass}
            value={typeFilter}
            onChange={(e) => {
              setTypeFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="">—</option>
            {TYPE_OPTIONS.map((type) => (
              <option key={type} value={type}>
                {typeLabel(type)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && !formOpen ? <p className={errorTextClass}>{error}</p> : null}

      {loading ? (
        <p className="text-sm text-slate-500">{t("common.loading")}</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-500">{t("letters.empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-4">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-2 pr-3">{t("letters.reference")}</th>
                <th className="py-2 pr-3">{t("letters.employee")}</th>
                <th className="py-2 pr-3">{t("letters.type")}</th>
                <th className="py-2 pr-3">{t("letters.language")}</th>
                <th className="py-2 pr-3">{t("common.status")}</th>
                <th className="py-2 pr-3">{t("letters.issuedAt")}</th>
                <th className="py-2 pr-3 text-right">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.id} className="border-b border-slate-100">
                  <td className="py-2 pr-3 font-mono text-xs">
                    {row.reference}
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs">
                    #{row.employee_id}
                  </td>
                  <td className="py-2 pr-3">{typeLabel(row.letter_type)}</td>
                  <td className="py-2 pr-3">{row.language.toUpperCase()}</td>
                  <td className="py-2 pr-3">{statusLabel(row.status)}</td>
                  <td className="py-2 pr-3">
                    {row.issued_at
                      ? row.issued_at.slice(0, 16).replace("T", " ")
                      : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <button
                      type="button"
                      className="text-blue-600 hover:underline"
                      onClick={() => setSelectedId(row.id)}
                    >
                      {t("letters.detail")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination meta={meta} onPage={setPage} />
        </div>
      )}

      <HrLetterDetail
        letterId={selectedId}
        actions={{
          canEdit: can("hr_letter.update"),
          canIssue: can("hr_letter.issue"),
          canVoid: can("hr_letter.void"),
        }}
        onClose={() => setSelectedId(null)}
        onChanged={() => void load()}
      />
    </div>
  );
}
