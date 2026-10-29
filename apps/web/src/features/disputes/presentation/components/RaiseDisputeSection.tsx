"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ArrowRight, Scale, X } from "lucide-react";
import { Button } from "@/shared/presentation/components/Button";
import { Select } from "@/shared/presentation/components/Select";
import { Textarea } from "@/shared/presentation/components/Textarea";
import { ButtonVariantEnum } from "@/shared/enums";
import { RaiseDisputeSectionProps } from "../../componentTypes";
import { REASON_LABELS, REASON_OPTIONS } from "../../constants";
import { DisputeReasonEnum } from "../../enums";
import { useMyDisputes } from "../../hooks/useMyDisputes";
import { DESCRIPTION_MAX, DESCRIPTION_MIN, createDisputeSchema } from "../../schemas";
import { DisputeStatusTag } from "./DisputeTags";

export function RaiseDisputeSection({ orderId, isPaid }: RaiseDisputeSectionProps) {
  const { disputes, isLoadingDisputes, createDispute, isCreatingDispute } = useMyDisputes();
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [reason, setReason] = useState<string>(DisputeReasonEnum.NotReceived);
  const [description, setDescription] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const existing = disputes.find((dispute) => dispute.order_id === orderId) ?? null;

  if (isLoadingDisputes) return null;

  if (existing) {
    return (
      <Link
        href={`/disputes/${existing.id}`}
        className="saas-card flex items-center gap-3 px-5 py-4 hover:border-blue-500/40 transition"
      >
        <Scale className="w-4 h-4 text-blue-400 shrink-0" strokeWidth={1.8} />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2 text-sm font-semibold text-fg">
            Dispute
            <DisputeStatusTag status={existing.status} />
          </span>
          <span className="block text-xs text-fg-muted">
            {REASON_LABELS[existing.reason] ?? existing.reason}
            {existing.decision_note ? ` · ${existing.decision_note}` : ""}
          </span>
        </span>
        <ArrowRight className="w-4 h-4 text-fg-dim shrink-0" />
      </Link>
    );
  }

  if (!isPaid) return null;

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const parsed = createDisputeSchema.safeParse({ reason, description });
    if (!parsed.success) {
      setErrorMessage(parsed.error.issues[0]?.message ?? "Check the form and try again");
      return;
    }
    setErrorMessage(null);
    createDispute({ orderId, payload: parsed.data })
      .then(() => {
        setIsFormOpen(false);
        setDescription("");
      })
      .catch((error: Error) => setErrorMessage(error.message));
  };

  if (!isFormOpen) {
    return (
      <div className="saas-card px-5 py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-fg">Something wrong with this order?</div>
          <p className="mt-0.5 text-xs text-fg-muted">
            Raise a dispute within 60 days of payment. A person reviews every dispute.
          </p>
        </div>
        <Button variant={ButtonVariantEnum.Outline} onClick={() => setIsFormOpen(true)} className="shrink-0">
          <Scale className="w-4 h-4" strokeWidth={1.8} />
          Raise a dispute
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="saas-card p-5 space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-sm font-semibold text-fg">Raise a dispute</h2>
          <p className="text-xs text-fg-muted max-w-xl">Tell us what went wrong. If it was a mistake on our side, we refund the payment.</p>
        </div>
        <button
          type="button"
          onClick={() => setIsFormOpen(false)}
          aria-label="Close"
          className="p-1 rounded-md text-fg-dim hover:text-fg hover:bg-fg/5"
        >
          <X className="w-4 h-4" strokeWidth={1.8} />
        </button>
      </div>

      {errorMessage !== null && (
        <p role="alert" className="text-xs text-rose-400">
          {errorMessage}
        </p>
      )}

      <div className="space-y-4 max-w-xl">
        <label className="block space-y-1.5">
          <span className="block text-[13px] font-medium text-fg-2">What happened?</span>
          <Select value={reason} onChange={setReason} options={REASON_OPTIONS} ariaLabel="Reason" />
        </label>

        <label className="block space-y-1.5">
          <span className="block text-[13px] font-medium text-fg-2">Details</span>
          <Textarea
            value={description}
            onChange={setDescription}
            maxLength={DESCRIPTION_MAX}
            rows={4}
            placeholder={`At least ${DESCRIPTION_MIN} characters. What did you expect, and what happened instead?`}
            className="w-full"
          />
          <span className="block text-right text-xs text-fg-dim tabular-nums">
            {description.length}/{DESCRIPTION_MAX}
          </span>
        </label>
      </div>

      <div className="flex items-center gap-2">
        <Button type="submit" isLoading={isCreatingDispute}>
          Send dispute
        </Button>
        <Button variant={ButtonVariantEnum.Ghost} disabled={isCreatingDispute} onClick={() => setIsFormOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
