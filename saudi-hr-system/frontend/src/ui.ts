import { ApiError } from "./api";

export const inputClass =
  "w-full rounded border border-slate-300 px-2 py-1.5 text-sm";
export const labelClass = "block text-sm font-medium text-slate-700";
export const primaryButtonClass =
  "rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700 disabled:opacity-50";
export const ghostButtonClass =
  "rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50";
export const dangerButtonClass =
  "rounded border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50";
export const errorTextClass = "text-sm text-red-600";

export function errorMessage(
  error: unknown,
  fallback: string,
  t?: (key: string) => string,
): string {
  if (error instanceof ApiError) {
    if (t && error.code) {
      const key = `error.${error.code}`;
      const translated = t(key);
      if (translated !== key) {
        return translated;
      }
    }
    return error.message;
  }
  return fallback;
}
