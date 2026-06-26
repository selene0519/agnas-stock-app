export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  className = "",
}: {
  options: { value: T; label: string; count?: number }[];
  value: T;
  onChange: (next: T) => void;
  className?: string;
}) {
  return (
    <div className={`mone-segmented ${className}`} role="tablist">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="tab"
          aria-selected={value === opt.value}
          data-active={value === opt.value ? "true" : "false"}
          onClick={() => onChange(opt.value)}
          className="mone-segmented-item"
        >
          {opt.label}
          {opt.count != null && opt.count > 0 && (
            <span className="opacity-70">{opt.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

export default SegmentedControl;
