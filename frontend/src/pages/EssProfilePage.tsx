import { useEffect, useState } from "react";
import { useSession } from "../App";
import { myProfile, type EssProfile } from "../api";
import { errorMessage, errorTextClass } from "../ui";

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase text-slate-500">
        {label}
      </dt>
      <dd className="text-sm text-slate-800">{value ?? "—"}</dd>
    </div>
  );
}

export default function EssProfilePage() {
  const { t, locale } = useSession();
  const [profile, setProfile] = useState<EssProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    myProfile()
      .then((data) => {
        if (!cancelled) {
          setProfile(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorMessage(err, t("common.error"), t));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  if (loading) {
    return <p className="text-sm text-slate-500">{t("common.loading")}</p>;
  }
  if (error || !profile) {
    return <p className={errorTextClass}>{error ?? t("common.error")}</p>;
  }

  const localName = (item: {
    name_ar: string;
    name_en: string;
  } | null): string | null =>
    item ? (locale === "ar" ? item.name_ar : item.name_en) : null;

  const statusKey = `status.${profile.status}`;
  const statusLabel = t(statusKey) === statusKey ? profile.status : t(statusKey);
  const typeKey = `empType.${profile.employment_type}`;
  const typeLabel = t(typeKey) === typeKey ? profile.employment_type : t(typeKey);
  const genderLabel = profile.gender
    ? t(`gender.${profile.gender}`)
    : null;

  return (
    <section className="space-y-6">
      <div>
        <h2 className="mb-1 text-sm font-semibold">
          {profile.first_name_en} {profile.last_name_en}
        </h2>
        <p className="font-mono text-xs text-slate-500">
          {profile.employee_number} · {statusLabel}
        </p>
      </div>

      <dl className="grid gap-4 sm:grid-cols-3">
        <Field label={t("ess.employeeNumber")} value={profile.employee_number} />
        <Field label={t("ess.company")} value={localName(profile.company)} />
        <Field label={t("ess.department")} value={localName(profile.department)} />
        <Field label={t("ess.branch")} value={localName(profile.branch)} />
        <Field label={t("ess.position")} value={localName(profile.job_position)} />
        <Field label={t("ess.manager")} value={localName(profile.manager)} />
        <Field label={t("ess.hireDate")} value={profile.hire_date} />
        <Field label={t("ess.employmentType")} value={typeLabel} />
        <Field label={t("ess.nationality")} value={profile.nationality} />
        <Field label={t("employees.gender")} value={genderLabel} />
        <Field label={t("ess.workEmail")} value={profile.work_email} />
        <Field label={t("ess.mobile")} value={profile.mobile_phone} />
      </dl>

      {profile.contract ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold">{t("ess.contract")}</h3>
          <dl className="grid gap-4 sm:grid-cols-4">
            <Field
              label={t("ess.contractNumber")}
              value={profile.contract.contract_number}
            />
            <Field
              label={t("contracts.type")}
              value={t(`contractType.${profile.contract.contract_type}`)}
            />
            <Field label={t("contracts.start")} value={profile.contract.start_date} />
            <Field label={t("contracts.end")} value={profile.contract.end_date} />
            <Field
              label={t("ess.basicSalary")}
              value={
                profile.contract.basic_salary
                  ? `${profile.contract.basic_salary} ${profile.contract.currency}`
                  : null
              }
            />
          </dl>
        </div>
      ) : null}
    </section>
  );
}
