"use client";

import React, { useState } from "react";
import { Check, X } from "lucide-react";
import { OrderApprovalActionsProps } from "../../componentTypes";
import { Button } from "@/shared/presentation/components/Button";
import { Input } from "@/shared/presentation/components/Input";
import { ButtonVariantEnum } from "@/shared/enums";

const HIGH_VALUE_APPROVAL = 100;

export function OrderApprovalActions({
  timeoutAt,
  total,
  onApprove,
  onDecline,
  isProcessing,
}: OrderApprovalActionsProps) {
  const [typedTotal, setTypedTotal] = useState<string>("");
  const amount = Number(total);
  const needsTypedTotal = amount >= HIGH_VALUE_APPROVAL;
  const typedMatches = Number(typedTotal.replace(/[$,\s]/g, "")) === amount;
  const canApprove = !needsTypedTotal || typedMatches;

  return (
    <div className="max-sm:fixed max-sm:inset-x-0 max-sm:bottom-0 max-sm:z-30 max-sm:border-t max-sm:border-line max-sm:bg-canvas max-sm:p-3 max-sm:pb-[calc(0.75rem+env(safe-area-inset-bottom))] sm:mt-5 sm:border-t sm:border-amber-500/20 sm:pt-4">
      <div className="flex flex-col sm:flex-row sm:items-center gap-2">
        {needsTypedTotal && (
          <Input
            value={typedTotal}
            onChange={setTypedTotal}
            maxLength={20}
            placeholder={`Type ${amount.toFixed(2)} to approve`}
            className="h-10 w-full sm:w-52"
          />
        )}
        <div className="flex items-center gap-2">
          <Button
            variant={ButtonVariantEnum.Primary}
            isLoading={isProcessing}
            disabled={!canApprove}
            onClick={() => onApprove(needsTypedTotal ? typedTotal : undefined)}
            className="flex-1 sm:flex-none"
          >
            <Check className="w-4 h-4" strokeWidth={2} />
            Approve order
          </Button>
          <Button
            variant={ButtonVariantEnum.Danger}
            disabled={isProcessing}
            onClick={onDecline}
            className="flex-1 sm:flex-none"
          >
            <X className="w-4 h-4" strokeWidth={2} />
            Decline
          </Button>
        </div>
      </div>
      <p className="mt-2 hidden sm:block text-xs text-fg-muted">
        Funds are held in PayPal but not charged until you approve.
        {timeoutAt !== null && " Approval expires in 30 minutes."}
      </p>
    </div>
  );
}
