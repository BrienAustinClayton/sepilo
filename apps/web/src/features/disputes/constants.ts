import {
  DisputeAiSourceEnum,
  DisputePriorityEnum,
  DisputeReasonEnum,
  DisputeStatusEnum,
  DisputeSuggestionEnum,
} from "./enums";

export const TONE = {
  success: "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20",
  danger: "bg-rose-500/10 text-rose-400 border border-rose-500/20",
  warning: "bg-amber-500/10 text-amber-400 border border-amber-500/20",
  brand: "bg-blue-500/10 text-blue-400 border border-blue-500/20",
  neutral: "bg-neutral-500/10 text-neutral-400 border border-neutral-500/20",
};

export const REASON_LABELS: Record<DisputeReasonEnum, string> = {
  [DisputeReasonEnum.NotReceived]: "Never arrived",
  [DisputeReasonEnum.NotAsDescribed]: "Not as described",
  [DisputeReasonEnum.Unauthorized]: "I didn't authorize this",
  [DisputeReasonEnum.Duplicate]: "Charged twice",
  [DisputeReasonEnum.Other]: "Something else",
};

export const REASON_OPTIONS = Object.values(DisputeReasonEnum).map((reason) => ({
  value: reason,
  label: REASON_LABELS[reason],
}));

export const STATUS_TAG: Record<DisputeStatusEnum, { label: string; style: string }> = {
  [DisputeStatusEnum.Open]: { label: "Open", style: TONE.warning },
  [DisputeStatusEnum.Refunded]: { label: "Refunded", style: TONE.success },
  [DisputeStatusEnum.Rejected]: { label: "Rejected", style: TONE.neutral },
  [DisputeStatusEnum.Failed]: { label: "Failed", style: TONE.danger },
};

export const PRIORITY_STYLES: Record<DisputePriorityEnum, string> = {
  [DisputePriorityEnum.Urgent]: TONE.danger,
  [DisputePriorityEnum.High]: TONE.warning,
  [DisputePriorityEnum.Normal]: TONE.brand,
  [DisputePriorityEnum.Low]: TONE.neutral,
};

export const SUGGESTION_TAG: Record<DisputeSuggestionEnum, { label: string; style: string }> = {
  [DisputeSuggestionEnum.Refund]: { label: "Suggest: refund", style: TONE.success },
  [DisputeSuggestionEnum.Reject]: { label: "Suggest: reject", style: TONE.neutral },
  [DisputeSuggestionEnum.Investigate]: { label: "Suggest: investigate", style: TONE.warning },
};

export const AI_SOURCE_TAG: Record<DisputeAiSourceEnum, string> = {
  [DisputeAiSourceEnum.Jev]: "AI: Jev",
  [DisputeAiSourceEnum.Rules]: "Rules only",
};

export const EMPTY_TEXT = {
  mine: "When you raise a dispute on a paid order, it shows up here with its status and our reply.",
  queue: "Nothing is waiting for a decision. New disputes appear here, most urgent first.",
  decided: "No disputes have been decided yet.",
};
