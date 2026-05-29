import type { ReactNode } from "react";

type Tone = "neutral" | "accent" | "good" | "warn";

function toneClass(tone?: Tone) {
  if (tone === "good") return "border-green-500/40 bg-green-500/10 text-green-300";
  if (tone === "warn") return "border-amber-500/40 bg-amber-500/10 text-amber-300";
  if (tone === "accent") return "border-sky-500/40 bg-sky-500/10 text-sky-300";
  return "border-slate-800 bg-slate-900/70 text-slate-100";
}

export function Section({
  title,
  right,
  children,
}: {
  title?: ReactNode;
  right?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="mb-5 rounded-2xl border border-slate-800 bg-slate-950/70 p-5">
      {(title || right) ? (
        <div className="mb-4 flex items-start justify-between gap-4">
          {title ? <h2 className="text-xl font-black text-white">{title}</h2> : <div />}
          {right ? <div className="shrink-0">{right}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function StatCard({
  label,
  value,
  note,
  tone = "neutral",
  children,
}: {
  label?: ReactNode;
  value?: ReactNode;
  note?: ReactNode;
  tone?: Tone;
  children?: ReactNode;
}) {
  return (
    <div className={`rounded-2xl border p-4 ${toneClass(tone)}`}>
      {label ? <div className="text-xs font-bold opacity-80">{label}</div> : null}
      {value !== undefined ? <div className="mt-2 text-2xl font-black">{value}</div> : null}
      {note ? <div className="mt-2 text-xs leading-5 opacity-80">{note}</div> : null}
      {children ? <div className="mt-3">{children}</div> : null}
    </div>
  );
}

export function EmptyReason({
  text,
  title = "표시할 데이터가 없습니다.",
  message,
  children,
}: {
  text?: ReactNode;
  title?: ReactNode;
  message?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5 text-sm leading-6 text-slate-400">
      <div className="font-black text-slate-100">{text ?? title}</div>
      {message ? <div className="mt-2">{message}</div> : null}
      {children ? <div className="mt-3">{children}</div> : null}
    </div>
  );
}
