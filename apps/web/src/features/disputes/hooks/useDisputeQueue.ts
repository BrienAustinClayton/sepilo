import { useQuery } from "@tanstack/react-query";
import { makeApiCall } from "@/shared/api/makeApiCall";
import { HttpMethodEnum } from "@/shared/enums";
import { DisputeStatusEnum, DisputeTabEnum } from "../enums";
import { ManagerDispute } from "../types";

function fetchByStatus(status: DisputeStatusEnum): Promise<ManagerDispute[]> {
  return makeApiCall<ManagerDispute[]>({
    endpoint: `/api/disputes?status=${status}`,
    method: HttpMethodEnum.Get,
    silent: true,
  });
}

function decidedAtMs(dispute: ManagerDispute): number {
  const time = dispute.decided_at ? new Date(dispute.decided_at).getTime() : 0;
  return Number.isNaN(time) ? 0 : time;
}

async function fetchDecided(): Promise<ManagerDispute[]> {
  const [refunded, rejected] = await Promise.all([
    fetchByStatus(DisputeStatusEnum.Refunded),
    fetchByStatus(DisputeStatusEnum.Rejected),
  ]);
  return [...refunded, ...rejected].sort((a, b) => decidedAtMs(b) - decidedAtMs(a));
}

export function useDisputeQueue(tab: DisputeTabEnum, enabled: boolean) {
  const queueQuery = useQuery<ManagerDispute[]>({
    queryKey: ["disputes", "queue"],
    queryFn: () => fetchByStatus(DisputeStatusEnum.Open),
    enabled: enabled && tab === DisputeTabEnum.Queue,
  });

  const decidedQuery = useQuery<ManagerDispute[]>({
    queryKey: ["disputes", "decided"],
    queryFn: fetchDecided,
    enabled: enabled && tab === DisputeTabEnum.Decided,
  });

  const active = tab === DisputeTabEnum.Decided ? decidedQuery : queueQuery;

  return {
    disputes: Array.isArray(active.data) ? active.data : [],
    isLoadingQueue: active.isLoading,
    loadError: active.isError,
  };
}
