"use client";

import React from "react";
import { Check as CheckIcon, Flag, Minus, X } from "lucide-react";
import { SecurityTimelineProps } from "../../componentTypes";
import { SecurityCheckResultEnum, SecurityCheckStepEnum } from "../../enums";
import { SecurityCheckRecord } from "../../types";
import { getStepDisplayName, readPreflight } from "../../utils";
import { PreflightChecklist } from "./PreflightChecklist";

export function SecurityChecksTimeline({ checks }: SecurityTimelineProps) {
  const hasNoChecks = checks.length === 0;

  if (hasNoChecks) {
    return (
      <div className="p-6 text-center text-sm text-fg-muted">
        No security checks recorded for this order yet.
      </div>
    );
  }

  return (
    <div className="divide-y divide-line">
      {checks.map((check: SecurityCheckRecord, index: number) => {
        const isPass = check.result === SecurityCheckResultEnum.Pass;
        const isFail = check.result === SecurityCheckResultEnum.Fail || check.result === SecurityCheckResultEnum.Error;
        const isFlag = check.result === SecurityCheckResultEnum.Flag;

        const badgeColor = isPass
          ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
          : isFail
          ? "bg-rose-500/10 text-rose-400 border border-rose-500/20"
          : isFlag
          ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
          : "bg-neutral-500/10 text-neutral-400 border border-neutral-500/20";

        const stepName = getStepDisplayName(check.step);
        const preflight = check.step === SecurityCheckStepEnum.Preflight ? readPreflight(check.details) : null;

        return (
          <div key={index}>
            <div className="flex items-center justify-between p-3.5">
              <div className="flex items-center gap-3">
                <span className={`flex h-7 w-7 items-center justify-center rounded-lg text-xs font-semibold ${badgeColor}`}>
                  {isPass ? (
                    <CheckIcon className="w-3.5 h-3.5" strokeWidth={2.5} />
                  ) : isFail ? (
                    <X className="w-3.5 h-3.5" strokeWidth={2.5} />
                  ) : isFlag ? (
                    <Flag className="w-3.5 h-3.5" strokeWidth={2} />
                  ) : (
                    <Minus className="w-3.5 h-3.5" />
                  )}
                </span>
                <div>
                  <div className="text-sm font-medium text-fg">{stepName}</div>
                  <div className="text-xs text-fg-dim">
                    Latency: {check.latency_ms} ms
                  </div>
                </div>
              </div>

              <span className={`px-2 py-0.5 rounded-full text-xs font-medium uppercase tracking-wider ${badgeColor}`}>
                {check.result}
              </span>
            </div>
            {preflight && <PreflightChecklist summary={preflight} />}
          </div>
        );
      })}
    </div>
  );
}
