import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { makeApiCall } from "@/shared/api/makeApiCall";
import { HttpMethodEnum } from "@/shared/enums";
import { DecideDisputePayload, DecideDisputeVariables, ManagerDispute, ManagerDisputeDetail } from "../types";

export function useDisputeDetail(disputeId: string, enabled: boolean) {
  const queryClient = useQueryClient();

  const detailQuery = useQuery<ManagerDisputeDetail>({
    queryKey: ["disputes", "detail", disputeId],
    queryFn: () =>
      makeApiCall<ManagerDisputeDetail>({
        endpoint: `/api/disputes/${encodeURIComponent(disputeId)}`,
        method: HttpMethodEnum.Get,
        silent: true,
      }),
    enabled,
    retry: false,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["disputes"] });
    queryClient.invalidateQueries({ queryKey: ["orders"] });
    queryClient.invalidateQueries({ queryKey: ["orderDetail"] });
  };

  const retriageMutation = useMutation<ManagerDispute, Error, string>({
    mutationFn: (id: string) =>
      makeApiCall<ManagerDispute>({
        endpoint: `/api/disputes/${encodeURIComponent(id)}/retriage`,
        method: HttpMethodEnum.Post,
        silent: true,
      }),
    onSuccess: refresh,
  });

  const decideMutation = useMutation<ManagerDispute, Error, DecideDisputeVariables>({
    mutationFn: ({ disputeId: id, payload }) =>
      makeApiCall<ManagerDispute, DecideDisputePayload>({
        endpoint: `/api/disputes/${encodeURIComponent(id)}/decision`,
        method: HttpMethodEnum.Post,
        payload,
        silent: true,
      }),
    onSuccess: refresh,
  });

  return {
    detail: detailQuery.data ?? null,
    isLoadingDetail: detailQuery.isLoading,
    isMissing: detailQuery.isError,
    retriage: retriageMutation.mutateAsync,
    isRetriaging: retriageMutation.isPending,
    decide: decideMutation.mutateAsync,
    isDeciding: decideMutation.isPending,
  };
}
