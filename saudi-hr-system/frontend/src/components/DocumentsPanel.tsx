import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSession } from "../App";
import {
  deleteEmployeeDocument,
  downloadEmployeeDocument,
  getEmployeeDocumentVisibility,
  listDocumentTypes,
  listEmployeeDocuments,
  setEmployeeDocumentVisibility,
  updateEmployeeDocument,
  uploadEmployeeDocument,
  type EmployeeDocument,
  type EmployeeDocumentType,
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

function nullable(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${bytes} B`;
}

interface UploadFormState {
  document_type_id: string;
  document_number: string;
  issue_date: string;
  expiry_date: string;
  notes: string;
}

const emptyUpload: UploadFormState = {
  document_type_id: "",
  document_number: "",
  issue_date: "",
  expiry_date: "",
  notes: "",
};

interface Props {
  employeeId: number;
}

export default function DocumentsPanel({ employeeId }: Props) {
  const { t, can, locale } = useSession();
  const [rows, setRows] = useState<EmployeeDocument[]>([]);
  const [types, setTypes] = useState<EmployeeDocumentType[]>([]);
  const [meta, setMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [form, setForm] = useState<UploadFormState | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [visibility, setVisibility] = useState<Record<number, boolean | undefined>>(
    {},
  );
  const [togglingId, setTogglingId] = useState<number | null>(null);

  const showVisibility =
    can("employee_document.update") || can("employee_document.view");

  const set = (key: keyof UploadFormState, value: string) =>
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listEmployeeDocuments(employeeId, {
        page,
        page_size: pageSize,
      });
      setRows(res.items);
      setMeta(res.page);
      setError(null);
      if (can("employee_document.update") || can("employee_document.view")) {
        const entries = await Promise.all(
          res.items.map(async (row) => {
            try {
              const state = await getEmployeeDocumentVisibility(row.id);
              return [row.id, state.employee_visible] as const;
            } catch {
              return [row.id, undefined] as const;
            }
          }),
        );
        setVisibility(Object.fromEntries(entries));
      }
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [employeeId, page, t, can]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    listDocumentTypes()
      .then((items) => {
        if (!cancelled) {
          setTypes(items);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  function typeName(typeId: number): string {
    const found = types.find((row) => row.id === typeId);
    if (!found) {
      return `#${typeId}`;
    }
    return locale === "ar" ? found.name_ar : found.name_en;
  }

  async function submitUpload(event: FormEvent) {
    event.preventDefault();
    if (form === null || file === null) {
      return;
    }
    setUploading(true);
    setError(null);
    const data = new FormData();
    data.append("document_type_id", form.document_type_id);
    if (form.document_number.trim()) {
      data.append("document_number", form.document_number.trim());
    }
    if (form.issue_date) {
      data.append("issue_date", form.issue_date);
    }
    if (form.expiry_date) {
      data.append("expiry_date", form.expiry_date);
    }
    if (form.notes.trim()) {
      data.append("notes", form.notes.trim());
    }
    data.append("file", file);
    try {
      await uploadEmployeeDocument(employeeId, data);
      setForm(null);
      setFile(null);
      setPage(1);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setUploading(false);
    }
  }

  async function submitEdit(event: FormEvent) {
    event.preventDefault();
    if (form === null || editingId === null) {
      return;
    }
    setUploading(true);
    setError(null);
    try {
      await updateEmployeeDocument(employeeId, editingId, {
        document_type_id: form.document_type_id
          ? Number(form.document_type_id)
          : undefined,
        document_number: nullable(form.document_number),
        issue_date: nullable(form.issue_date),
        expiry_date: nullable(form.expiry_date),
        notes: nullable(form.notes),
      });
      setForm(null);
      setEditingId(null);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setUploading(false);
    }
  }

  async function download(row: EmployeeDocument) {
    try {
      const { blob, filename } = await downloadEmployeeDocument(
        employeeId,
        row.id,
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename || row.file_name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  async function remove(row: EmployeeDocument) {
    if (!window.confirm(t("documents.deleteConfirm"))) {
      return;
    }
    try {
      await deleteEmployeeDocument(employeeId, row.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    }
  }

  async function toggleVisibility(row: EmployeeDocument) {
    const current = visibility[row.id];
    if (current === undefined) {
      return;
    }
    setTogglingId(row.id);
    setError(null);
    try {
      const next = await setEmployeeDocumentVisibility(row.id, !current);
      setVisibility((prev) => ({
        ...prev,
        [row.id]: next.employee_visible,
      }));
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setTogglingId(null);
    }
  }

  function startCreate() {
    setEditingId(null);
    setFile(null);
    setForm({
      ...emptyUpload,
      document_type_id: types.length > 0 ? String(types[0].id) : "",
    });
  }

  function startEdit(row: EmployeeDocument) {
    setEditingId(row.id);
    setFile(null);
    setForm({
      document_type_id: String(row.document_type_id),
      document_number: row.document_number ?? "",
      issue_date: row.issue_date ?? "",
      expiry_date: row.expiry_date ?? "",
      notes: row.notes ?? "",
    });
  }

  const isCreate = editingId === null;

  return (
    <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t("documents.title")}</h2>
        {can("employee_document.create") && form === null ? (
          <button type="button" onClick={startCreate} className={primaryButtonClass}>
            {t("documents.upload")}
          </button>
        ) : null}
      </div>

      {error ? <p className={errorTextClass}>{error}</p> : null}

      {form ? (
        <form
          onSubmit={isCreate ? submitUpload : submitEdit}
          className="grid gap-3 sm:grid-cols-3"
        >
          <label className="block">
            <span className={labelClass}>{t("documents.type")}</span>
            <select
              value={form.document_type_id}
              onChange={(event) => set("document_type_id", event.target.value)}
              required
              className={inputClass}
            >
              <option value="" disabled>
                —
              </option>
              {types.map((row) => (
                <option key={row.id} value={String(row.id)}>
                  {locale === "ar" ? row.name_ar : row.name_en}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className={labelClass}>{t("documents.number")}</span>
            <input
              type="text"
              maxLength={50}
              value={form.document_number}
              onChange={(event) => set("document_number", event.target.value)}
              className={inputClass}
            />
          </label>
          {isCreate ? (
            <label className="block">
              <span className={labelClass}>{t("documents.file")}</span>
              <input
                type="file"
                required
                accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                className="block w-full text-sm"
              />
            </label>
          ) : (
            <div />
          )}
          <label className="block">
            <span className={labelClass}>{t("documents.issue")}</span>
            <input
              type="date"
              value={form.issue_date}
              onChange={(event) => set("issue_date", event.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block">
            <span className={labelClass}>{t("documents.expiry")}</span>
            <input
              type="date"
              value={form.expiry_date}
              onChange={(event) => set("expiry_date", event.target.value)}
              className={inputClass}
            />
          </label>
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
            <button
              type="submit"
              disabled={uploading}
              className={primaryButtonClass}
            >
              {uploading ? t("common.saving") : t("common.save")}
            </button>
            <button
              type="button"
              onClick={() => {
                setForm(null);
                setEditingId(null);
                setFile(null);
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
        <p className="text-sm text-slate-500">{t("documents.empty")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-2 pr-3">{t("documents.type")}</th>
                <th className="py-2 pr-3">{t("documents.file")}</th>
                <th className="py-2 pr-3">{t("documents.number")}</th>
                <th className="py-2 pr-3">{t("documents.issue")}</th>
                <th className="py-2 pr-3">{t("documents.expiry")}</th>
                <th className="py-2 pr-3">{t("documents.size")}</th>
                {showVisibility ? (
                  <th className="py-2 pr-3">{t("documents.visibility")}</th>
                ) : null}
                <th className="py-2 pr-3 text-right">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-slate-100">
                  <td className="py-2 pr-3">{typeName(row.document_type_id)}</td>
                  <td className="py-2 pr-3">{row.file_name}</td>
                  <td className="py-2 pr-3 font-mono text-xs">
                    {row.document_number ?? "—"}
                  </td>
                  <td className="py-2 pr-3">{row.issue_date ?? "—"}</td>
                  <td className="py-2 pr-3">{row.expiry_date ?? "—"}</td>
                  <td className="py-2 pr-3">{formatSize(row.file_size)}</td>
                  {showVisibility ? (
                    <td className="py-2 pr-3">
                      {visibility[row.id] === undefined ? (
                        <span className="text-slate-400">—</span>
                      ) : can("employee_document.update") ? (
                        <button
                          type="button"
                          disabled={togglingId === row.id}
                          onClick={() => void toggleVisibility(row)}
                          className={ghostButtonClass}
                        >
                          {visibility[row.id]
                            ? t("documents.employeeVisible")
                            : t("documents.hiddenFromEmployee")}
                        </button>
                      ) : (
                        <span className="text-slate-600">
                          {visibility[row.id]
                            ? t("documents.employeeVisible")
                            : t("documents.hiddenFromEmployee")}
                        </span>
                      )}
                    </td>
                  ) : null}
                  <td className="py-2 pr-3 text-right">
                    <div className="inline-flex gap-1">
                      {can("employee_document.download") ? (
                        <button
                          type="button"
                          onClick={() => void download(row)}
                          className={ghostButtonClass}
                        >
                          {t("documents.download")}
                        </button>
                      ) : null}
                      {can("employee_document.update") ? (
                        <button
                          type="button"
                          onClick={() => startEdit(row)}
                          className={ghostButtonClass}
                        >
                          {t("common.edit")}
                        </button>
                      ) : null}
                      {can("employee_document.delete") ? (
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
