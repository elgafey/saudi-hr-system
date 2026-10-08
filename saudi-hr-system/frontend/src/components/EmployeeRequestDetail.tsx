import { useCallback, useEffect, useState } from "react";
import { useSession } from "../App";
import {
  approveEmployeeRequest,
  cancelEmployeeRequest,
  getEmployeeRequest,
  rejectEmployeeRequest,
  submitEmployeeRequest,
  type EmployeeRequest,
} from "../api";
import {
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  inputClass,
} from "../ui";

export interface RequestDetailActions {
  canSubmit: boolean;
  canCancel: boolean;
  canDecide: boolean;
}

interface Props {
  requestId: number | null;
  actions: RequestDetailActions;
  onClose: () => void;
  onChanged: () => void;
}

function formatStamp(value: string | null): string {
  if (!value) {
    return "—";
  }
  return value.slice(0, 16).replace("T", " ");
}

export default function EmployeeRequestDetail({
  requestId,
  actions,
  onClose,
  onChanged,
}: Props) {
  const { t } = useSession();
  const [detail, setDetail] = useState<EmployeeRequest | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [mode, setMode] = useState<"approve" | "reject" | "cancel" | null>(
    null,
  );

  const load = useCallback(async () => {
    if (requestId === null) {
      setDetail(null);
      return;
    }
    setLoading(true);
    setReason("");
    setMode(null);
    try {
      setDetail(await getEmployeeRequest(requestId));
      setError(null);
    } catch (err) {
      setDetail(null);
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [requestId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(kind: "submit" | "cancel" | "approve" | "reject") {
    if (requestId === null) {
      return;
    }
    if (kind === "reject" && !reason.trim()) {
      setError(t("approvals.rejectReasonRequired"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (kind === "submit") {
        await submitEmployeeRequest(requestId);
      } else if (kind === "cancel") {
        await cancelEmployeeRequest(requestId, reason.trim() || null);
      } else if (kind === "approve") {
        await approveEmployeeRequest(requestId, reason.trim() || null);
      } else {
        await rejectEmployeeRequest(requestId, reason.trim());
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

  if (requestId === null) {
    return null;
  }

  const typeLabel = detail
    ? (() => {
        const key = `requests.type.${detail.request_type}`;
        const label = t(key);
        return label === key ? detail.request_type : label;
      })()
    : "";
  const statusLabel = detail
    ? (() => {
        const key = `requests.status.${detail.status}`;
        const label = t(key);
        return label === key ? detail.status : label;
      })()
    : "";
  const payload = detail?.payload ?? {};
  const isDraft = detail?.status === "draft";
  const isDecidable = detail?.status === "submitted";
  const isCancellable = isDraft || isDecidable;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-4">
        <h3 className="text-sm font-semibold">{t("requests.detail")}</h3>
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
                {t("requests.type")}
              </dt>
              <dd className="text-sm">{typeLabel}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("common.status")}
              </dt>
              <dd className="text-sm">{statusLabel}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("requests.subject")}
              </dt>
              <dd className="text-sm">{detail.subject}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("requests.submittedAt")}
              </dt>
              <dd className="text-sm">{formatStamp(detail.submitted_at)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("requests.decidedAt")}
              </dt>
              <dd className="text-sm">{formatStamp(detail.decided_at)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("requests.approver")}
              </dt>
              <dd className="text-sm">
                {detail.approver_employee_id ?? "—"}
              </dd>
            </div>
          </dl>

          {detail.reason ? (
            <p className="text-sm">
              <span className="text-xs font-medium uppercase text-slate-500">
                {t("requests.reason")}:
              </span>{" "}
              {detail.reason}
            </p>
          ) : null}

          {detail.request_type === "attendance_correction" ? (
            <dl className="grid gap-4 sm:grid-cols-3">
              <div>
                <dt className="text-xs font-medium uppercase text-slate-500">
                  {t("requests.workDate")}
                </dt>
                <dd className="text-sm">
                  {String(payload.work_date ?? detail.work_date ?? "—")}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase text-slate-500">
                  {t("requests.checkIn")}
                </dt>
                <dd className="text-sm font-mono text-xs">
                  {String(payload.check_in ?? "—")}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase text-slate-500">
                  {t("requests.checkOut")}
                </dt>
                <dd className="text-sm font-mono text-xs">
                  {String(payload.check_out ?? "—")}
                </dd>
              </div>
            </dl>
          ) : null}

          {detail.request_type === "hr_letter" ? (
            <dl className="grid gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-xs font-medium uppercase text-slate-500">
                  {t("requests.purpose")}
                </dt>
                <dd className="text-sm">{String(payload.purpose ?? "—")}</dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase text-slate-500">
                  {t("requests.language")}
                </dt>
                <dd className="text-sm">
                  {payload.language === "ar"
                    ? t("requests.language.ar")
                    : payload.language === "en"
                      ? t("requests.language.en")
                      : "—"}
                </dd>
              </div>
            </dl>
          ) : null}

          {detail.request_type === "document_request" ? (
            <dl className="grid gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-xs font-medium uppercase text-slate-500">
                  {t("requests.documentName")}
                </dt>
                <dd className="text-sm">
                  {String(payload.document_name ?? "—")}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase text-slate-500">
                  {t("requests.note")}
                </dt>
                <dd className="text-sm">{String(payload.note ?? "—")}</dd>
              </div>
            </dl>
          ) : null}

          {detail.request_type === "other" ? (
            <p className="text-sm">
              <span className="text-xs font-medium uppercase text-slate-500">
                {t("requests.details")}:
              </span>{" "}
              {String(payload.details ?? "—")}
            </p>
          ) : null}

          {detail.decision_reason ? (
            <p className="text-sm">
              <span className="text-xs font-medium uppercase text-slate-500">
                {t("approvals.decisionReason")}:
              </span>{" "}
              {detail.decision_reason}
            </p>
          ) : null}
          {detail.cancel_reason ? (
            <p className="text-sm">
              <span className="text-xs font-medium uppercase text-slate-500">
                {t("requests.cancelReason")}:
              </span>{" "}
              {detail.cancel_reason}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
            {actions.canSubmit && isDraft ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={() => void act("submit")}
              >
                {t("requests.submit")}
              </button>
            ) : null}
            {actions.canCancel && isCancellable ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={() => setMode(mode === "cancel" ? null : "cancel")}
              >
                {t("requests.cancel")}
              </button>
            ) : null}
            {actions.canDecide && isDecidable ? (
              <>
                <button
                  type="button"
                  className={ghostButtonClass}
                  disabled={busy}
                  onClick={() => setMode(mode === "approve" ? null : "approve")}
                >
                  {t("approvals.approve")}
                </button>
                <button
                  type="button"
                  className={ghostButtonClass}
                  disabled={busy}
                  onClick={() => setMode(mode === "reject" ? null : "reject")}
                >
                  {t("approvals.reject")}
                </button>
              </>
            ) : null}
            {mode ? (
              <span className="flex items-center gap-2">
                <input
                  className={`${inputClass} w-64`}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder={
                    mode === "reject"
                      ? t("approvals.rejectReason")
                      : mode === "cancel"
                        ? t("requests.cancelReason")
                        : t("approvals.decisionReason")
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
              </span>
            ) : null}
          </div>

          <div>
            <h4 className="mb-2 text-xs font-medium uppercase text-slate-500">
              {t("requests.events")}
            </h4>
            {detail.events.length === 0 ? (
              <p className="text-sm text-slate-500">{t("requests.noEvents")}</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {detail.events.map((event) => {
                  const key = `requests.event.${event.event_type}`;
                  const label = t(key);
                  return (
                    <li key={event.id} className="flex flex-wrap gap-2">
                      <span className="text-slate-800">
                        {label === key ? event.event_type : label}
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
