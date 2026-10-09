import { NavLink, Outlet } from "react-router-dom";
import { useSession } from "../App";

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `rounded px-3 py-1.5 text-sm ${
    isActive
      ? "bg-slate-900 text-white"
      : "text-slate-600 hover:bg-slate-100"
  }`;

export default function EssLayoutPage() {
  const { t, can } = useSession();
  return (
    <div className="space-y-6 py-8">
      <h1 className="text-xl font-semibold">{t("ess.heading")}</h1>
      <nav className="flex flex-wrap gap-1 border-b border-slate-200 pb-2">
        <NavLink to="/me" end className={tabClass}>
          {t("ess.tab.profile")}
        </NavLink>
        {can("ess.document.view") ? (
          <NavLink to="/me/documents" className={tabClass}>
            {t("ess.tab.documents")}
          </NavLink>
        ) : null}
        {can("ess.attendance.view") ? (
          <NavLink to="/me/attendance" className={tabClass}>
            {t("ess.tab.attendance")}
          </NavLink>
        ) : null}
        {can("ess.payslip.view") ? (
          <NavLink to="/me/payslips" className={tabClass}>
            {t("ess.tab.payslips")}
          </NavLink>
        ) : null}
        {can("ess.letter.view") ? (
          <NavLink to="/me/letters" className={tabClass}>
            {t("ess.tab.letters")}
          </NavLink>
        ) : null}
      </nav>
      <Outlet />
    </div>
  );
}
