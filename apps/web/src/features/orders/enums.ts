export enum OrderStatusEnum {
  Received = "received",
  AwaitingPayment = "awaiting_payment",
  Authorized = "authorized",
  Checking = "checking",
  PendingApproval = "pending_approval",
  Captured = "captured",
  Voided = "voided",
  Refunded = "refunded",
  Rejected = "rejected",
  Failed = "failed",
}

export enum OrderFilterTabEnum {
  All = "all",
  NeedsApproval = "needs_approval",
  Paid = "paid",
  Blocked = "blocked",
  InProgress = "in_progress",
}

export enum SecurityCheckStepEnum {
  VerifyAgent = "verify_agent",
  CheckMandate = "check_mandate",
  AuthorizePayment = "authorize_payment",
  ScanInjection = "scan_injection",
  IntentDiff = "intent_diff",
  GraphRisk = "graph_risk",
  Preflight = "preflight",
  Decide = "decide",
  CaptureOrVoid = "capture_or_void",
  BuildProof = "build_proof",
}

export enum SecurityCheckResultEnum {
  Pass = "pass",
  Fail = "fail",
  Flag = "flag",
  Skip = "skip",
  Error = "error",
}

export enum PreflightStatusEnum {
  Pass = "pass",
  Fail = "fail",
  Accepted = "accepted",
  NotSent = "not_sent",
}

export enum ApprovalDecisionEnum {
  Approved = "approved",
  Declined = "declined",
}
