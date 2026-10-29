import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { makeApiCall } from "@/shared/api/makeApiCall";
import { HttpMethodEnum } from "@/shared/enums";
import { ConnectAgentPayload, ShoppingAgent } from "../types";

export function useAgentsManagement() {
  const queryClient = useQueryClient();

  const agentsQuery = useQuery<ShoppingAgent[]>({
    queryKey: ["agents"],
    queryFn: () =>
      makeApiCall<ShoppingAgent[]>({
        endpoint: "/api/me/agents",
        method: HttpMethodEnum.Get,
      }),
  });

  const connectAgentMutation = useMutation<ShoppingAgent, Error, ConnectAgentPayload>({
    mutationFn: (payload: ConnectAgentPayload) =>
      makeApiCall<ShoppingAgent, ConnectAgentPayload>({
        endpoint: "/api/me/agents",
        method: HttpMethodEnum.Post,
        payload,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });

  const revokeAgentMutation = useMutation<ShoppingAgent, Error, string>({
    mutationFn: (agentId: string) =>
      makeApiCall<ShoppingAgent>({
        endpoint: `/api/me/agents/${encodeURIComponent(agentId)}/revoke`,
        method: HttpMethodEnum.Post,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });

  return {
    agents: Array.isArray(agentsQuery.data) ? agentsQuery.data : [],
    isLoadingAgents: agentsQuery.isLoading,
    connectAgent: connectAgentMutation.mutateAsync,
    isConnectingAgent: connectAgentMutation.isPending,
    revokeAgent: revokeAgentMutation.mutateAsync,
    isRevokingAgent: revokeAgentMutation.isPending,
  };
}
