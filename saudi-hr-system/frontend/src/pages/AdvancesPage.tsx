import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSession } from "../App";
import {
  createSalaryAdvance,
  listSalaryAdvances,
  type PageMeta,
  type SalaryAdvance,
  type SalaryAdvancesPageParams,
} from "../api";
import SalaryAdvanceDetail from "../components/SalaryAdvanceDetail";
import Pagination from "../components/Pagination";
import {
  errorMessage,
  errorTextClass,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../ui";

const pageSize = 20;

const STATUS_OPTIONS = [
  "draft",
  "submitted",
  "approved",
  "rejected",
  "cancelled",
  "disbursed",
  "settled",
];

interface FormState {
  amount: string;
  reason: string;
  requested_date: string;
}

const emptyForm: FormState = {
  amount: "",
  reason: "",
  requested_date: "",
};

export default function AdvancesPage() {
  const { t, can } = useSession();
  const mayView =
    can("salary_advance.view") || can("salary_advance.create");
  const mayCreate = can("salary_advance.create");
  const mayInbox =
    can("salary_advance.manage") ||
    can("salary_advance.approve") ||
    can("salary_advance.reject");

  const [items, setItems] = useState<SalaryAdvance[]>([]);
  const [meta, setMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [inboxOnly, setInboxOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      const params: SalaryAdvancesPageParams = {
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
        assigned_to_me: inboxOnly ? true : undefined,
      };
      const res = await listSalaryAdvances(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, inboxOnly, t, mayView]);

  useEffect(() => {
    void load();
  }, [load]);

  function setField(key: keyof FormState, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const created = await createSalaryAdvance({
        amount: Number(form.amount),
        reason: form.reason,
        requested_date: form.requested_date,
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
    const key = `advances.status.${status}`;
    const label = t(key);
    return label === key ? status : label;
  };

  return (
    <div className="space-y-6 py-8">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold">{t("advances.heading")}</h1>
        {mayCreate ? (
          <button
            type="button"
            className={primaryButtonClass}
            onClick={() => setFormOpen((open) => !open)}
          >
            {formOpen ? t("common.cancel") : t("advances.new")}
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
              <span className={labelClass}>{t("advances.amount")}</span>
              <input
                type="number"
                step="0.01"
                min="0.01"
                className={inputClass}
                value={form.amount}
                required
                onChange={(e) => setField("amount", e.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className={labelClass}>{t("advances.requestedDate")}</span>
              <input
                type="date"
                className={inputClass}
                value={form.requested_date}
                required
                onChange={(e) => setField("requested_date", e.target.value)}
              />
            </label>
          </div>
          <label className="block text-sm">
            <span className={labelClass}>{t("advances.reason")}</span>
            <textarea
              className={inputClass}
              rows={3}
              maxLength={4000}
              value={form.reason}
              required
              onChange={(e) => setField("reason", e.target.value)}
            />
          </label>
          <button type="submit" className={primaryButtonClass} disabled={saving}>
            {saving ? t("common.saving") : t("common.save")}
          </button>
        </form>
      ) : null}

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className={labelClass}>{t("advances.filters.status")}</span>
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
        {mayInbox ? (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={inboxOnly}
              onChange={(e) => {
                setInboxOnly(e.target.checked);
                setPage(1);
              }}
            />
            <span>{t("advances.filters.assignedToMe")}</span>
          </label>
        ) : null}
      </div>

      {error && !formOpen ? <p className={errorTextClass}>{error}</p> : null}

      {loading ? (
        <p className="text-sm text-slate-500">{t("common.loading")}</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-500">{t("advances.empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-4">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-2 pr-3">{t("advances.employee")}</th>
                <th className="py-2 pr-3">{t("advances.amount")}</th>
                <th className="py-2 pr-3">{t("advances.installment")}</th>
                <th className="py-2 pr-3">{t("common.status")}</th>
                <th className="py-2 pr-3">{t("advances.requestedDate")}</th>
                <th className="py-2 pr-3">{t("advances.submittedAt")}</th>
                <th className="py-2 pr-3 text-right">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.id} className="border-b border-slate-100">
                  <td className="py-2 pr-3 font-mono text-xs">
                    #{row.employee_id}
                  </td>
                  <td className="py-2 pr-3">{row.amount}</td>
                  <td className="py-2 pr-3">{row.installment_amount ?? "—"}</td>
                  <td className="py-2 pr-3">{statusLabel(row.status)}</td>
                  <td className="py-2 pr-3">{row.requested_date}</td>
                  <td className="py-2 pr-3">
                    {row.submitted_at
                      ? row.submitted_at.slice(0, 16).replace("T", " ")
                      : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <button
                      type="button"
                      className="text-blue-600 hover:underline"
                      onClick={() => setSelectedId(row.id)}
                    >
                      {t("advances.detail")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination meta={meta} onPage={setPage} />
        </div>
      )}

      <SalaryAdvanceDetail
        advanceId={selectedId}
        actions={{
          canEdit: can("salary_advance.update"),
          canSubmit: can("salary_advance.submit"),
          canCancel: can("salary_advance.cancel"),
          canApprove: can("salary_advance.approve"),
          canReject: can("salary_advance.reject"),
          canDisburse: can("salary_advance.disburse"),
          canSettle: can("salary_advance.settle"),
        }}
        onClose={() => setSelectedId(null)}
        onChanged={() => void load()}
      />
    </div>
  );
}
