export type BadgeTone = "safe" | "warning" | "danger" | "info" | "neutral";

export function Badge({
  tone = "neutral",
  children,
  className = "",
}: {
  tone?: BadgeTone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span className={`mone-badge mone-tone-${tone} ${className}`}>
      {children}
    </span>
  );
}

export default Badge;
