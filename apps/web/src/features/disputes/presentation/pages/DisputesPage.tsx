"use client";

import React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Scale } from "lucide-react";
import { DisputeTabEnum } from "../../enums";
import { EMPTY_TEXT } from "../../constants";
import { useDisputeQueue } from "../../hooks/useDisputeQueue";
import { useDisputeRole } from "../../hooks/useDisputeRole";
import { useMyDisputes } from "../../hooks/useMyDisputes";
import { ManagerDisputesList } from "../components/ManagerDisputesList";
import { MyDisputesList } from "../components/MyDisputesList";

const TAB_LABELS: Record<DisputeTabEnum, string> = {
  [DisputeTabEnum.Queue]: "Queue",
  [DisputeTabEnum.Decided]: "Decided",
  [DisputeTabEnum.Mine]: "My disputes",
};

const TABS = Object.values(DisputeTabEnum);

function parseTab(value: string | null): DisputeTabEnum {
  return TABS.find((tab) => tab === value) ?? DisputeTabEnum.Queue;
}

export function DisputesPage() {
  const router = useRouter();
  const params = useSearchParams();
  const { isLoadingRole, isManager } = useDisputeRole();

  const requestedTab = parseTab(params.get("tab"));
  const currentTab = isManager ? requestedTab : DisputeTabEnum.Mine;
  const setCurrentTab = (tab: DisputeTabEnum) =>
    router.replace(tab === DisputeTabEnum.Queue ? "/disputes" : `/disputes?tab=${tab}`, { scroll: false });

  const { disputes: myDisputes, isLoadingDisputes } = useMyDisputes();
  const { disputes: managerDisputes, isLoadingQueue, loadError } = useDisputeQueue(currentTab, isManager);

  if (isLoadingRole) {
    return <div className="p-8 text-center text-sm text-fg-muted">Loading...</div>;
  }

  const isMine = currentTab === DisputeTabEnum.Mine;
  const isLoading = isMine ? isLoadingDisputes : isLoadingQueue;
  const count = isMine ? myDisputes.length : managerDisputes.length;
  const emptyText = EMPTY_TEXT[currentTab];

  return (
    <div>
      <div className="mb-6 space-y-1">
        <h1 className="text-xl font-semibold tracking-tight">Disputes</h1>
        <p className="text-sm text-fg-muted max-w-2xl">
          {isManager
            ? "Review disputes on paid orders, most urgent first. Jev suggests an outcome; you make the decision."
            : "Something wrong with a paid order? Raise a dispute from the order page and track our reply here."}
        </p>
      </div>

      {isManager && (
        <div role="tablist" className="flex items-center gap-1 mb-4 border-b border-line overflow-x-auto whitespace-nowrap -mx-4 px-4 sm:mx-0 sm:px-0">
          {TABS.map((tab) => {
            const isSelected = tab === currentTab;
            return (
              <button
                key={tab}
                role="tab"
                aria-selected={isSelected}
                onClick={() => setCurrentTab(tab)}
                className={`relative px-3 h-9 text-[13px] font-medium transition ${
                  isSelected ? "text-fg" : "text-fg-muted hover:text-fg"
                }`}
              >
                {TAB_LABELS[tab]}
                {isSelected && <span className="absolute left-2 right-2 -bottom-px h-0.5 rounded-full bg-blue-500" />}
              </button>
            );
          })}
        </div>
      )}

      <div className="saas-card overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-sm text-fg-muted">Loading disputes...</div>
        ) : !isMine && loadError ? (
          <div className="p-8 text-center text-sm text-rose-400">Could not load disputes. Try again in a moment.</div>
        ) : count === 0 ? (
          <div className="flex flex-col items-center text-center px-6 py-14">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-fg/5 text-fg-muted mb-4">
              <Scale className="w-5 h-5" strokeWidth={1.8} />
            </span>
            <h3 className="text-sm font-semibold text-fg">No disputes here</h3>
            <p className="mt-1 text-sm text-fg-muted max-w-sm">{emptyText}</p>
          </div>
        ) : isMine ? (
          <MyDisputesList disputes={myDisputes} />
        ) : (
          <ManagerDisputesList disputes={managerDisputes} />
        )}
      </div>
    </div>
  );
}
