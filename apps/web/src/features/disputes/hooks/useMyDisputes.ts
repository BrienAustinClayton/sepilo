import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { makeApiCall } from "@/shared/api/makeApiCall";
import { HttpMethodEnum } from "@/shared/enums";
import { CreateDisputePayload, Dispute } from "../types";

export function useMyDisputes() {
  const queryClient = useQueryClient();

  const disputesQuery = useQuery<Dispute[]>({
    queryKey: ["disputes", "mine"],
    queryFn: () =>
      makeApiCall<Dispute[]>({
        endpoint: "/api/me/disputes",
        method: HttpMethodEnum.Get,
        silent: true,
      }),
  });

  const createDisputeMutation = useMutation<Dispute, Error, { orderId: string; payload: CreateDisputePayload }>({
    mutationFn: ({ orderId, payload }) =>
      makeApiCall<Dispute, CreateDisputePayload>({
        endpoint: `/api/me/orders/${encodeURIComponent(orderId)}/disputes`,
        method: HttpMethodEnum.Post,
        payload,
        silent: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["disputes"] });
    },
  });

  return {
    disputes: Array.isArray(disputesQuery.data) ? disputesQuery.data : [],
    isLoadingDisputes: disputesQuery.isLoading,
    createDispute: createDisputeMutation.mutateAsync,
    isCreatingDispute: createDisputeMutation.isPending,
  };
}

export function useMyDispute(disputeId: string, enabled: boolean) {
  const disputeQuery = useQuery<Dispute>({
    queryKey: ["disputes", "mine", disputeId],
    queryFn: () =>
      makeApiCall<Dispute>({
        endpoint: `/api/me/disputes/${encodeURIComponent(disputeId)}`,
        method: HttpMethodEnum.Get,
        silent: true,
      }),
    enabled,
    retry: false,
  });

  return {
    dispute: disputeQuery.data ?? null,
    isLoadingDispute: disputeQuery.isLoading,
    isMissing: disputeQuery.isError,
  };
}
