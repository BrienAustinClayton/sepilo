"use client";

import React from "react";
import { Bot } from "lucide-react";
import { AgentsTableProps } from "../../componentTypes";
import { AgentStatusEnum } from "../../enums";
import { agentKindBadge } from "../../constants";
import { ShoppingAgent } from "../../types";
import { CopyAgentIdButton } from "./CopyAgentIdButton";

export function AgentsTable({ agents, onDisconnectAgent }: AgentsTableProps) {
  const hasNoAgents = agents.length === 0;

  if (hasNoAgents) {
    return (
      <div className="flex flex-col items-center text-center px-6 py-14">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-fg/5 text-fg-muted mb-4">
          <Bot className="w-5 h-5" strokeWidth={1.8} />
        </span>
        <h3 className="text-sm font-semibold text-fg">No agents connected</h3>
        <p className="mt-1 text-sm text-fg-muted max-w-sm">
          Connect your first agent to start shopping safely.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead className="border-b border-line bg-fg/2">
          <tr>
            <th className="px-4 py-2.5 text-left text-xs font-medium text-fg-dim whitespace-nowrap">Name</th>
            <th className="px-4 py-2.5 text-left text-xs font-medium text-fg-dim whitespace-nowrap">Agent ID</th>
            <th className="px-4 py-2.5 text-left text-xs font-medium text-fg-dim whitespace-nowrap">Type</th>
            <th className="px-4 py-2.5 text-left text-xs font-medium text-fg-dim whitespace-nowrap">Status</th>
            <th className="px-4 py-2.5 text-right text-xs font-medium text-fg-dim whitespace-nowrap">Action</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((agent: ShoppingAgent) => {
            const isActive = agent.status === AgentStatusEnum.Active;
            const statusLabel = isActive ? "Active" : "Revoked";
            const statusBadgeStyle = isActive
              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
              : "bg-neutral-500/10 text-neutral-400 border border-neutral-500/20";

            return (
              <tr key={agent.id} className="border-b border-line last:border-0 transition hover:bg-fg/2">
                <td className="px-4 py-3 text-sm text-fg-2 align-middle font-medium">
                  {agent.name}
                </td>
                <td className="px-4 py-3 text-sm text-fg-2 align-middle">
                  <CopyAgentIdButton value={agent.id} />
                </td>
                <td className="px-4 py-3 text-sm text-fg-2 align-middle">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${agentKindBadge(agent.kind).style}`}>
                      {agentKindBadge(agent.kind).label}
                    </span>
                    <span className="text-xs text-fg-muted">
                      {agent.managed ? "Hosted by Sepilo" : "External Agent"}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-3 text-sm text-fg-2 align-middle">
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${statusBadgeStyle}`}>
                    {statusLabel}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-fg-2 align-middle text-right">
                  {isActive && (
                    <button
                      type="button"
                      onClick={() => onDisconnectAgent(agent)}
                      className="text-xs text-rose-400 hover:text-rose-300 font-medium"
                    >
                      Disconnect
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
