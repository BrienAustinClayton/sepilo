export enum DisputeReasonEnum {
  NotReceived = "not_received",
  NotAsDescribed = "not_as_described",
  Unauthorized = "unauthorized",
  Duplicate = "duplicate",
  Other = "other",
}

export enum DisputeStatusEnum {
  Open = "open",
  Refunded = "refunded",
  Rejected = "rejected",
  Failed = "failed",
}

export enum DisputePriorityEnum {
  Urgent = "urgent",
  High = "high",
  Normal = "normal",
  Low = "low",
}

export enum DisputeSuggestionEnum {
  Refund = "refund",
  Reject = "reject",
  Investigate = "investigate",
}

export enum DisputeAiSourceEnum {
  Jev = "jev",
  Rules = "rules",
}

export enum DisputeDecisionEnum {
  Refund = "refund",
  Reject = "reject",
}

export enum DisputeTabEnum {
  Queue = "queue",
  Decided = "decided",
  Mine = "mine",
}

export enum DisputeRoleEnum {
  User = "user",
  Manager = "dispute_manager",
}
