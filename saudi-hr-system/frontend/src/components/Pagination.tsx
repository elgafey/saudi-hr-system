import { useSession } from "../App";
import type { PageMeta } from "../api";

interface Props {
  meta: PageMeta;
  onPage: (page: number) => void;
}

export default function Pagination({ meta, onPage }: Props) {
  const { t } = useSession();
  const totalPages = Math.max(1, Math.ceil(meta.total / meta.page_size));

  if (meta.total === 0) {
    return null;
  }

  return (
    <div className="flex items-center justify-between gap-4 border-t border-slate-100 pt-3 text-sm text-slate-600">
      <span>
        {meta.total} {t("common.results")}
      </span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={meta.page <= 1}
          onClick={() => onPage(meta.page - 1)}
          className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40 enabled:hover:bg-slate-100"
        >
          {t("pagination.prev")}
        </button>
        <span>
          {t("pagination.pageOf")} {meta.page} / {totalPages}
        </span>
        <button
          type="button"
          disabled={meta.page >= totalPages}
          onClick={() => onPage(meta.page + 1)}
          className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40 enabled:hover:bg-slate-100"
        >
          {t("pagination.next")}
        </button>
      </div>
    </div>
  );
}
