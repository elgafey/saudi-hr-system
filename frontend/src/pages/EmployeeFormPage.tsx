import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useSession } from "../App";
import {
  createEmployee,
  getDepartment,
  getEmployee,
  getJobGrade,
  getJobPosition,
  listBranches,
  listDepartments,
  listEmployees,
  listJobGrades,
  listJobPositions,
  updateEmployee,
  type Branch,
  type EmployeeInput,
  type EmployeePatch,
} from "../api";
import SearchSelect, { type SearchOption } from "../components/SearchSelect";
import {
  errorMessage,
  errorTextClass,
  ghostButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../ui";

interface FormState {
  employee_number: string;
  first_name_ar: string;
  middle_name_ar: string;
  last_name_ar: string;
  first_name_en: string;
  middle_name_en: string;
  last_name_en: string;
  date_of_birth: string;
  gender: string;
  nationality: string;
  personal_email: string;
  work_email: string;
  mobile_phone: string;
  emergency_contact_name: string;
  emergency_contact_phone: string;
  identity_type: string;
  identity_number: string;
  identity_issue_date: string;
  identity_expiry_date: string;
  branch_id: string;
  department_id: string;
  job_position_id: string;
  job_grade_id: string;
  manager_id: string;
  status: string;
  employment_type: string;
  hire_date: string;
  probation_end_date: string;
  termination_date: string;
  notes: string;
}

const emptyForm: FormState = {
  employee_number: "",
  first_name_ar: "",
  middle_name_ar: "",
  last_name_ar: "",
  first_name_en: "",
  middle_name_en: "",
  last_name_en: "",
  date_of_birth: "",
  gender: "",
  nationality: "SA",
  personal_email: "",
  work_email: "",
  mobile_phone: "",
  emergency_contact_name: "",
  emergency_contact_phone: "",
  identity_type: "",
  identity_number: "",
  identity_issue_date: "",
  identity_expiry_date: "",
  branch_id: "",
  department_id: "",
  job_position_id: "",
  job_grade_id: "",
  manager_id: "",
  status: "draft",
  employment_type: "full_time",
  hire_date: "",
  probation_end_date: "",
  termination_date: "",
  notes: "",
};

function nullable(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function optionalId(value: string): number | null {
  return value === "" ? null : Number(value);
}

interface TextFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
  maxLength?: number;
  dir?: "rtl" | "ltr";
}

function TextField({
  label,
  value,
  onChange,
  type,
  required,
  maxLength,
  dir,
}: TextFieldProps) {
  return (
    <label className="block">
      <span className={labelClass}>{label}</span>
      <input
        type={type ?? "text"}
        required={required}
        maxLength={maxLength}
        dir={dir}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      />
    </label>
  );
}

interface SelectFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}

