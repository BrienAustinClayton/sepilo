import { DisputePriorityEnum, DisputeSuggestionEnum, DisputeAiSourceEnum, DisputeStatusEnum } from "./enums";
import { DecideDisputePayload, Dispute, ManagerDispute, ManagerDisputeDetail } from "./types";

export interface DisputeStatusTagProps {
  status: DisputeStatusEnum;
}

export interface DisputePriorityBadgeProps {
  label: DisputePriorityEnum;
  score: number;
}

export interface DisputeSuggestionChipProps {
  suggestion: DisputeSuggestionEnum | null;
}

export interface DisputeAiSourceTagProps {
  source: DisputeAiSourceEnum | null;
}

export interface MyDisputesListProps {
  disputes: Dispute[];
}

export interface ManagerDisputesListProps {
  disputes: ManagerDispute[];
}

export interface RaiseDisputeSectionProps {
  orderId: string;
  isPaid: boolean;
}

export interface DisputeDecisionFormProps {
  total: string;
  isProcessing: boolean;
  onSubmit: (payload: DecideDisputePayload) => Promise<void>;
}

export interface DisputeTriagePanelProps {
  dispute: ManagerDispute;
}

export interface DisputeChecksPanelProps {
  detail: ManagerDisputeDetail;
}

export interface DisputeSummaryProps {
  dispute: Dispute;
}
