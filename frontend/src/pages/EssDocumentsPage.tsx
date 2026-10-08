import { useCallback, useEffect, useState } from "react";
import { useSession } from "../App";
import {
  downloadMyDocument,
  myDocuments,
  type EmployeeDocument,
  type PageMeta,
} from "../api";
import Pagination from "../components/Pagination";
import { errorMessage, errorTextClass } from "../ui";

const pageSize = 20;

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${bytes} B`;
}

export default function EssDocumentsPage() {
  const { t } = useSession();
  const [rows, setRows] = useState<EmployeeDocument[]>([]);
  const [meta, setMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await myDocuments({ page, page_size: pageSize });
      setRows(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [page, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function download(row: EmployeeDocument) {
    setBusyId(row.id);
    setError(null);
    try {
      const { blob, filename } = await downloadMyDocument(row.id);
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
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="space-y-4">
      <p className="text-xs text-slate-500">
        {t("ess.documents.gatingNote")}
      </p>
      {error ? <p className={errorTextClass}>{error}</p> : null}
      {loading ? (
        <p className="text-sm text-slate-500">{t("common.loading")}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500">{t("ess.documents.empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-4">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-2 pr-3">{t("documents.file")}</th>
                <th className="py-2 pr-3">{t("documents.number")}</th>
                <th className="py-2 pr-3">{t("documents.issue")}</th>
                <th className="py-2 pr-3">{t("documents.expiry")}</th>
                <th className="py-2 pr-3">{t("documents.size")}</th>
                <th className="py-2 pr-3 text-right">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-slate-100">
                  <td className="py-2 pr-3">{row.file_name}</td>
                  <td className="py-2 pr-3 font-mono text-xs">
                    {row.document_number ?? "—"}
                  </td>
                  <td className="py-2 pr-3">{row.issue_date ?? "—"}</td>
                  <td className="py-2 pr-3">{row.expiry_date ?? "—"}</td>
                  <td className="py-2 pr-3">{formatSize(row.file_size)}</td>
                  <td className="py-2 pr-3 text-right">
                    <button
                      type="button"
                      disabled={busyId === row.id}
                      onClick={() => void download(row)}
                      className="text-blue-600 hover:underline disabled:opacity-50"
                    >
                      {t("documents.download")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination meta={meta} onPage={setPage} />
        </div>
      )}
    </section>
  );
}
