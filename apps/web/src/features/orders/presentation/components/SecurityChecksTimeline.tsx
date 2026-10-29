"use client";

import React from "react";
import { Check, Flag, LucideIcon, Minus, X } from "lucide-react";
import { PIPELINE_STEPS } from "../../constants";
import { SecurityTimelineProps } from "../../componentTypes";
import { SecurityCheckResultEnum, SecurityCheckStepEnum } from "../../enums";
import { SecurityCheckRecord } from "../../types";
import { describePreflight, readPreflight } from "../../utils";

interface StepLook {
  Icon: LucideIcon;
  tone: string;
  text: string;
  label: string;
}

const PASS_TONE = "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";
const FAIL_TONE = "bg-rose-500/10 text-rose-400 border border-rose-500/20";
const FLAG_TONE = "bg-amber-500/10 text-amber-400 border border-amber-500/20";
const IDLE_TONE = "bg-fg/5 text-fg-dim border border-line";

const FLAG_LABELS: Record<string, string> = {
  [SecurityCheckStepEnum.AuthorizePayment]: "Waiting for PayPal",
  [SecurityCheckStepEnum.CaptureOrVoid]: "Waiting for you",
};

function look(step: string, check: SecurityCheckRecord | undefined): StepLook {
  if (!check) return { Icon: Minus, tone: IDLE_TONE, text: "text-fg-dim", label: "Not run" };
  switch (check.result) {
    case SecurityCheckResultEnum.Pass:
      return { Icon: Check, tone: PASS_TONE, text: "text-emerald-400", label: "Passed" };
    case SecurityCheckResultEnum.Fail:
      return { Icon: X, tone: FAIL_TONE, text: "text-rose-400", label: "Failed" };
    case SecurityCheckResultEnum.Error:
      return { Icon: X, tone: FAIL_TONE, text: "text-rose-400", label: "Error" };
    case SecurityCheckResultEnum.Flag:
      return { Icon: Flag, tone: FLAG_TONE, text: "text-amber-400", label: FLAG_LABELS[step] ?? "Flagged" };
    default:
      return { Icon: Minus, tone: IDLE_TONE, text: "text-fg-dim", label: "Skipped" };
  }
}

function formatDuration(ms: number): string {
  if (ms <= 0) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function SecurityChecksTimeline({ checks }: SecurityTimelineProps) {
  const latest = new Map<string, SecurityCheckRecord>();
  checks.forEach((check) => latest.set(check.step, check));

  return (
    <ol className="px-5 py-4">
      {PIPELINE_STEPS.map((info, index) => {
        const check = latest.get(info.step);
        const { Icon, tone, text, label } = look(info.step, check);
        const isLast = index === PIPELINE_STEPS.length - 1;
        const duration = check ? formatDuration(check.latency_ms) : "";
        const preflight = check && info.step === SecurityCheckStepEnum.Preflight ? readPreflight(check.details) : null;

        return (
          <li key={info.step} className={`relative flex gap-3 ${isLast ? "" : "pb-4"}`}>
            {!isLast && <span className="absolute left-3.5 top-8 bottom-0 w-px -translate-x-1/2 bg-line" aria-hidden="true" />}
            <span className={`relative flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${tone}`}>
              <Icon className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="text-sm font-medium text-fg">{info.name}</span>
                <span className="text-xs text-fg-dim tabular-nums">
                  <span className={text}>{label}</span>
                  {duration && ` · ${duration}`}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-fg-muted">{info.description}</p>
              {preflight && (
                <a href="#security-checks" className="mt-1 inline-block text-xs font-medium text-blue-400 hover:text-blue-300">
                  {describePreflight(preflight)}
                </a>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
