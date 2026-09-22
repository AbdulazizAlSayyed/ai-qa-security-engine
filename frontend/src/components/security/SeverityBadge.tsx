import { SEVERITY_CLASS, SEVERITY_LABEL } from "@/lib/security";
import type { Severity } from "@/types/security";

interface SeverityBadgeProps {
  severity: Severity;
  count?: number;
}

export default function SeverityBadge({ severity, count }: SeverityBadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${SEVERITY_CLASS[severity]}`}
    >
      {SEVERITY_LABEL[severity]}
      {count !== undefined ? <span className="font-mono">{count}</span> : null}
    </span>
  );
}
