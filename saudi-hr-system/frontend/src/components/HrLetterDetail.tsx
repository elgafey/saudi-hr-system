import { useCallback, useEffect, useState } from "react";
import { useSession } from "../App";
import {
  cancelHrLetter,
  getHrLetter,
  issueHrLetter,
  updateHrLetter,
  voidHrLetter,
  type HrLetter,
} from "../api";
import {
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  inputClass,
} from "../ui";

export interface LetterDetailActions {
  canEdit: boolean;
  canIssue: boolean;
  canVoid: boolean;
}

interface Props {
  letterId: number | null;
  actions: LetterDetailActions;
  onClose: () => void;
  onChanged: () => void;
}

type Mode = "edit" | "cancel" | "void" | null;

function formatStamp(value: string | null): string {
  if (!value) {
    return "—";
  }
  return value.slice(0, 16).replace("T", " ");
}

const FIELD_ORDER = [
  "company_name",
  "company_cr",
  "company_address",
  "company_city",
  "employee_name",
  "employee_number",
  "identity_number",
  "position",
  "department",
  "branch",
  "employment_type",
  "employment_status",
  "hire_date",
  "contract_number",
  "contract_start_date",
  "contract_end_date",
  "basic_salary",
  "currency",
  "salary_effective_from",
  "branch_address",
  "branch_city",
];

const VALUE_KEYS = new Set([
  "employment_type",
  "employment_status",
]);

