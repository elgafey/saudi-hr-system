import { useCallback, useEffect, useState } from "react";
import { useSession } from "../App";
import {
  getMyLetter,
  listMyLetters,
  type HrLetter,
  type HrLetterListItem,
  type PageMeta,
} from "../api";
import Pagination from "../components/Pagination";
import { errorMessage, errorTextClass } from "../ui";

const pageSize = 20;

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

const VALUE_KEYS = new Set(["employment_type", "employment_status"]);

function formatStamp(value: string | null): string {
  if (!value) {
    return "—";
  }
  return value.slice(0, 16).replace("T", " ");
}

export default function EssLettersPage() {
  const { t, can } = useSession();
  const mayView = can("ess.letter.view");

  const [items, setItems] = useState<HrLetterListItem[]>([]);
  const [meta, setMeta] = useState<PageMeta>({
    page: 1,
    page_size: pageSize,
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [detail, setDetail] = useState<HrLetter | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    if (!mayView) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await listMyLetters({ page, page_size: pageSize });
      setItems(res.items);
      setMeta(res.page);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [page, t, mayView]);

  const loadDetail = useCallback(async () => {
    if (detailId === null) {
      setDetail(null);
      return;
    }
    setDetailLoading(true);
    try {
      setDetail(await getMyLetter(detailId));
      setError(null);
    } catch (err) {
      setDetail(null);
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setDetailLoading(false);
    }
  }, [detailId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  if (!mayView) {
    return <p className={errorTextClass}>{t("error.forbidden")}</p>;
  }

  const statusLabel = (status: string): string => {
    const key = `letters.status.${status}`;
    const label = t(key);
    return label === key ? status : label;
  };

  const typeLabel = (type: string): string => {
    const key = `letters.type.${type}`;
    const label = t(key);
    return label === key ? type : label;
  };

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

  const contentFields = detail
    ? FIELD_ORDER.filter((name) => name in detail.content).concat(
        Object.keys(detail.content).filter((name) => !FIELD_ORDER.includes(name)),
      )
    : [];

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">{t("ess.letters.heading")}</h2>

      {error ? <p className={errorTextClass}>{error}</p> : null}

      {loading ? (
        <p className="text-sm text-slate-500">{t("common.loading")}</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-500">{t("ess.letters.empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-4">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-2 pr-3">{t("letters.reference")}</th>
                <th className="py-2 pr-3">{t("letters.type")}</th>
                <th className="py-2 pr-3">{t("common.status")}</th>
                <th className="py-2 pr-3">{t("letters.issuedAt")}</th>
                <th className="py-2 pr-3 text-right">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.id} className="border-b border-slate-100">
                  <td className="py-2 pr-3 font-mono text-xs">
                    {row.reference}
                  </td>
                  <td className="py-2 pr-3">{typeLabel(row.letter_type)}</td>
                  <td className="py-2 pr-3">{statusLabel(row.status)}</td>
                  <td className="py-2 pr-3">
                    {row.issued_at
                      ? row.issued_at.slice(0, 16).replace("T", " ")
                      : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <button
                      type="button"
                      className="text-blue-600 hover:underline"
                      onClick={() => setDetailId(row.id)}
                    >
                      {t("letters.detail")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination meta={meta} onPage={setPage} />
        </div>
      )}

      {detailId !== null ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between gap-4">
            <h3 className="text-sm font-semibold">{t("letters.detail")}</h3>
            <button
              type="button"
              className="text-sm text-slate-500 hover:underline"
              onClick={() => {
                setDetailId(null);
                setDetail(null);
              }}
            >
              {t("common.close")}
            </button>
          </div>

          {detailLoading ? (
            <p className="text-sm text-slate-500">{t("common.loading")}</p>
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
                  <dd className="text-sm">{statusLabel(detail.status)}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase text-slate-500">
                    {t("letters.type")}
                  </dt>
                  <dd className="text-sm">{typeLabel(detail.letter_type)}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase text-slate-500">
                    {t("letters.language")}
                  </dt>
                  <dd className="text-sm">{detail.language.toUpperCase()}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase text-slate-500">
                    {t("letters.issuedAt")}
                  </dt>
                  <dd className="text-sm">{formatStamp(detail.issued_at)}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase text-slate-500">
                    {t("letters.purpose")}
                  </dt>
                  <dd className="text-sm">{detail.purpose ?? "—"}</dd>
                </div>
              </dl>

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

              <div>
                <h4 className="mb-2 text-xs font-medium uppercase text-slate-500">
                  {t("letters.events")}
                </h4>
                {detail.events.length === 0 ? (
                  <p className="text-sm text-slate-500">
                    {t("letters.noEvents")}
                  </p>
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
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
