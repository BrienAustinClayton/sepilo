"use client";

import React, { useState } from "react";
import { Check, X } from "lucide-react";
import { Button } from "@/shared/presentation/components/Button";
import { Input } from "@/shared/presentation/components/Input";
import { Textarea } from "@/shared/presentation/components/Textarea";
import { ButtonVariantEnum } from "@/shared/enums";
import { DisputeDecisionFormProps } from "../../componentTypes";
import { DisputeDecisionEnum } from "../../enums";
import { NOTE_MAX, buildDecisionSchema } from "../../schemas";

const CHOICES: Array<{ value: DisputeDecisionEnum; label: string }> = [
  { value: DisputeDecisionEnum.Refund, label: "Refund" },
  { value: DisputeDecisionEnum.Reject, label: "Reject" },
];

export function DisputeDecisionForm({ total, isProcessing, onSubmit }: DisputeDecisionFormProps) {
  const [decision, setDecision] = useState<DisputeDecisionEnum>(DisputeDecisionEnum.Refund);
  const [note, setNote] = useState("");
  const [confirmTotal, setConfirmTotal] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const isRefund = decision === DisputeDecisionEnum.Refund;
  const amount = Number(total).toFixed(2);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const parsed = buildDecisionSchema(total).safeParse({ decision, note, confirmTotal });
    if (!parsed.success) {
      setErrorMessage(parsed.error.issues[0]?.message ?? "Check the form and try again");
      return;
    }
    setErrorMessage(null);
    onSubmit({
      decision: parsed.data.decision,
      note: parsed.data.note,
      ...(isRefund ? { confirm_total: parsed.data.confirmTotal } : {}),
    }).catch((error: Error) => setErrorMessage(error.message));
  };

  return (
    <form onSubmit={handleSubmit} className="p-5 space-y-4">
      <div role="radiogroup" aria-label="Decision" className="grid grid-cols-2 gap-2">
        {CHOICES.map((choice) => {
          const isSelected = choice.value === decision;
          return (
            <button
              key={choice.value}
              type="button"
              role="radio"
              aria-checked={isSelected}
              disabled={isProcessing}
              onClick={() => setDecision(choice.value)}
              className={`h-10 rounded-lg border text-[13px] font-medium transition ${
                isSelected
                  ? "border-blue-500/60 bg-blue-500/10 text-fg"
                  : "border-line text-fg-muted hover:text-fg hover:bg-fg/5"
              }`}
            >
              {choice.label}
            </button>
          );
        })}
      </div>

      <label className="block space-y-1.5">
        <span className="block text-[13px] font-medium text-fg-2">Note for the customer</span>
        <Textarea
          value={note}
          onChange={setNote}
          maxLength={NOTE_MAX}
          rows={3}
          placeholder="Explain the decision in a sentence or two"
          disabled={isProcessing}
          className="w-full"
        />
      </label>

      {isRefund && (
        <label className="block space-y-1.5">
          <span className="block text-[13px] font-medium text-fg-2">Type ${amount} to confirm</span>
          <Input
            value={confirmTotal}
            onChange={setConfirmTotal}
            maxLength={20}
            placeholder={amount}
            disabled={isProcessing}
            className="h-10 w-full"
          />
          <span className="block text-xs text-fg-dim">
            The full order total goes back to the customer through PayPal. The amount can&apos;t be changed.
          </span>
        </label>
      )}

      {errorMessage !== null && (
        <p role="alert" className="text-xs text-rose-400">
          {errorMessage}
        </p>
      )}

      <Button
        type="submit"
        variant={isRefund ? ButtonVariantEnum.Primary : ButtonVariantEnum.Danger}
        isLoading={isProcessing}
        disabled={isProcessing}
        className="w-full justify-center"
      >
        {isRefund ? <Check className="w-4 h-4" strokeWidth={2} /> : <X className="w-4 h-4" strokeWidth={2} />}
        {isRefund ? `Refund $${amount}` : "Reject dispute"}
      </Button>
    </form>
  );
}
