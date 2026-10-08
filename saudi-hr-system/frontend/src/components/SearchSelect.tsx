import { useEffect, useRef, useState } from "react";
import { inputClass, labelClass } from "../ui";

export interface SearchOption {
  id: number;
  label: string;
}

interface SearchSelectProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  load: (search: string) => Promise<SearchOption[]>;
  resolve?: (id: number) => Promise<string>;
  placeholder?: string;
}

export default function SearchSelect({
  label,
  value,
  onChange,
  load,
  resolve,
  placeholder,
}: SearchSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<SearchOption[]>([]);
  const [selectedLabel, setSelectedLabel] = useState("");
  const timer = useRef<number | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;
  const resolveRef = useRef(resolve);
  resolveRef.current = resolve;

  useEffect(() => {
    if (value === "") {
      setSelectedLabel("");
      return;
    }
    const resolveFn = resolveRef.current;
    if (!resolveFn) {
      return;
    }
    let cancelled = false;
    resolveFn(Number(value))
      .then((text) => {
        if (!cancelled) {
          setSelectedLabel(text);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSelectedLabel(`#${value}`);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [value]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onDocMouseDown(event: MouseEvent) {
      if (
        rootRef.current &&
        !rootRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  useEffect(
    () => () => {
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
      }
    },
    [],
  );

  function runSearch(text: string) {
    setQuery(text);
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
    }
    timer.current = window.setTimeout(() => {
      loadRef
        .current(text)
        .then((rows) => setOptions(rows))
        .catch(() => setOptions([]));
    }, 300);
  }

  function select(option: SearchOption) {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
    }
    onChange(String(option.id));
    setSelectedLabel(option.label);
    setOpen(false);
    setQuery("");
    setOptions([]);
  }

  function clear() {
    onChange("");
    setSelectedLabel("");
    setQuery("");
    setOptions([]);
  }

  return (
    <div className="relative block" ref={rootRef}>
      <span className={labelClass}>{label}</span>
      <div className="mt-1 flex gap-1">
        <input
          className={inputClass}
          value={open ? query : selectedLabel}
          placeholder={placeholder ?? ""}
          onFocus={() => {
            setOpen(true);
            runSearch("");
          }}
          onChange={(event) => runSearch(event.target.value)}
        />
        {value !== "" && !open ? (
          <button
            type="button"
            onClick={clear}
            className={inputClass}
            style={{ width: "auto" }}
            aria-label={label}
          >
            ×
          </button>
        ) : null}
      </div>
      {open && options.length > 0 ? (
        <ul className="absolute z-20 mt-1 max-h-48 w-full overflow-auto rounded border border-slate-200 bg-white shadow-lg">
          {options.map((option) => (
            <li key={option.id}>
              <button
                type="button"
                className="block w-full px-2 py-1.5 text-left text-sm hover:bg-slate-100"
                onMouseDown={(event) => {
                  event.preventDefault();
                  select(option);
                }}
              >
                {option.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
