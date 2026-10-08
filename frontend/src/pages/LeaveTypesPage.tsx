import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { useSession } from "../App";
import {
  createLeaveType,
  createStatutoryRule,
  deactivateStatutoryRule,
  deleteLeaveType,
  listLeaveTypes,
  listStatutoryRules,
  updateLeaveType,
  type LeaveType,
  type LeaveTypeInput,
  type LeaveTypePageParams,
  type StatutoryRule,
  type StatutoryRuleInput,
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

interface TypeFormState {
  code: string;
  name_ar: string;
  name_en: string;
  description: string;
  is_paid: boolean;
  requires_approval: boolean;
  allocation_requires_approval: boolean;
  day_counting_mode: string;
  requires_attachment: boolean;
  attachment_threshold_days: string;
  requires_reason: boolean;
  negative_balance_allowed: boolean;
  min_request_days: string;
  max_request_days: string;
  default_entitlement_days: string;
  carry_forward_enabled: boolean;
  carry_forward_max_days: string;
  carry_forward_expiry: string;
  allowance_treatment: string;
  is_statutory: boolean;
  statutory_key: string;
  status: string;
  sort_order: string;
}

const emptyTypeForm: TypeFormState = {
  code: "",
  name_ar: "",
  name_en: "",
  description: "",
  is_paid: true,
  requires_approval: true,
  allocation_requires_approval: false,
  day_counting_mode: "working_days",
  requires_attachment: false,
  attachment_threshold_days: "",
  requires_reason: false,
  negative_balance_allowed: false,
  min_request_days: "",
  max_request_days: "",
  default_entitlement_days: "",
  carry_forward_enabled: false,
  carry_forward_max_days: "",
  carry_forward_expiry: "end_of_next_year",
  allowance_treatment: "continue",
  is_statutory: false,
  statutory_key: "",
  status: "active",
  sort_order: "0",
};

function num(value: string): number | null {
  if (value.trim() === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function typePayload(
  companyId: number,
  form: TypeFormState,
): LeaveTypeInput {
  return {
    company_id: companyId,
    code: form.code.trim(),
    name_ar: form.name_ar.trim(),
    name_en: form.name_en.trim(),
    description: form.description.trim() || null,
    is_paid: form.is_paid,
    requires_approval: form.requires_approval,
    allocation_requires_approval: form.allocation_requires_approval,
    day_counting_mode: form.day_counting_mode,
    requires_attachment: form.requires_attachment,
    attachment_threshold_days: num(form.attachment_threshold_days),
    requires_reason: form.requires_reason,
    negative_balance_allowed: form.negative_balance_allowed,
    min_request_days: num(form.min_request_days),
    max_request_days: num(form.max_request_days),
    default_entitlement_days: num(form.default_entitlement_days),
    carry_forward_enabled: form.carry_forward_enabled,
    carry_forward_max_days: num(form.carry_forward_max_days),
    carry_forward_expiry: form.carry_forward_expiry,
    allowance_treatment: form.allowance_treatment,
    is_statutory: form.is_statutory,
    statutory_key: form.statutory_key.trim() || null,
    status: form.status,
    sort_order: Number(form.sort_order) || 0,
  };
}

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

const emptyRuleForm: RuleFormState = {
  statutory_key: "",
  effective_from: "",
  effective_to: "",
  source_reference: "",
  source_date: "",
  requires_legal_verification: true,
  notes: "",
  rule_json: "{}",
};

export default function LeaveTypesPage() {
  const { t, can, me } = useSession();
  const companyId = me?.company_ids[0] ?? null;

  const [items, setItems] = useState<LeaveType[]>([]);
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
  const [editing, setEditing] = useState<LeaveType | null>(null);
  const [form, setForm] = useState<TypeFormState>(emptyTypeForm);
  const [saving, setSaving] = useState(false);

  const [rules, setRules] = useState<StatutoryRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(true);
  const [ruleOpen, setRuleOpen] = useState(false);
  const [ruleForm, setRuleForm] = useState<RuleFormState>(emptyRuleForm);
  const [ruleSaving, setRuleSaving] = useState(false);

  const load = useCallback(async () => {
    if (companyId === null) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: LeaveTypePageParams = {
        company_id: companyId,
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
        statutory_key: keyFilter || undefined,
      };
      const res = await listLeaveTypes(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [companyId, page, statusFilter, keyFilter, t]);

  const loadRules = useCallback(async () => {
    if (companyId === null) {
      setRules([]);
      setRulesLoading(false);
      return;
    }
    setRulesLoading(true);
    try {
      const res = await listStatutoryRules({
        company_id: companyId,
        page_size: 100,
      });
      setRules(res.items);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setRulesLoading(false);
    }
  }, [companyId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadRules();
  }, [loadRules]);

  function openCreate() {
    setEditing(null);
    setForm(emptyTypeForm);
    setFormOpen(true);
    setError(null);
  }

  function openEdit(row: LeaveType) {
    setEditing(row);
    setForm({
      code: row.code,
      name_ar: row.name_ar,
      name_en: row.name_en,
      description: row.description ?? "",
      is_paid: row.is_paid,
      requires_approval: row.requires_approval,
      allocation_requires_approval: row.allocation_requires_approval,
      day_counting_mode: row.day_counting_mode,
      requires_attachment: row.requires_attachment,
      attachment_threshold_days:
        row.attachment_threshold_days !== null
          ? String(row.attachment_threshold_days)
          : "",
      requires_reason: row.requires_reason,
      negative_balance_allowed: row.negative_balance_allowed,
      min_request_days:
        row.min_request_days !== null ? String(row.min_request_days) : "",
      max_request_days:
        row.max_request_days !== null ? String(row.max_request_days) : "",
      default_entitlement_days:
        row.default_entitlement_days !== null
          ? String(row.default_entitlement_days)
          : "",
      carry_forward_enabled: row.carry_forward_enabled,
      carry_forward_max_days:
        row.carry_forward_max_days !== null
          ? String(row.carry_forward_max_days)
          : "",
      carry_forward_expiry: row.carry_forward_expiry,
      allowance_treatment: row.allowance_treatment,
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
    const payload = typePayload(companyId, form);
    try {
      if (editing) {
        const { company_id: _ignored, ...patch } = payload;
        void _ignored;
        await updateLeaveType(editing.id, patch);
      } else {
        await createLeaveType(payload);
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

  async function handleDelete(row: LeaveType) {
    if (!window.confirm(t("leaveTypes.deleteConfirm"))) {
      return;
    }
    setError(null);
    try {
      await deleteLeaveType(row.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  async function submitRule(event: FormEvent) {
    event.preventDefault();
    if (companyId === null) {
      return;
    }
    let parsedJson: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(ruleForm.rule_json || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("not an object");
      }
      parsedJson = parsed as Record<string, unknown>;
    } catch {
      setError(t("statutory.invalidJson"));
      return;
    }
    setRuleSaving(true);
    setError(null);
    try {
      const payload: StatutoryRuleInput = {
        company_id: companyId,
        statutory_key: ruleForm.statutory_key.trim(),
        effective_from: ruleForm.effective_from,
        effective_to: ruleForm.effective_to || null,
        rule_json: parsedJson,
        source_reference: ruleForm.source_reference.trim(),
        source_date: ruleForm.source_date || null,
        requires_legal_verification: ruleForm.requires_legal_verification,
        notes: ruleForm.notes.trim() || null,
      };
      await createStatutoryRule(payload);
      setRuleOpen(false);
      setRuleForm(emptyRuleForm);
      await loadRules();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setRuleSaving(false);
    }
  }

  async function handleDeactivate(rule: StatutoryRule) {
    if (!window.confirm(t("statutory.deactivateConfirm"))) {
      return;
    }
    const reason = window.prompt(t("statutory.notes")) ?? "";
    setError(null);
    try {
      await deactivateStatutoryRule(rule.id, {
        reason: reason.trim() || null,
      });
      await loadRules();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  const canCreate = can("leave_type.create");
  const canUpdate = can("leave_type.update");
  const canDelete = can("leave_type.delete");

  const set = <K extends keyof TypeFormState>(
    key: K,
    value: TypeFormState[K],
  ) => setForm((prev) => ({ ...prev, [key]: value }));

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{t("leaveTypes.heading")}</h1>
        {canCreate ? (
          <button
            type="button"
            onClick={openCreate}
            className={primaryButtonClass}
          >
            + {t("leaveTypes.new")}
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
          <span className={labelClass}>
            {t("leaveTypes.filters.status")}
          </span>
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
          <span className={labelClass}>
            {t("leaveTypes.filters.statutoryKey")}
          </span>
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
            {editing ? t("leaveTypes.edit") : t("leaveTypes.new")}
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
              <span className={labelClass}>{t("leaveTypes.sortOrder")}</span>
              <input
                type="number"
                value={form.sort_order}
                onChange={(event) => set("sort_order", event.target.value)}
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
            <label className="sm:col-span-2">
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
                {t("leaveTypes.dayCountingMode")}
              </span>
              <select
                value={form.day_counting_mode}
                onChange={(event) =>
                  set("day_counting_mode", event.target.value)
                }
                className={inputClass}
              >
                <option value="working_days">
                  {t("dayCounting.working_days")}
                </option>
                <option value="calendar_days">
                  {t("dayCounting.calendar_days")}
                </option>
              </select>
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
                {t("leaveTypes.attachmentThresholdDays")}
              </span>
              <input
                type="number"
                min={1}
                step="0.5"
                value={form.attachment_threshold_days}
                onChange={(event) =>
                  set("attachment_threshold_days", event.target.value)
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("leaveTypes.defaultEntitlementDays")}
              </span>
              <input
                type="number"
                min={0}
                step="0.5"
                value={form.default_entitlement_days}
                onChange={(event) =>
                  set("default_entitlement_days", event.target.value)
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("leaveTypes.minRequestDays")}
              </span>
              <input
                type="number"
                min={1}
                step="0.5"
                value={form.min_request_days}
                onChange={(event) =>
                  set("min_request_days", event.target.value)
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("leaveTypes.maxRequestDays")}
              </span>
              <input
                type="number"
                min={1}
                step="0.5"
                value={form.max_request_days}
                onChange={(event) =>
                  set("max_request_days", event.target.value)
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("leaveTypes.carryForwardMaxDays")}
              </span>
              <input
                type="number"
                min={0}
                step="0.5"
                value={form.carry_forward_max_days}
                onChange={(event) =>
                  set("carry_forward_max_days", event.target.value)
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("leaveTypes.carryForwardExpiry")}
              </span>
              <select
                value={form.carry_forward_expiry}
                onChange={(event) =>
                  set("carry_forward_expiry", event.target.value)
                }
                className={inputClass}
              >
                <option value="none">{t("carryExpiry.none")}</option>
                <option value="end_of_year">
                  {t("carryExpiry.end_of_year")}
                </option>
                <option value="end_of_next_year">
                  {t("carryExpiry.end_of_next_year")}
                </option>
              </select>
            </label>
            <label>
              <span className={labelClass}>
                {t("leaveTypes.allowanceTreatment")}
              </span>
              <select
                value={form.allowance_treatment}
                onChange={(event) =>
                  set("allowance_treatment", event.target.value)
                }
                className={inputClass}
              >
                <option value="continue">{t("allowance.continue")}</option>
                <option value="deduct">{t("allowance.deduct")}</option>
                <option value="prorate">{t("allowance.prorate")}</option>
              </select>
            </label>
            <label>
              <span className={labelClass}>
                {t("leaveTypes.statutoryKey")}
              </span>
              <input
                maxLength={50}
                value={form.statutory_key}
                onChange={(event) => set("statutory_key", event.target.value)}
                className={inputClass}
              />
            </label>
            <div className="grid gap-2 sm:col-span-2 sm:grid-cols-3">
              {(
                [
                  ["is_paid", "leaveTypes.isPaid"],
                  [
                    "requires_approval",
                    "leaveTypes.requiresApproval",
                  ],
                  [
                    "allocation_requires_approval",
                    "leaveTypes.allocationRequiresApproval",
                  ],
                  [
                    "requires_attachment",
                    "leaveTypes.requiresAttachment",
                  ],
                  ["requires_reason", "leaveTypes.requiresReason"],
                  [
                    "negative_balance_allowed",
                    "leaveTypes.negativeBalanceAllowed",
                  ],
                  [
                    "carry_forward_enabled",
                    "leaveTypes.carryForwardEnabled",
                  ],
                  ["is_statutory", "leaveTypes.isStatutory"],
                ] as const
              ).map(([key, labelKey]) => (
                <label
                  key={key}
                  className="flex items-center gap-2 text-sm text-slate-700"
                >
                  <input
                    type="checkbox"
                    checked={form[key]}
                    onChange={(event) => set(key, event.target.checked)}
                  />
                  {t(labelKey)}
                </label>
              ))}
            </div>
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
            {t("leaveTypes.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-start text-slate-500">
                  <th className="py-2 text-start">{t("common.code")}</th>
                  <th className="py-2 text-start">{t("common.nameEn")}</th>
                  <th className="py-2 text-start">{t("common.nameAr")}</th>
                  <th className="py-2 text-start">
                    {t("leaveTypes.isPaid")}
                  </th>
                  <th className="py-2 text-start">
                    {t("leaveTypes.dayCountingMode")}
                  </th>
                  <th className="py-2 text-start">{t("common.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="py-2 font-mono text-xs">{row.code}</td>
                    <td className="py-2">{row.name_en}</td>
                    <td className="py-2">{row.name_ar}</td>
                    <td className="py-2">{row.is_paid ? "✓" : "—"}</td>
                    <td className="py-2">
                      {row.day_counting_mode === "working_days"
                        ? t("dayCounting.working_days")
                        : t("dayCounting.calendar_days")}
                    </td>
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

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">{t("statutory.heading")}</h2>
          {canCreate ? (
            <button
              type="button"
              onClick={() => {
                setRuleOpen(!ruleOpen);
                setError(null);
              }}
              className={ghostButtonClass}
            >
              + {t("statutory.new")}
            </button>
          ) : null}
        </div>

        {ruleOpen ? (
          <form onSubmit={submitRule} className="mb-4 grid gap-3 sm:grid-cols-2">
            <label>
              <span className={labelClass}>{t("statutory.key")}</span>
              <input
                required
                maxLength={50}
                value={ruleForm.statutory_key}
                onChange={(event) =>
                  setRuleForm({ ...ruleForm, statutory_key: event.target.value })
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
                value={ruleForm.source_reference}
                onChange={(event) =>
                  setRuleForm({
                    ...ruleForm,
                    source_reference: event.target.value,
                  })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("statutory.effectiveFrom")}
              </span>
              <input
                required
                type="date"
                value={ruleForm.effective_from}
                onChange={(event) =>
                  setRuleForm({
                    ...ruleForm,
                    effective_from: event.target.value,
                  })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>
                {t("statutory.effectiveTo")}
              </span>
              <input
                type="date"
                value={ruleForm.effective_to}
                onChange={(event) =>
                  setRuleForm({
                    ...ruleForm,
                    effective_to: event.target.value,
                  })
                }
                className={inputClass}
              />
            </label>
            <label>
              <span className={labelClass}>{t("statutory.sourceDate")}</span>
              <input
                type="date"
                value={ruleForm.source_date}
                onChange={(event) =>
                  setRuleForm({ ...ruleForm, source_date: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label className="flex items-center gap-2 self-end py-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={ruleForm.requires_legal_verification}
                onChange={(event) =>
                  setRuleForm({
                    ...ruleForm,
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
                value={ruleForm.rule_json}
                onChange={(event) =>
                  setRuleForm({ ...ruleForm, rule_json: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <label className="sm:col-span-2">
              <span className={labelClass}>{t("statutory.notes")}</span>
              <input
                maxLength={2000}
                value={ruleForm.notes}
                onChange={(event) =>
                  setRuleForm({ ...ruleForm, notes: event.target.value })
                }
                className={inputClass}
              />
            </label>
            <div className="flex gap-2 sm:col-span-2">
              <button
                type="submit"
                disabled={ruleSaving}
                className={primaryButtonClass}
              >
                {ruleSaving ? t("common.saving") : t("common.save")}
              </button>
              <button
                type="button"
                onClick={() => setRuleOpen(false)}
                className={ghostButtonClass}
              >
                {t("common.cancel")}
              </button>
            </div>
          </form>
        ) : null}

        {rulesLoading ? (
          <p className="py-4 text-center text-sm text-slate-500">
            {t("common.loading")}
          </p>
        ) : rules.length === 0 ? (
          <p className="py-4 text-center text-sm text-slate-500">
            {t("statutory.empty")}
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
                  <th className="py-2 text-start">
                    {t("statutory.version")}
                  </th>
                  <th className="py-2 text-start">{t("common.status")}</th>
                  <th className="py-2 text-start">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.id} className="border-b border-slate-100">
                    <td className="py-2 font-mono text-xs">
                      {rule.statutory_key}
                    </td>
                    <td className="py-2">{rule.effective_from}</td>
                    <td className="py-2">{rule.effective_to ?? "—"}</td>
                    <td className="py-2">{rule.source_reference}</td>
                    <td className="py-2">v{rule.version}</td>
                    <td className="py-2">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                        {rule.status === "active"
                          ? t("statutory.status.active")
                          : t("statutory.status.inactive")}
                      </span>
                    </td>
                    <td className="py-2">
                      {canUpdate && rule.status === "active" ? (
                        <button
                          type="button"
                          onClick={() => void handleDeactivate(rule)}
                          className="text-amber-700 hover:underline"
                        >
                          {t("statutory.deactivate")}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
