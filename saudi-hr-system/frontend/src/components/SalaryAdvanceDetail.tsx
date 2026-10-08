import { useCallback, useEffect, useState } from "react";
import { useSession } from "../App";
import {
  approveSalaryAdvance,
  cancelSalaryAdvance,
  disburseSalaryAdvance,
  getSalaryAdvance,
  rejectSalaryAdvance,
  settleSalaryAdvance,
  submitSalaryAdvance,
  updateSalaryAdvance,
  type SalaryAdvance,
} from "../api";
import {
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  inputClass,
} from "../ui";

export interface AdvanceDetailActions {
  canEdit: boolean;
  canSubmit: boolean;
  canCancel: boolean;
  canApprove: boolean;
  canReject: boolean;
  canDisburse: boolean;
  canSettle: boolean;
}

interface Props {
  advanceId: number | null;
  actions: AdvanceDetailActions;
  onClose: () => void;
  onChanged: () => void;
}

type Mode =
  | "edit"
  | "cancel"
  | "approve"
  | "reject"
  | "disburse"
  | "settle"
  | null;

type Action = "submit" | Exclude<Mode, "edit" | null>;

function formatStamp(value: string | null): string {
  if (!value) {
    return "—";
  }
  return value.slice(0, 16).replace("T", " ");
}

