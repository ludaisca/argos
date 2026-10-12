export function QuotaGauge({
  label,
  used,
  limit,
  accent = "var(--chart-1)",
}: {
  label: string;
  used: number;
  limit: number;
  accent?: string;
}) {
  const pct = limit > 0 ? Math.min(1, used / limit) : 0;
  const radius = 30;
  const circumference = 2 * Math.PI * radius;
  const dash = circumference * pct;
  return (
    <div className="flex items-center gap-3">
      <svg width="76" height="76" viewBox="0 0 76 76" className="shrink-0">
        <circle
          cx="38"
          cy="38"
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeWidth="7"
        />
        <circle
          cx="38"
          cy="38"
          r={radius}
          fill="none"
          stroke={accent}
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference - dash}`}
          transform="rotate(-90 38 38)"
        />
        <text
          x="38"
          y="42"
          textAnchor="middle"
          className="fill-foreground text-[13px] font-semibold"
        >
          {Math.round(pct * 100)}%
        </text>
      </svg>
      <div className="min-w-0">
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-muted-foreground">
          {used}/{limit} hoy · quedan {Math.max(0, limit - used)}
        </div>
      </div>
    </div>
  );
}
