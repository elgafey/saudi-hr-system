import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSession } from "../App";
import {
  createEmployeeRequest,
  listEmployeeRequests,
  type EmployeeRequest,
  type EmployeeRequestPageParams,
  type PageMeta,
} from "../api";
import EmployeeRequestDetail from "../components/EmployeeRequestDetail";
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
];

const TYPE_OPTIONS = [
  "attendance_correction",
  "hr_letter",
  "document_request",
  "other",
];

interface FormState {
  request_type: string;
  subject: string;
  reason: string;
  work_date: string;
  check_in: string;
  check_out: string;
  purpose: string;
  language: string;
  document_name: string;
  note: string;
  details: string;
}

const emptyForm: FormState = {
  request_type: "hr_letter",
  subject: "",
  reason: "",
  work_date: "",
  check_in: "",
  check_out: "",
  purpose: "",
  language: "en",
  document_name: "",
  note: "",
  details: "",
};

export default function EssRequestsPage() {
  const { t, can } = useSession();
  const mayView = can("employee_request.view");
  const mayCreate = can("employee_request.create");

  const [items, setItems] = useState<EmployeeRequest[]>([]);
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

  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);

  const [selectedId, setSelectedId] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!mayView && !mayCreate) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params: EmployeeRequestPageParams = {
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
        request_type: typeFilter || undefined,
      };
      const res = await listEmployeeRequests(params);
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, typeFilter, t, mayView, mayCreate]);

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
      let payload: Record<string, unknown> = {};
      if (form.request_type === "attendance_correction") {
        payload = {
          work_date: form.work_date,
          check_in: `${form.work_date}T${form.check_in || "08:00"}`,
          check_out: `${form.work_date}T${form.check_out || "17:00"}`,
        };
      } else if (form.request_type === "hr_letter") {
        payload = { purpose: form.purpose, language: form.language };
      } else if (form.request_type === "document_request") {
        payload = {
          document_name: form.document_name,
          note: form.note || null,
        };
        if (!payload.note) {
          delete payload.note;
        }
      } else {
        payload = { details: form.details };
        if (!payload.details) {
          delete payload.details;
        }
      }
      const created = await createEmployeeRequest({
        request_type: form.request_type,
        subject: form.subject,
        reason: form.reason || null,
        payload,
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

  if (!mayView && !mayCreate) {
    return <p className={errorTextClass}>{t("error.forbidden")}</p>;
  }

  const statusLabel = (status: string): string => {
    const key = `requests.status.${status}`;
    const label = t(key);
    return label === key ? status : label;
  };
  const typeLabel = (type: string): string => {
    const key = `requests.type.${type}`;
    const label = t(key);
    return label === key ? type : label;
  };

  return (
    <div className="space-y-6 py-8">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold">{t("requests.heading")}</h1>
        {mayCreate ? (
          <button
            type="button"
            className={primaryButtonClass}
            onClick={() => setFormOpen((open) => !open)}
          >
            {formOpen ? t("common.cancel") : t("requests.new")}
          </button>
        ) : null}
      </div>

      {formOpen ? (
        <form
          onSubmit={(event) => void save(event)}
          className="space-y-3 rounded-xl border border-slate-200 bg-white p-4"
        >
          <label className="block text-sm">
            <span className={labelClass}>{t("requests.type")}</span>
            <select
              className={inputClass}
              value={form.request_type}
              onChange={(e) => setField("request_type", e.target.value)}
            >
              {TYPE_OPTIONS.map((type) => (
                <option key={type} value={type}>
                  {typeLabel(type)}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className={labelClass}>{t("requests.subject")}</span>
            <input
              className={inputClass}
              value={form.subject}
              required
              maxLength={255}
              onChange={(e) => setField("subject", e.target.value)}
            />
          </label>

          {form.request_type === "attendance_correction" ? (
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="block text-sm">
                <span className={labelClass}>{t("requests.workDate")}</span>
                <input
                  type="date"
                  className={inputClass}
                  value={form.work_date}
                  required
                  onChange={(e) => setField("work_date", e.target.value)}
                />
              </label>
              <label className="block text-sm">
                <span className={labelClass}>{t("requests.checkIn")}</span>
                <input
                  type="time"
                  className={inputClass}
                  value={form.check_in}
                  required
                  onChange={(e) => setField("check_in", e.target.value)}
                />
              </label>
              <label className="block text-sm">
                <span className={labelClass}>{t("requests.checkOut")}</span>
                <input
                  type="time"
                  className={inputClass}
                  value={form.check_out}
                  required
                  onChange={(e) => setField("check_out", e.target.value)}
                />
              </label>
            </div>
          ) : null}

          {form.request_type === "hr_letter" ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-sm">
                <span className={labelClass}>{t("requests.purpose")}</span>
                <input
                  className={inputClass}
                  value={form.purpose}
                  required
                  maxLength={500}
                  onChange={(e) => setField("purpose", e.target.value)}
                />
              </label>
              <label className="block text-sm">
                <span className={labelClass}>{t("requests.language")}</span>
                <select
                  className={inputClass}
                  value={form.language}
                  onChange={(e) => setField("language", e.target.value)}
                >
                  <option value="en">{t("requests.language.en")}</option>
                  <option value="ar">{t("requests.language.ar")}</option>
                </select>
              </label>
            </div>
          ) : null}

          {form.request_type === "document_request" ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-sm">
                <span className={labelClass}>
                  {t("requests.documentName")}
                </span>
                <input
                  className={inputClass}
                  value={form.document_name}
                  required
                  maxLength={255}
                  onChange={(e) => setField("document_name", e.target.value)}
                />
              </label>
              <label className="block text-sm">
                <span className={labelClass}>{t("requests.note")}</span>
                <input
                  className={inputClass}
                  value={form.note}
                  maxLength={1000}
                  onChange={(e) => setField("note", e.target.value)}
                />
              </label>
            </div>
          ) : null}

          {form.request_type === "other" ? (
            <label className="block text-sm">
              <span className={labelClass}>{t("requests.details")}</span>
              <textarea
                className={inputClass}
                rows={3}
                maxLength={4000}
                value={form.details}
                onChange={(e) => setField("details", e.target.value)}
              />
            </label>
          ) : null}

          <label className="block text-sm">
            <span className={labelClass}>{t("requests.reason")}</span>
            <textarea
              className={inputClass}
              rows={2}
              maxLength={4000}
              value={form.reason}
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
          <span className={labelClass}>{t("approvals.filters.status")}</span>
          <select
            className={inputClass}
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="">�</option>
            {STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>
                {statusLabel(status)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className={labelClass}>{t("requests.type")}</span>
          <select
            className={inputClass}
            value={typeFilter}
            onChange={(e) => {
              setTypeFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="">�</option>
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
        <p className="text-sm text-slate-500">{t("requests.empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-4">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-2 pr-3">{t("requests.subject")}</th>
                <th className="py-2 pr-3">{t("requests.type")}</th>
                <th className="py-2 pr-3">{t("common.status")}</th>
                <th className="py-2 pr-3">{t("requests.submittedAt")}</th>
                <th className="py-2 pr-3">{t("requests.decidedAt")}</th>
                <th className="py-2 pr-3 text-right">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.id} className="border-b border-slate-100">
                  <td className="py-2 pr-3">{row.subject}</td>
                  <td className="py-2 pr-3">{typeLabel(row.request_type)}</td>
                  <td className="py-2 pr-3">{statusLabel(row.status)}</td>
                  <td className="py-2 pr-3">
                    {row.submitted_at
                      ? row.submitted_at.slice(0, 16).replace("T", " ")
                      : "—"}
                  </td>
                  <td className="py-2 pr-3">
                    {row.decided_at
                      ? row.decided_at.slice(0, 16).replace("T", " ")
                      : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <button
                      type="button"
                      className="text-blue-600 hover:underline"
                      onClick={() => setSelectedId(row.id)}
                    >
                      {t("requests.detail")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination meta={meta} onPage={setPage} />
        </div>
      )}

      <EmployeeRequestDetail
        requestId={selectedId}
        actions={{
          canSubmit: mayCreate,
          canCancel: mayCreate,
          canDecide: false,
        }}
        onClose={() => setSelectedId(null)}
        onChanged={() => void load()}
      />
    </div>
  );
}
