"use client";

import React, { useId, useState } from "react";
import { Check, ChevronDown, Minus, ThumbsUp, X } from "lucide-react";
import { PreflightStatusEnum } from "../../enums";
import { PreflightChecklistProps } from "../../componentTypes";

const ITEM_TONE: Record<PreflightStatusEnum, string> = {
  [PreflightStatusEnum.Pass]: "text-emerald-400",
  [PreflightStatusEnum.Fail]: "text-rose-400",
  [PreflightStatusEnum.Accepted]: "text-amber-400",
  [PreflightStatusEnum.NotSent]: "text-fg-dim",
};

const ITEM_NOTE: Partial<Record<PreflightStatusEnum, string>> = {
  [PreflightStatusEnum.Accepted]: "Warning you reviewed",
  [PreflightStatusEnum.NotSent]: "Not sent",
};

function ItemIcon({ status }: { status: PreflightStatusEnum }) {
  const className = "w-3.5 h-3.5 shrink-0";
  if (status === PreflightStatusEnum.Pass) return <Check className={className} strokeWidth={2.5} />;
  if (status === PreflightStatusEnum.Accepted) return <ThumbsUp className={className} strokeWidth={2} />;
  if (status === PreflightStatusEnum.Fail) return <X className={className} strokeWidth={2.5} />;
  return <Minus className={className} />;
}

export function PreflightChecklist({ summary }: PreflightChecklistProps) {
  const [isOpen, setIsOpen] = useState(false);
  const listId = useId();

  return (
    <div className="px-3.5 pb-3.5 -mt-1">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
        aria-controls={listId}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-400 hover:text-blue-300 transition"
      >
        {summary.passed} of {summary.total} passed
        <ChevronDown className={`w-3.5 h-3.5 transition-transform ${isOpen ? "rotate-180" : ""}`} strokeWidth={2} />
      </button>

      {isOpen && (
        <ul id={listId} className="mt-2 space-y-1.5">
          {summary.items.map((item) => (
            <li key={item.id} className="flex items-start gap-2 text-xs">
              <span className={`mt-0.5 ${ITEM_TONE[item.status]}`}>
                <ItemIcon status={item.status} />
              </span>
              <span className="min-w-0">
                <span className="text-fg-2">{item.label}</span>
                {(item.detail || ITEM_NOTE[item.status]) && (
                  <span className="block text-fg-dim">{item.detail || ITEM_NOTE[item.status]}</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