function SelectField({ label, value, onChange, options }: SelectFieldProps) {
  return (
    <label className="block">
      <span className={labelClass}>{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      >
        <option value="">—</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function EmployeeFormPage({ mode }: { mode: "create" | "edit" }) {
  const { t, me } = useSession();
  const navigate = useNavigate();
  const params = useParams<{ id: string }>();
  const companyId = me?.company_ids[0] ?? null;
  const editId = mode === "edit" && params.id ? Number(params.id) : null;

  const [form, setForm] = useState<FormState>(emptyForm);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [loading, setLoading] = useState(mode === "edit");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (key: keyof FormState, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  useEffect(() => {
    if (companyId === null) {
      return;
    }
    let cancelled = false;
    listBranches(companyId)
      .then((rows) => {
        if (!cancelled) {
          setBranches(rows);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  const loadEmployee = useCallback(async () => {
    if (editId === null) {
      return;
    }
    setLoading(true);
    try {
      const employee = await getEmployee(editId);
      setForm({
        employee_number: employee.employee_number,
        first_name_ar: employee.first_name_ar,
        middle_name_ar: employee.middle_name_ar ?? "",
        last_name_ar: employee.last_name_ar,
        first_name_en: employee.first_name_en,
        middle_name_en: employee.middle_name_en ?? "",
        last_name_en: employee.last_name_en,
        date_of_birth: employee.date_of_birth ?? "",
        gender: employee.gender ?? "",
        nationality: employee.nationality,
        personal_email: employee.personal_email ?? "",
        work_email: employee.work_email ?? "",
        mobile_phone: employee.mobile_phone ?? "",
        emergency_contact_name: employee.emergency_contact_name ?? "",
        emergency_contact_phone: employee.emergency_contact_phone ?? "",
        identity_type: employee.identity_type ?? "",
        identity_number: employee.identity_number ?? "",
        identity_issue_date: employee.identity_issue_date ?? "",
        identity_expiry_date: employee.identity_expiry_date ?? "",
        branch_id: employee.branch_id ? String(employee.branch_id) : "",
        department_id: employee.department_id
          ? String(employee.department_id)
          : "",
        job_position_id: employee.job_position_id
          ? String(employee.job_position_id)
          : "",
        job_grade_id: employee.job_grade_id
          ? String(employee.job_grade_id)
          : "",
        manager_id: employee.manager_id ? String(employee.manager_id) : "",
        status: employee.status,
        employment_type: employee.employment_type,
        hire_date: employee.hire_date ?? "",
        probation_end_date: employee.probation_end_date ?? "",
        termination_date: employee.termination_date ?? "",
        notes: employee.notes ?? "",
      });
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t("common.error"), t));
    } finally {
      setLoading(false);
    }
  }, [editId, t]);

  useEffect(() => {
    void loadEmployee();
  }, [loadEmployee]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (companyId === null) {
      return;
    }
    if (form.identity_number.trim() && !form.identity_type) {
      setError(t("employees.identityPairingError"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const common: Omit<EmployeeInput, "company_id"> = {
        first_name_ar: form.first_name_ar.trim(),
        last_name_ar: form.last_name_ar.trim(),
        first_name_en: form.first_name_en.trim(),
        last_name_en: form.last_name_en.trim(),
        nationality: form.nationality.trim() || "SA",
        status: form.status,
        employment_type: form.employment_type,
        middle_name_ar: nullable(form.middle_name_ar),
        middle_name_en: nullable(form.middle_name_en),
        date_of_birth: nullable(form.date_of_birth),
        gender: nullable(form.gender),
        personal_email: nullable(form.personal_email),
        work_email: nullable(form.work_email),
        mobile_phone: nullable(form.mobile_phone),
        emergency_contact_name: nullable(form.emergency_contact_name),
        emergency_contact_phone: nullable(form.emergency_contact_phone),
        identity_type: nullable(form.identity_type),
        identity_number: nullable(form.identity_number),
        identity_issue_date: nullable(form.identity_issue_date),
        identity_expiry_date: nullable(form.identity_expiry_date),
        branch_id: optionalId(form.branch_id),
        department_id: optionalId(form.department_id),
        job_position_id: optionalId(form.job_position_id),
        job_grade_id: optionalId(form.job_grade_id),
        manager_id: optionalId(form.manager_id),
        hire_date: nullable(form.hire_date),
        probation_end_date: nullable(form.probation_end_date),
        termination_date: nullable(form.termination_date),
        notes: nullable(form.notes),
      };
      if (mode === "create") {
        const numberValue = nullable(form.employee_number);
        const created = await createEmployee({
          ...common,
          company_id: companyId,
          employee_number: numberValue,
        });
        navigate(`/employees/${created.id}`);
      } else if (editId !== null) {
        const patch: EmployeePatch = { ...common };
        const numberValue = nullable(form.employee_number);
        if (numberValue !== null) {
          patch.employee_number = numberValue;
        }
        await updateEmployee(editId, patch);
        navigate(`/employees/${editId}`);
      }
    } catch (err) {
      setError(errorMessage(err, t("common.failed"), t));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="py-16">
        <p className="text-center text-slate-500">{t("common.loading")}</p>
      </div>
    );
  }

  const sectionTitle = "sm:col-span-full mt-2 text-sm font-semibold";

  function loadDepartments(search: string): Promise<SearchOption[]> {
    if (companyId === null) {
      return Promise.resolve([]);
    }
    return listDepartments({
      company_id: companyId,
      search,
      page: 1,
      page_size: 10,
    }).then((page) => page.items.map((row) => ({ id: row.id, label: row.name_en })));
  }

  function loadPositions(search: string): Promise<SearchOption[]> {
    if (companyId === null) {
      return Promise.resolve([]);
    }
    return listJobPositions({
      company_id: companyId,
      search,
      page: 1,
      page_size: 10,
    }).then((page) => page.items.map((row) => ({ id: row.id, label: row.name_en })));
  }

  function loadGrades(search: string): Promise<SearchOption[]> {
    if (companyId === null) {
      return Promise.resolve([]);
    }
    return listJobGrades({
      company_id: companyId,
      search,
      page: 1,
      page_size: 10,
    }).then((page) =>
      page.items.map((row) => ({
        id: row.id,
        label: `L${row.level} — ${row.name_en}`,
      })),
    );
  }

  function loadManagers(search: string): Promise<SearchOption[]> {
    if (companyId === null) {
      return Promise.resolve([]);
    }
    return listEmployees({
      company_id: companyId,
      search,
      page: 1,
      page_size: 10,
    }).then((page) =>
      page.items
        .filter((row) => row.id !== editId)
        .map((row) => ({
          id: row.id,
          label: `${row.employee_number} — ${row.first_name_en} ${row.last_name_en}`,
        })),
    );
  }

  return (
    <div className="space-y-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">
          {mode === "create" ? t("employees.new") : t("employees.edit")}
        </h1>
        <Link
          to="/employees"
          className="text-sm text-blue-600 hover:underline"
        >
          {t("common.back")}
        </Link>
      </div>

      {error ? <p className={errorTextClass}>{error}</p> : null}

      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
        <div className={sectionTitle}>{t("employees.sectionNames")}</div>
        <TextField
          label={t("employees.firstNameAr")}
          value={form.first_name_ar}
          onChange={(value) => set("first_name_ar", value)}
          required
          maxLength={100}
          dir="rtl"
        />
        <TextField
          label={t("employees.middleNameAr")}
          value={form.middle_name_ar}
          onChange={(value) => set("middle_name_ar", value)}
          maxLength={100}
          dir="rtl"
        />
        <TextField
          label={t("employees.lastNameAr")}
          value={form.last_name_ar}
          onChange={(value) => set("last_name_ar", value)}
          required
          maxLength={100}
          dir="rtl"
        />
        <TextField
          label={t("employees.firstNameEn")}
          value={form.first_name_en}
          onChange={(value) => set("first_name_en", value)}
          required
          maxLength={100}
        />
        <TextField
          label={t("employees.middleNameEn")}
          value={form.middle_name_en}
          onChange={(value) => set("middle_name_en", value)}
          maxLength={100}
        />
        <TextField
          label={t("employees.lastNameEn")}
          value={form.last_name_en}
          onChange={(value) => set("last_name_en", value)}
          required
          maxLength={100}
        />

        <div className={sectionTitle}>{t("employees.sectionIdentity")}</div>
        <TextField
          label={t("employees.number")}
          value={form.employee_number}
          onChange={(value) => set("employee_number", value)}
          maxLength={50}
        />
        <SelectField
          label={t("employees.identityType")}
          value={form.identity_type}
          onChange={(value) => set("identity_type", value)}
          options={[
            { value: "national_id", label: t("identity.national_id") },
            { value: "iqama", label: t("identity.iqama") },
            { value: "passport", label: t("identity.passport") },
          ]}
        />
        <TextField
          label={t("employees.identityNumber")}
          value={form.identity_number}
          onChange={(value) => set("identity_number", value)}
          maxLength={50}
        />
        <TextField
          label={t("employees.issueDate")}
          value={form.identity_issue_date}
          onChange={(value) => set("identity_issue_date", value)}
          type="date"
        />
        <TextField
          label={t("employees.expiryDate")}
          value={form.identity_expiry_date}
          onChange={(value) => set("identity_expiry_date", value)}
          type="date"
        />
        <TextField
          label={t("employees.dob")}
          value={form.date_of_birth}
          onChange={(value) => set("date_of_birth", value)}
          type="date"
        />
        <SelectField
          label={t("employees.gender")}
          value={form.gender}
          onChange={(value) => set("gender", value)}
          options={[
            { value: "male", label: t("gender.male") },
            { value: "female", label: t("gender.female") },
          ]}
        />
        <TextField
          label={t("employees.nationality")}
          value={form.nationality}
          onChange={(value) => set("nationality", value)}
          maxLength={2}
        />

        <div className={sectionTitle}>{t("employees.sectionContact")}</div>
        <TextField
          label={t("employees.personalEmail")}
          value={form.personal_email}
          onChange={(value) => set("personal_email", value)}
          type="email"
          maxLength={255}
        />
        <TextField
          label={t("employees.workEmail")}
          value={form.work_email}
          onChange={(value) => set("work_email", value)}
          type="email"
          maxLength={255}
        />
        <TextField
          label={t("employees.mobile")}
          value={form.mobile_phone}
          onChange={(value) => set("mobile_phone", value)}
          maxLength={32}
        />
        <TextField
          label={t("employees.emergencyName")}
          value={form.emergency_contact_name}
          onChange={(value) => set("emergency_contact_name", value)}
          maxLength={255}
        />
        <TextField
          label={t("employees.emergencyPhone")}
          value={form.emergency_contact_phone}
          onChange={(value) => set("emergency_contact_phone", value)}
          maxLength={32}
        />

        <div className={sectionTitle}>{t("employees.sectionOrg")}</div>
        <SelectField
          label={t("employees.branch")}
          value={form.branch_id}
          onChange={(value) => set("branch_id", value)}
          options={branches.map((row) => ({
            value: String(row.id),
            label: `${row.code} — ${row.name}`,
          }))}
        />
        <SearchSelect
          label={t("employees.department")}
          value={form.department_id}
          onChange={(value) => set("department_id", value)}
          load={loadDepartments}
          resolve={(id) => getDepartment(id).then((row) => row.name_en)}
        />
        <SearchSelect
          label={t("employees.position")}
          value={form.job_position_id}
          onChange={(value) => set("job_position_id", value)}
          load={loadPositions}
          resolve={(id) => getJobPosition(id).then((row) => row.name_en)}
        />
        <SearchSelect
          label={t("employees.grade")}
          value={form.job_grade_id}
          onChange={(value) => set("job_grade_id", value)}
          load={loadGrades}
          resolve={(id) =>
            getJobGrade(id).then((row) => `L${row.level} — ${row.name_en}`)
          }
        />
        <SearchSelect
          label={t("employees.manager")}
          value={form.manager_id}
          onChange={(value) => set("manager_id", value)}
          load={loadManagers}
          resolve={(id) =>
            getEmployee(id).then(
              (row) =>
                `${row.employee_number} — ${row.first_name_en} ${row.last_name_en}`,
            )
          }
        />

        <div className={sectionTitle}>{t("employees.sectionEmployment")}</div>
        <SelectField
          label={t("common.status")}
          value={form.status}
          onChange={(value) => set("status", value)}
          options={[
            { value: "draft", label: t("status.draft") },
            { value: "active", label: t("status.active") },
            { value: "suspended", label: t("status.suspended") },
            { value: "terminated", label: t("status.terminated") },
          ]}
        />
        <SelectField
          label={t("employees.employmentType")}
          value={form.employment_type}
          onChange={(value) => set("employment_type", value)}
          options={[
            { value: "full_time", label: t("empType.full_time") },
            { value: "part_time", label: t("empType.part_time") },
            { value: "temporary", label: t("empType.temporary") },
            { value: "intern", label: t("empType.intern") },
          ]}
        />
        <TextField
          label={t("employees.hireDate")}
          value={form.hire_date}
          onChange={(value) => set("hire_date", value)}
          type="date"
        />
        <TextField
          label={t("employees.probationEnd")}
          value={form.probation_end_date}
          onChange={(value) => set("probation_end_date", value)}
          type="date"
        />
        <TextField
          label={t("employees.terminationDate")}
          value={form.termination_date}
          onChange={(value) => set("termination_date", value)}
          type="date"
        />

        <div className={sectionTitle}>{t("employees.sectionNotes")}</div>
        <label className="block sm:col-span-full">
          <span className={labelClass}>{t("employees.notes")}</span>
          <textarea
            maxLength={2000}
            rows={3}
            value={form.notes}
            onChange={(event) => set("notes", event.target.value)}
            className={inputClass}
          />
        </label>
        <p className="text-xs text-slate-500 sm:col-span-full">
          {t("employees.autoNumberHint")}
        </p>

        <div className="flex gap-2 sm:col-span-full">
          <button
            type="submit"
            disabled={saving}
            className={primaryButtonClass}
          >
            {saving ? t("common.saving") : t("common.save")}
          </button>
          <Link to="/employees" className={ghostButtonClass}>
            {t("common.cancel")}
          </Link>
        </div>
      </form>
    </div>
  );
}