export default function HrLetterDetail({
  letterId,
  actions,
  onClose,
  onChanged,
}: Props) {
  const { t } = useSession();
  const [detail, setDetail] = useState<HrLetter | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<Mode>(null);
  const [reason, setReason] = useState("");
  const [editPurpose, setEditPurpose] = useState("");
  const [editLanguage, setEditLanguage] = useState("en");

  const load = useCallback(async () => {
    if (letterId === null) {
      setDetail(null);
      return;
    }
    setLoading(true);
    setReason("");
    setMode(null);
    try {
      setDetail(await getHrLetter(letterId));
      setError(null);
    } catch (err) {
      setDetail(null);
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [letterId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function openEdit() {
    if (!detail) {
      return;
    }
    setEditPurpose(detail.purpose ?? "");
    setEditLanguage(detail.language);
    setMode("edit");
  }

  async function act(kind: "issue" | "cancel" | "void") {
    if (letterId === null) {
      return;
    }
    if (kind === "void" && !reason.trim()) {
      setError(t("letters.voidReasonRequired"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (kind === "issue") {
        await issueHrLetter(letterId);
      } else if (kind === "cancel") {
        await cancelHrLetter(letterId, reason.trim() || null);
      } else {
        await voidHrLetter(letterId, reason.trim());
      }
      setReason("");
      setMode(null);
      await load();
      onChanged();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusy(false);
    }
  }

  async function saveEdit() {
    if (letterId === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await updateHrLetter(letterId, {
        purpose: editPurpose.trim() || null,
        language: editLanguage,
      });
      setMode(null);
      await load();
      onChanged();
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setBusy(false);
    }
  }

  if (letterId === null) {
    return null;
  }

  const fieldLabel = (name: string): string => {
    const key = `letters.field.${name}`;
    const label = t(key);
    return label === key ? name : label;
  };

  const valueLabel = (name: string, value: string): string => {
    if (!VALUE_KEYS.has(name)) {
      return value;
    }
    const key = `letters.value.${value}`;
    const label = t(key);
    return label === key ? value : label;
  };

  const statusLabel = detail
    ? (() => {
        const key = `letters.status.${detail.status}`;
        const label = t(key);
        return label === key ? detail.status : label;
      })()
    : "";

  const typeLabel = detail
    ? (() => {
        const key = `letters.type.${detail.letter_type}`;
        const label = t(key);
        return label === key ? detail.letter_type : label;
      })()
    : "";

  const isDraft = detail?.status === "draft";
  const isIssued = detail?.status === "issued";

  const contentFields = detail
    ? FIELD_ORDER.filter((name) => name in detail.content).concat(
        Object.keys(detail.content).filter((name) => !FIELD_ORDER.includes(name)),
      )
    : [];

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-4">
        <h3 className="text-sm font-semibold">{t("letters.detail")}</h3>
        <button
          type="button"
          className="text-sm text-slate-500 hover:underline"
          onClick={onClose}
        >
          {t("common.close")}
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">{t("common.loading")}</p>
      ) : error && !detail ? (
        <p className={errorTextClass}>{error}</p>
      ) : detail ? (
        <div className="space-y-4">
          <dl className="grid gap-4 sm:grid-cols-3">
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("letters.reference")}
              </dt>
              <dd className="text-sm font-mono">{detail.reference}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("common.status")}
              </dt>
              <dd className="text-sm">{statusLabel}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("letters.type")}
              </dt>
              <dd className="text-sm">{typeLabel}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("letters.language")}
              </dt>
              <dd className="text-sm">{detail.language.toUpperCase()}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("letters.employee")}
              </dt>
              <dd className="text-sm font-mono text-xs">
                #{detail.employee_id}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("letters.issuedAt")}
              </dt>
              <dd className="text-sm">{formatStamp(detail.issued_at)}</dd>
            </div>
          </dl>

          <p className="text-sm">
            <span className="text-xs font-medium uppercase text-slate-500">
              {t("letters.purpose")}:
            </span>{" "}
            {detail.purpose ?? "—"}
          </p>

          {detail.cancel_reason ? (
            <p className="text-sm">
              <span className="text-xs font-medium uppercase text-slate-500">
                {t("letters.cancelReason")}:
              </span>{" "}
              {detail.cancel_reason}
            </p>
          ) : null}
          {detail.void_reason ? (
            <p className="text-sm">
              <span className="text-xs font-medium uppercase text-slate-500">
                {t("letters.voidReason")}:
              </span>{" "}
              {detail.void_reason}
            </p>
          ) : null}

          <div>
            <h4 className="mb-2 text-xs font-medium uppercase text-slate-500">
              {t("letters.content")}
            </h4>
            <dl className="grid gap-3 rounded-lg bg-slate-50 p-3 sm:grid-cols-3">
              {contentFields.map((name) => {
                const value = detail.content[name];
                return (
                  <div key={name}>
                    <dt className="text-xs font-medium uppercase text-slate-500">
                      {fieldLabel(name)}
                    </dt>
                    <dd className="text-sm">
                      {value === null || value === ""
                        ? "—"
                        : valueLabel(name, value)}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
            {actions.canEdit && isDraft && mode !== "edit" ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={openEdit}
              >
                {t("letters.editAction")}
              </button>
            ) : null}
            {actions.canIssue && isDraft && mode === null ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={() => void act("issue")}
              >
                {t("letters.issue")}
              </button>
            ) : null}
            {actions.canEdit && isDraft && mode === null ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={() => setMode("cancel")}
              >
                {t("letters.cancel")}
              </button>
            ) : null}
            {actions.canVoid && isIssued && mode === null ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={() => setMode("void")}
              >
                {t("letters.void")}
              </button>
            ) : null}

            {mode === "edit" ? (
              <span className="flex flex-wrap items-center gap-2">
                <input
                  className={`${inputClass} w-64`}
                  value={editPurpose}
                  maxLength={500}
                  onChange={(e) => setEditPurpose(e.target.value)}
                  placeholder={t("letters.editPurpose")}
                />
                <select
                  className={`${inputClass} w-32`}
                  value={editLanguage}
                  onChange={(e) => setEditLanguage(e.target.value)}
                >
                  <option value="en">EN</option>
                  <option value="ar">AR</option>
                </select>
                <button
                  type="button"
                  className={ghostButtonClass}
                  disabled={busy}
                  onClick={() => void saveEdit()}
                >
                  {t("common.save")}
                </button>
                <button
                  type="button"
                  className={ghostButtonClass}
                  disabled={busy}
                  onClick={() => setMode(null)}
                >
                  {t("common.cancel")}
                </button>
              </span>
            ) : null}

            {mode === "cancel" || mode === "void" ? (
              <span className="flex items-center gap-2">
                <input
                  className={`${inputClass} w-64`}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder={
                    mode === "void"
                      ? t("letters.voidReasonPlaceholder")
                      : t("letters.cancelReasonPlaceholder")
                  }
                />
                <button
                  type="button"
                  className={ghostButtonClass}
                  disabled={busy}
                  onClick={() => void act(mode)}
                >
                  {t("common.save")}
                </button>
                <button
                  type="button"
                  className={ghostButtonClass}
                  disabled={busy}
                  onClick={() => setMode(null)}
                >
                  {t("common.cancel")}
                </button>
              </span>
            ) : null}
          </div>

          <div>
            <h4 className="mb-2 text-xs font-medium uppercase text-slate-500">
              {t("letters.events")}
            </h4>
            {detail.events.length === 0 ? (
              <p className="text-sm text-slate-500">{t("letters.noEvents")}</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {detail.events.map((event) => {
                  const key = `letters.event.${event.action}`;
                  const label = t(key);
                  return (
                    <li key={event.id} className="flex flex-wrap gap-2">
                      <span className="text-slate-800">
                        {label === key ? event.action : label}
                      </span>
                      <span className="text-slate-500">
                        {event.actor_name}
                      </span>
                      <span className="text-slate-400">
                        {formatStamp(event.created_at)}
                      </span>
                      {event.note ? (
                        <span className="text-slate-500">{event.note}</span>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {error ? <p className={errorTextClass}>{error}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
