import React from "react";
import {
  DisputeAiSourceTagProps,
  DisputePriorityBadgeProps,
  DisputeStatusTagProps,
  DisputeSuggestionChipProps,
} from "../../componentTypes";
import { AI_SOURCE_TAG, PRIORITY_STYLES, STATUS_TAG, SUGGESTION_TAG, TONE } from "../../constants";

const PILL = "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap";

export function DisputeStatusTag({ status }: DisputeStatusTagProps) {
  const { label, style } = STATUS_TAG[status] ?? { label: status, style: TONE.neutral };
  return <span className={`${PILL} ${style}`}>{label}</span>;
}

export function DisputePriorityBadge({ label, score }: DisputePriorityBadgeProps) {
  const style = PRIORITY_STYLES[label] ?? TONE.neutral;
  return (
    <span className={`${PILL} gap-1.5 capitalize ${style}`}>
      {label}
      <span className="tabular-nums opacity-80">{score}</span>
    </span>
  );
}

export function DisputeSuggestionChip({ suggestion }: DisputeSuggestionChipProps) {
  if (suggestion === null) return null;
  const { label, style } = SUGGESTION_TAG[suggestion] ?? { label: suggestion, style: TONE.neutral };
  return <span className={`${PILL} ${style}`}>{label}</span>;
}

export function DisputeAiSourceTag({ source }: DisputeAiSourceTagProps) {
  if (source === null) return null;
  return <span className={`${PILL} ${TONE.neutral}`}>{AI_SOURCE_TAG[source] ?? source}</span>;
}