export default function SalaryAdvanceDetail({
  advanceId,
  actions,
  onClose,
  onChanged,
}: Props) {
  const { t } = useSession();
  const [detail, setDetail] = useState<SalaryAdvance | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<Mode>(null);
  const [reason, setReason] = useState("");
  const [editAmount, setEditAmount] = useState("");
  const [editDate, setEditDate] = useState("");
  const [installment, setInstallment] = useState("");

  const load = useCallback(async () => {
    if (advanceId === null) {
      setDetail(null);
      return;
    }
    setLoading(true);
    setReason("");
    setInstallment("");
    setMode(null);
    try {
      setDetail(await getSalaryAdvance(advanceId));
      setError(null);
    } catch (err) {
      setDetail(null);
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [advanceId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function openEdit() {
    if (!detail) {
      return;
    }
    setEditAmount(String(detail.amount));
    setEditDate(detail.requested_date);
    setReason(detail.reason);
    setMode("edit");
  }

  async function act(kind: Action) {
    if (advanceId === null) {
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
        await submitSalaryAdvance(advanceId);
      } else if (kind === "cancel") {
        await cancelSalaryAdvance(advanceId, reason.trim() || null);
      } else if (kind === "approve") {
        await approveSalaryAdvance(advanceId, reason.trim() || null);
      } else if (kind === "reject") {
        await rejectSalaryAdvance(advanceId, reason.trim());
      } else if (kind === "disburse") {
        await disburseSalaryAdvance(advanceId, {
          installment_amount: installment
            ? Number(installment)
            : null,
          note: reason.trim() || null,
        });
      } else {
        await settleSalaryAdvance(advanceId, {
          reason: reason.trim() || null,
        });
      }
      setReason("");
      setInstallment("");
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
    if (advanceId === null || !editAmount || !reason.trim() || !editDate) {
      setError(t("error.SALARY_ADVANCE_REASON_REQUIRED"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await updateSalaryAdvance(advanceId, {
        amount: Number(editAmount),
        reason: reason.trim(),
        requested_date: editDate,
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

  if (advanceId === null) {
    return null;
  }

  const statusLabel = detail
    ? (() => {
        const key = `advances.status.${detail.status}`;
        const label = t(key);
        return label === key ? detail.status : label;
      })()
    : "";
  const isDraft = detail?.status === "draft";
  const isSubmitted = detail?.status === "submitted";
  const isApproved = detail?.status === "approved";
  const isDisbursed = detail?.status === "disbursed";

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-4">
        <h3 className="text-sm font-semibold">{t("advances.detail")}</h3>
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
                {t("common.status")}
              </dt>
              <dd className="text-sm">{statusLabel}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("advances.employee")}
              </dt>
              <dd className="text-sm font-mono text-xs">
                #{detail.employee_id}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("advances.amount")}
              </dt>
              <dd className="text-sm">{detail.amount}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("advances.installment")}
              </dt>
              <dd className="text-sm">{detail.installment_amount ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("advances.requestedDate")}
              </dt>
              <dd className="text-sm">{detail.requested_date}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("advances.deductionRule")}
              </dt>
              <dd className="text-sm font-mono text-xs">
                {detail.deduction_rule_id !== null
                  ? `#${detail.deduction_rule_id}`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("advances.submittedAt")}
              </dt>
              <dd className="text-sm">{formatStamp(detail.submitted_at)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("advances.decidedAt")}
              </dt>
              <dd className="text-sm">{formatStamp(detail.decided_at)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("advances.disbursedAt")}
              </dt>
              <dd className="text-sm">{formatStamp(detail.disbursed_at)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-slate-500">
                {t("advances.settledAt")}
              </dt>
              <dd className="text-sm">{formatStamp(detail.settled_at)}</dd>
            </div>
          </dl>

          <p className="text-sm">
            <span className="text-xs font-medium uppercase text-slate-500">
              {t("advances.reason")}:
            </span>{" "}
            {detail.reason}
          </p>

          {detail.decision_reason ? (
            <p className="text-sm">
              <span className="text-xs font-medium uppercase text-slate-500">
                {t("advances.decisionReason")}:
              </span>{" "}
              {detail.decision_reason}
            </p>
          ) : null}
          {detail.settle_note ? (
            <p className="text-sm">
              <span className="text-xs font-medium uppercase text-slate-500">
                {t("advances.settleNote")}:
              </span>{" "}
              {detail.settle_note}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
            {actions.canEdit && isDraft && mode !== "edit" ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={openEdit}
              >
                {t("advances.editAction")}
              </button>
            ) : null}
            {actions.canSubmit && isDraft && mode === null ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={() => void act("submit")}
              >
                {t("advances.submit")}
              </button>
            ) : null}
            {actions.canCancel && (isDraft || isSubmitted) && mode === null ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={() => setMode("cancel")}
              >
                {t("advances.cancel")}
              </button>
            ) : null}
            {actions.canApprove && isSubmitted && mode === null ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={() => setMode("approve")}
              >
                {t("advances.approve")}
              </button>
            ) : null}
            {actions.canReject && isSubmitted && mode === null ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={() => setMode("reject")}
              >
                {t("advances.reject")}
              </button>
            ) : null}
            {actions.canDisburse && isApproved && mode === null ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={() => setMode("disburse")}
              >
                {t("advances.disburse")}
              </button>
            ) : null}
            {actions.canSettle && isDisbursed && mode === null ? (
              <button
                type="button"
                className={ghostButtonClass}
                disabled={busy}
                onClick={() => setMode("settle")}
              >
                {t("advances.settle")}
              </button>
            ) : null}

            {mode === "edit" ? (
              <span className="flex flex-wrap items-center gap-2">
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  className={`${inputClass} w-32`}
                  value={editAmount}
                  onChange={(e) => setEditAmount(e.target.value)}
                  placeholder={t("advances.amount")}
                />
                <input
                  type="date"
                  className={`${inputClass} w-40`}
                  value={editDate}
                  onChange={(e) => setEditDate(e.target.value)}
                />
                <input
                  className={`${inputClass} w-64`}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder={t("advances.reason")}
                />
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

            {mode === "disburse" ? (
              <span className="flex flex-wrap items-center gap-2">
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  className={`${inputClass} w-40`}
                  value={installment}
                  onChange={(e) => setInstallment(e.target.value)}
                  placeholder={t("advances.installmentAmount")}
                />
                <input
                  className={`${inputClass} w-64`}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder={t("advances.note")}
                />
                <button
                  type="button"
                  className={ghostButtonClass}
                  disabled={busy}
                  onClick={() => void act("disburse")}
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

            {mode && mode !== "edit" && mode !== "disburse" ? (
              <span className="flex items-center gap-2">
                <input
                  className={`${inputClass} w-64`}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder={
                    mode === "reject"
                      ? t("approvals.rejectReason")
                      : mode === "cancel"
                        ? t("advances.cancelReason")
                        : mode === "settle"
                          ? t("advances.settleNote")
                          : t("advances.decisionReason")
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
              {t("advances.events")}
            </h4>
            {detail.events.length === 0 ? (
              <p className="text-sm text-slate-500">{t("advances.noEvents")}</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {detail.events.map((event) => {
                  const key = `advances.event.${event.event_type}`;
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
