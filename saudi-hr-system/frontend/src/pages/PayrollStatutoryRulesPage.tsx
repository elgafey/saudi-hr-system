import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  createPayrollStatutoryRule,
  deactivatePayrollStatutoryRule,
  listPayrollStatutoryRules,
  type PayrollStatutoryRule,
  type PayrollStatutoryRuleInput,
  type PayrollStatutoryRulePageParams,
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

interface RuleFormState {
  statutory_key: string;
  effective_from: string;
  effective_to: string;
  source_reference: string;
  source_date: string;
  requires_legal_verification: boolean;
  notes: string;
  rule_json: string;
}

const emptyForm: RuleFormState = {
  statutory_key: "",
  effective_from: "",
  effective_to: "",
  source_reference: "",
  source_date: "",
  requires_legal_verification: true,
  notes: "",
  rule_json: "{}",
};

export default function PayrollStatutoryRulesPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<PayrollStatutoryRule[]>([]);
  const [meta, setMeta] = useState<{
    page: number;
    page_size: number;
    total: number;
  }>({ page: 1, page_size: pageSize, total: 0 });
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [keyFilter, setKeyFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<RuleFormState>(emptyForm);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: PayrollStatutoryRulePageParams = {
        company_id: companyId,
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
        statutory_key: keyFilter || undefined,
      };
      const res = await listPayrollStatutoryRules(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [companyId, page, statusFilter, keyFilter, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (companyId === null) {
      return;
    }
    let parsedJson: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(form.rule_json || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("not an object");
      }
      parsedJson = parsed as Record<string, unknown>;
    } catch {
      setError(t("statutory.invalidJson"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload: PayrollStatutoryRuleInput = {
        company_id: companyId,
        statutory_key: form.statutory_key.trim(),
        effective_from: form.effective_from,
        effective_to: form.effective_to || null,
        rule_json: parsedJson,
        source_reference: form.source_reference.trim(),
        source_date: form.source_date || null,
        requires_legal_verification: form.requires_legal_verification,
        notes: form.notes.trim() || null,
      };
      await createPayrollStatutoryRule(payload);
      setFormOpen(false);
      setForm(emptyForm);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSaving(false);
    }
  }

  async function handleDeactivate(rule: PayrollStatutoryRule) {
    if (!window.confirm(t("payrollStatutory.deactivateConfirm"))) {
      return;
    }
    setError(null);
    try {
      await deactivatePayrollStatutoryRule(rule.id, { status: "inactive" });
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  const canCreate = can("payroll_statutory_rule.create");
  const canDeactivate = can("payroll_statutory_rule.deactivate");

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">
          {t("payrollStatutory.heading")}
        </h1>
        {canCreate ? (
          <button
            type="button"
            onClick={() => {
              setFormOpen(!formOpen);
              setError(null);
            }}
            className={primaryButtonClass}
          >
            + {t("payrollStatutory.new")}
          </button>
        ) : null}
      </div>

      <p className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-800">
        {t("payrollStatutory.notice")}
      </p>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setPage(1);
        }}
        className="flex flex-wrap items-end gap-3"
      >
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
        <label className="min-w-40 flex-1">
          <span className={labelClass}>{t("statutory.key")}</span>
          <input
            value={keyFilter}
            onChange={(event) => {
              setKeyFilter(event.target.value);
              setPage(1);
            }}
            className={inputClass}
          />
        </label>
        <button type="submit" className={ghostButtonClass}>
          {t("common.search")}
        </button>
      </form>

      {formOpen ? (
        <section className="rounded-xl border border-slate-300 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold">
            {t("payrollStatutory.new")}
          </h2>
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("statutory.key")}</span>
              <input
                required
                maxLength={50}
                value={form.statutory_key}
                onChange={(event) =>
                  setForm({ ...form, statutory_key: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("statutory.sourceReference")}
              </span>
              <input
                required
                maxLength={500}
                value={form.source_reference}
                onChange={(event) =>
                  setForm({ ...form, source_reference: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("statutory.effectiveFrom")}</span>
              <input
                required
                type="date"
                value={form.effective_from}
                onChange={(event) =>
                  setForm({ ...form, effective_from: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("statutory.effectiveTo")}</span>
              <input
                type="date"
                value={form.effective_to}
                onChange={(event) =>
                  setForm({ ...form, effective_to: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("statutory.sourceDate")}</span>
              <input
                type="date"
                value={form.source_date}
                onChange={(event) =>
                  setForm({ ...form, source_date: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label className="flex items-center gap-2 self-end py-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={form.requires_legal_verification}
                onChange={(event) =>
                  setForm({
                    ...form,
                    requires_legal_verification: event.target.checked,
                  })
                }
              />
              {t("statutory.legalVerification")}
            </label>
            <label className="sm:col-span-2">
              <span className={labelClass}>{t("statutory.ruleJson")}</span>
              <textarea
                rows={3}
                value={form.rule_json}
                onChange={(event) =>
                  setForm({ ...form, rule_json: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label className="sm:col-span-2">
              <span className={labelClass}>{t("statutory.notes")}</span>
              <input
                maxLength={2000}
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
                onClick={() => setFormOpen(false)}
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
            {t("payrollStatutory.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("statutory.key")}</th>
                  <th className="py-2 text-start">
                    {t("statutory.effectiveFrom")}
                  </th>
                  <th className="py-2 text-start">
                    {t("statutory.effectiveTo")}
                  </th>
                  <th className="py-2 text-start">
                    {t("statutory.sourceReference")}
                  </th>
                  <th className="py-2 text-start">{t("statutory.version")}</th>
                  <th className="py-2 text-start">
                    {t("statutory.legalVerification")}
                  </th>
                  <th className="py-2 text-start">{t("common.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((rule) => (
                  <tr key={rule.id} className="border-b border-slate-100">
                    <td className="py-2 font-mono text-xs">
                      {rule.statutory_key}
                    </td>
                    <td className="py-2">{rule.effective_from}</td>
                    <td className="py-2">{rule.effective_to ?? "—"}</td>
                    <td className="py-2">{rule.source_reference}</td>
                    <td className="py-2">v{rule.version}</td>
                    <td className="py-2">
                      {rule.requires_legal_verification ? "✓" : "—"}
                    </td>
                    <td className="py-2">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                        {rule.status === "active"
                          ? t("status.active")
                          : t("status.inactive")}
                      </span>
                    </td>
                    <td className="py-2">
                      {canDeactivate && rule.status === "active" ? (
                        <button
                          type="button"
                          onClick={() => void handleDeactivate(rule)}
                          className="text-amber-700 hover:underline"
                        >
                          {t("common.deactivate")}
                        </button>
                      ) : null}
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
