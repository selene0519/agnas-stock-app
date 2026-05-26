import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  note,
  tone = "neutral"
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: "neutral" | "good" | "warn" | "danger" | "accent";
}) {
  const color = {
    neutral: "border-line",
    good: "border-good/45",
    warn: "border-warn/45",
    danger: "border-danger/45",
    accent: "border-accent/45"
  }[tone];
  return (
    <div className={`min-h-24 rounded-lg border ${color} bg-card p-4 shadow-soft`}>
      <div className="text-xs font-bold uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-2 text-2xl font-black text-white">{value}</div>
      {note ? <div className="mt-1 text-xs leading-5 text-muted">{note}</div> : null}
    </div>
  );
}

export function Section({
  title,
  children,
  right
}: {
  title: string;
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <section className="mt-5">
      <div className="mb-3 flex items-center justify-between border-b border-line pb-2">
        <h2 className="text-base font-black text-white">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

export function EmptyReason({ text }: { text: string }) {
  return <div className="rounded-lg border border-line bg-panel p-5 text-sm text-muted">{text}</div>;
}
