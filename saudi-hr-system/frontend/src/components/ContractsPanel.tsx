import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSession } from "../App";
import {
  createEmployeeContract,
  deleteEmployeeContract,
  listEmployeeContracts,
  updateEmployeeContract,
  type EmployeeContract,
  type PageMeta,
} from "../api";
import Pagination from "./Pagination";
import {
  dangerButtonClass,
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../ui";

const pageSize = 10;

interface ContractFormState {
  contract_type: string;
  status: string;
  contract_number: string;
  start_date: string;
  end_date: string;
  signed_date: string;
  termination_date: string;
  termination_reason: string;
  basic_salary: string;
  currency: string;
  notes: string;
}

const emptyForm: ContractFormState = {
  contract_type: "fixed_term",
  status: "draft",
  contract_number: "",
  start_date: "",
  end_date: "",
  signed_date: "",
  termination_date: "",
  termination_reason: "",
  basic_salary: "",
  currency: "SAR",
  notes: "",
};

function nullable(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function TextField({
  label,
  value,
  onChange,
  type,
  required,
  maxLength,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
  maxLength?: number;
}) {
  return (
    <label className="block">
      <span className={labelClass}>{label}</span>
      <input
        type={type ?? "text"}
        required={required}
        maxLength={maxLength}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      />
    </label>
  );
}

interface Props {
  employeeId: number;
  companyId: number;
}

export default function ContractsPanel({ employeeId, companyId }: Props) {
  const { t, can } = useSession();
  const [rows, setRows] = useState<EmployeeContract[]>([]);
  const [meta, setMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<ContractFormState | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (key: keyof ContractFormState, value: string) =>
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listEmployeeContracts(employeeId, {
        page,
        page_size: pageSize,
      });
      setRows(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [employeeId, page, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function startCreate() {
    setEditingId(null);
    setForm({ ...emptyForm });
  }

  function startEdit(row: EmployeeContract) {
    setEditingId(row.id);
    setForm({
      contract_type: row.contract_type,
      status: row.status,
      contract_number: row.contract_number ?? "",
      start_date: row.start_date,
      end_date: row.end_date ?? "",
      signed_date: row.signed_date ?? "",
      termination_date: row.termination_date ?? "",
      termination_reason: row.termination_reason ?? "",
      basic_salary: row.basic_salary !== null ? String(row.basic_salary) : "",
      currency: row.currency,
      notes: row.notes ?? "",
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (form === null) {
      return;
    }
    setSaving(true);
    setError(null);
    const payload = {
      company_id: companyId,
      contract_type: form.contract_type,
      status: form.status,
      contract_number: nullable(form.contract_number),
      start_date: form.start_date,
      end_date: nullable(form.end_date),
      signed_date: nullable(form.signed_date),
      termination_date: nullable(form.termination_date),
      termination_reason: nullable(form.termination_reason),
      basic_salary: form.basic_salary === "" ? null : Number(form.basic_salary),
      currency: form.currency.trim() || "SAR",
      notes: nullable(form.notes),
    };
    try {
      if (editingId === null) {
        await createEmployeeContract(employeeId, payload);
      } else {
        await updateEmployeeContract(employeeId, editingId, payload);
      }
      setForm(null);
      setEditingId(null);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setSaving(false);
    }
  }

  async function remove(row: EmployeeContract) {
    if (!window.confirm(t("contracts.deleteConfirm"))) {
      return;
    }
    try {
      await deleteEmployeeContract(employeeId, row.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  const typeLabel = (value: string) => t(`contractType.${value}`);
  const statusLabel = (value: string) => t(`contractStatus.${value}`);

  return (
    <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t("contracts.title")}</h2>
        {can("employee_contract.create") && form === null ? (
          <button type="button" onClick={startCreate} className={primaryButtonClass}>
            {t("contracts.new")}
          </button>
        ) : null}
      </div>

      {error ? <p className={errorTextClass}>{error}</p> : null}

      {form ? (
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-3">
          <label className="block">
            <span className={labelClass}>{t("contracts.type")}</span>
            <select
              value={form.contract_type}
              onChange={(event) => set("contract_type", event.target.value)}
              className={inputClass}
            >
              <option value="fixed_term">{t("contractType.fixed_term")}</option>
              <option value="indefinite">{t("contractType.indefinite")}</option>
              <option value="part_time">{t("contractType.part_time")}</option>
              <option value="temporary">{t("contractType.temporary")}</option>
              <option value="probation">{t("contractType.probation")}</option>
            </select>
          </label>
          <label className="block">
            <span className={labelClass}>{t("common.status")}</span>
            <select
              value={form.status}
              onChange={(event) => set("status", event.target.value)}
              className={inputClass}
            >
              <option value="draft">{t("contractStatus.draft")}</option>
              <option value="active">{t("contractStatus.active")}</option>
              <option value="expired">{t("contractStatus.expired")}</option>
              <option value="terminated">{t("contractStatus.terminated")}</option>
              <option value="cancelled">{t("contractStatus.cancelled")}</option>
            </select>
          </label>
          <TextField
            label={t("contracts.number")}
            value={form.contract_number}
            onChange={(value) => set("contract_number", value)}
            maxLength={50}
          />
          <TextField
            label={t("contracts.start")}
            value={form.start_date}
            onChange={(value) => set("start_date", value)}
            type="date"
            required
          />
          <TextField
            label={t("contracts.end")}
            value={form.end_date}
            onChange={(value) => set("end_date", value)}
            type="date"
          />
          <TextField
            label={t("contracts.signed")}
            value={form.signed_date}
            onChange={(value) => set("signed_date", value)}
            type="date"
          />
          <TextField
            label={t("contracts.termination")}
            value={form.termination_date}
            onChange={(value) => set("termination_date", value)}
            type="date"
          />
          <TextField
            label={t("contracts.terminationReason")}
            value={form.termination_reason}
            onChange={(value) => set("termination_reason", value)}
            maxLength={500}
          />
          <TextField
            label={t("contracts.salary")}
            value={form.basic_salary}
            onChange={(value) => set("basic_salary", value)}
            type="number"
          />
          <TextField
            label={t("contracts.currency")}
            value={form.currency}
            onChange={(value) => set("currency", value)}
            maxLength={3}
          />
          <label className="block sm:col-span-3">
            <span className={labelClass}>{t("employees.notes")}</span>
            <textarea
              rows={2}
              maxLength={2000}
              value={form.notes}
              onChange={(event) => set("notes", event.target.value)}
              className={inputClass}
            />
          </label>
          <div className="flex gap-2 sm:col-span-3">
            <button type="submit" disabled={saving} className={primaryButtonClass}>
              {saving ? t("common.saving") : t("common.save")}
            </button>
            <button
              type="button"
              onClick={() => {
                setForm(null);
                setEditingId(null);
              }}
              className={ghostButtonClass}
            >
              {t("common.cancel")}
            </button>
          </div>
        </form>
      ) : null}

      {loading ? (
        <p className="text-sm text-slate-500">{t("common.loading")}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500">{t("contracts.empty")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-2 pr-3">{t("contracts.type")}</th>
                <th className="py-2 pr-3">{t("common.status")}</th>
                <th className="py-2 pr-3">{t("contracts.number")}</th>
                <th className="py-2 pr-3">{t("contracts.start")}</th>
                <th className="py-2 pr-3">{t("contracts.end")}</th>
                <th className="py-2 pr-3">{t("contracts.salary")}</th>
                <th className="py-2 pr-3 text-right">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-slate-100">
                  <td className="py-2 pr-3">{typeLabel(row.contract_type)}</td>
                  <td className="py-2 pr-3">
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">
                      {statusLabel(row.status)}
                    </span>
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs">
                    {row.contract_number ?? "—"}
                  </td>
                  <td className="py-2 pr-3">{row.start_date}</td>
                  <td className="py-2 pr-3">{row.end_date ?? "—"}</td>
                  <td className="py-2 pr-3">
                    {row.basic_salary !== null
                      ? `${row.basic_salary} ${row.currency}`
                      : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <div className="inline-flex gap-1">
                      {can("employee_contract.update") ? (
                        <button
                          type="button"
                          onClick={() => startEdit(row)}
                          className={ghostButtonClass}
                        >
                          {t("common.edit")}
                        </button>
                      ) : null}
                      {can("employee_contract.delete") ? (
                        <button
                          type="button"
                          onClick={() => void remove(row)}
                          className={dangerButtonClass}
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
        </div>
      )}

      <Pagination meta={meta} onPage={setPage} />
    </section>
  );
}
