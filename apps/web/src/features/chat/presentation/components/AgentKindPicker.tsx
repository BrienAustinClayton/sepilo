"use client";

import React from "react";
import { AgentKind } from "@/lib/types";
import { AGENT_CHOICES } from "../../constants";

interface AgentKindPickerProps {
  value: AgentKind;
  onChange: (kind: AgentKind) => void;
}

export function AgentKindPicker({ value, onChange }: AgentKindPickerProps) {
  const current = AGENT_CHOICES.find((choice) => choice.kind === value) ?? AGENT_CHOICES[0];

  return (
    <div className="space-y-2 max-w-sm mx-auto">
      <div role="radiogroup" aria-label="Agent" className="flex w-full rounded-full bg-fg/6 p-1">
        {AGENT_CHOICES.map((choice) => {
          const isSelected = choice.kind === value;
          return (
            <button
              key={choice.kind}
              type="button"
              role="radio"
              aria-checked={isSelected}
              onClick={() => onChange(choice.kind)}
              className={`flex-1 rounded-full px-3 py-1.5 text-sm font-medium transition ${
                isSelected ? "bg-canvas text-fg shadow-sm" : "text-fg-muted hover:text-fg"
              }`}
            >
              {choice.label}
            </button>
          );
        })}
      </div>
      <p className="text-xs text-fg-dim">{current.hint}</p>
    </div>
  );
}
