"use client";

import React from "react";
import { Check, TriangleAlert } from "lucide-react";
import { ChecksSummary } from "../../types";

export function ChecksBadge({ checks }: { checks: ChecksSummary | null | undefined }) {
  if (!checks) {
    return (
      <span className="text-sm text-fg-dim" title="The 32 security checks did not run for this order" aria-label="No security checks ran">
        {"—"}
      </span>
    );
  }

  const isClean = checks.passed >= checks.total;
  const tooltip = isClean
    ? `All ${checks.total} security checks passed`
    : checks.failed.length > 0
      ? `Failed: ${checks.failed.join("; ")}`
      : `${checks.total - checks.passed} security checks did not pass`;

  return (
    <span
      title={tooltip}
      aria-label={`${checks.passed} of ${checks.total} security checks passed. ${tooltip}`}
      className={`inline-flex items-center gap-1 text-xs font-medium tabular-nums ${isClean ? "text-emerald-400" : "text-amber-400"}`}
    >
      {isClean ? (
        <Check className="w-3.5 h-3.5" strokeWidth={2.5} aria-hidden="true" />
      ) : (
        <TriangleAlert className="w-3.5 h-3.5" strokeWidth={2} aria-hidden="true" />
      )}
      {checks.passed}/{checks.total}
    </span>
  );
}
