import { useSession } from "../App";

export default function DashboardPage() {
  const { me, t, signOut } = useSession();

  if (!me) {
    return null;
  }

  return (
    <div className="space-y-6 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t("dashboard.heading")}</h1>
        <button
          type="button"
          onClick={() => void signOut()}
          className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100"
        >
          {t("dashboard.logout")}
        </button>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <p className="text-sm text-slate-500">{t("dashboard.signedInAs")}</p>
        <p className="font-medium">{me.user.email}</p>
        {me.user.is_platform_admin ? (
          <p className="mt-1 text-xs font-medium text-blue-600">
            Platform Administrator
          </p>
        ) : null}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="mb-2 text-sm font-semibold">
          {t("dashboard.companies")}
        </h2>
        {me.company_ids.length === 0 ? (
          <p className="text-sm text-slate-500">—</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {me.company_ids.map((id) => (
              <li
                key={id}
                className="rounded bg-slate-100 px-2 py-1 text-sm"
              >
                #{id}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="mb-2 text-sm font-semibold">
          {t("dashboard.permissions")}
        </h2>
        <ul className="flex flex-wrap gap-2">
          {me.permissions.map((code) => (
            <li
              key={code}
              className="rounded bg-slate-100 px-2 py-1 font-mono text-xs"
            >
              {code}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
