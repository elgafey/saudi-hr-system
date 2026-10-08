import { useCallback, useEffect, useState } from "react";
import { useSession } from "../App";
import {
  getEmployeeUserLink,
  getUser,
  linkEmployeeUser,
  listUsers,
  unlinkEmployeeUser,
  type EmployeeUserLink,
} from "../api";
import SearchSelect, { type SearchOption } from "./SearchSelect";
import {
  dangerButtonClass,
  errorMessage,
  errorTextClass,
  primaryButtonClass,
} from "../ui";

interface Props {
  employeeId: number;
  companyId: number;
}

export default function UserAccountPanel({ employeeId, companyId }: Props) {
  const { t, can } = useSession();
  const [link, setLink] = useState<EmployeeUserLink | null>(null);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getEmployeeUserLink(employeeId);
      setLink(result);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [employeeId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function loadUsers(search: string): Promise<SearchOption[]> {
    return listUsers({ company_id: companyId, search, limit: 10 }).then(
      (items) =>
        items.map((row) => ({
          id: row.id,
          label: `${row.full_name} — ${row.email}`,
        })),
    );
  }

  async function linkUser() {
    if (selectedUserId === "") {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await linkEmployeeUser(employeeId, Number(selectedUserId));
      setSelectedUserId("");
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setBusy(false);
    }
  }

  async function unlink() {
    if (!window.confirm(t("account.unlinkConfirm"))) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await unlinkEmployeeUser(employeeId);
      await load();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold">{t("account.title")}</h2>

      {error ? <p className={errorTextClass}>{error}</p> : null}

      {loading ? (
        <p className="text-sm text-slate-500">{t("common.loading")}</p>
      ) : link?.linked && link.user ? (
        <div className="space-y-3">
          <p className="text-sm">{t("account.linked")}</p>
          <div className="flex flex-wrap items-center gap-3 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
            <span className="font-medium">{link.user.full_name}</span>
            <span className="text-slate-600">{link.user.email}</span>
            <span
              className={`rounded px-2 py-0.5 text-xs ${
                link.user.is_active
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-slate-200 text-slate-600"
              }`}
            >
              {t(link.user.is_active ? "status.active" : "status.inactive")}
            </span>
          </div>
          {can("employee_user_link.manage") ? (
            <button
              type="button"
              onClick={() => void unlink()}
              disabled={busy}
              className={dangerButtonClass}
            >
              {t("account.unlink")}
            </button>
          ) : null}
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">{t("account.notLinked")}</p>
          {can("employee_user_link.manage") ? (
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-64 flex-1">
                <SearchSelect
                  label={t("account.searchUser")}
                  value={selectedUserId}
                  onChange={setSelectedUserId}
                  load={loadUsers}
                  resolve={(id) =>
                    getUser(id).then((row) => `${row.full_name} — ${row.email}`)
                  }
                />
              </div>
              <button
                type="button"
                onClick={() => void linkUser()}
                disabled={busy || selectedUserId === ""}
                className={primaryButtonClass}
              >
                {t("account.link")}
              </button>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
