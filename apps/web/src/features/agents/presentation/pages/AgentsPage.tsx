"use client";

import React, { useState } from "react";
import { Plug } from "lucide-react";
import { AgentModalTypeEnum } from "../../enums";
import { useAgentsManagement } from "../../hooks/useAgentsManagement";
import { ShoppingAgent } from "../../types";
import { AgentsTable } from "../components/AgentsTable";
import { ConnectCustomAgentForm } from "../components/ConnectCustomAgentForm";

export function AgentsPage() {
  const [activeModal, setActiveModal] = useState<AgentModalTypeEnum>(
    AgentModalTypeEnum.None
  );
  const { agents, isLoadingAgents, revokeAgent } = useAgentsManagement();

  const handleDisconnect = (agent: ShoppingAgent) => {
    const confirmationPrompt = `Disconnect ${agent.name}? It will no longer be able to check out on your behalf.`;
    const userConfirmed = window.confirm(confirmationPrompt);
    if (!userConfirmed) {
      return;
    }
    revokeAgent(agent.id);
  };

  const isCustomModalOpen = activeModal === AgentModalTypeEnum.Own;
  const isModalClosed = activeModal === AgentModalTypeEnum.None;

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-6">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold tracking-tight">Agents</h1>
          <p className="text-sm text-fg-muted max-w-2xl">
            AI agents allowed to shop for you. Every checkout an agent makes is signed, checked against your rules,
            and only then paid.
          </p>
        </div>

        {isModalClosed && (
          <div className="flex flex-wrap items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => setActiveModal(AgentModalTypeEnum.Own)}
              className="intentlock-btn-outline"
            >
              <Plug className="w-4 h-4" strokeWidth={1.8} />
              Connect your own
            </button>
          </div>
        )}
      </div>

      {isCustomModalOpen && (
        <ConnectCustomAgentForm
          onClose={() => setActiveModal(AgentModalTypeEnum.None)}
        />
      )}

      <div className="saas-card overflow-hidden">
        {isLoadingAgents ? (
          <div className="p-8 text-center text-sm text-fg-muted">
            Loading agents...
          </div>
        ) : (
          <AgentsTable
            agents={agents}
            onDisconnectAgent={handleDisconnect}
          />
        )}
      </div>
    </div>
  );
}
