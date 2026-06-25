import type { BadgeTone } from "./Badge";

export function MetricCard({
  label,
  value,
  emphasis,
  tone,
  className = "",
}: {
  label: string;
  value: React.ReactNode;
  emphasis?: "primary";
  tone?: BadgeTone;
  className?: string;
}) {
  return (
    <div
      className={`mone-metric-card ${tone ? `mone-tone-${tone}` : ""} ${className}`}
      data-emphasis={emphasis}
      data-tone={tone || undefined}
    >
      <div className="mone-metric-label">{label}</div>
      <div className="mone-metric-value">{value}</div>
    </div>
  );
}

export default MetricCard;
