import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { makeApiCall } from "@/shared/api/makeApiCall";
import { HttpMethodEnum } from "@/shared/enums";
import { OrderFilterTabEnum } from "../enums";
import { ApiOrderDetail, toOrderDetail } from "../mappers";
import { OrderDetailResponse, OrderSummary } from "../types";
import { isInProgress } from "../utils";

export function useOrdersManagement(selectedTab: OrderFilterTabEnum = OrderFilterTabEnum.All, activeOrderId: string | null = null) {
  const queryClient = useQueryClient();

  const ordersListQuery = useQuery<OrderSummary[]>({
    queryKey: ["orders", selectedTab],
    queryFn: () =>
      makeApiCall<OrderSummary[]>({
        endpoint: `/api/me/orders?view=${selectedTab}`,
        method: HttpMethodEnum.Get,
      }),
  });

  const shouldFetchDetail = activeOrderId !== null && activeOrderId.length > 0;
  const orderDetailQuery = useQuery<OrderDetailResponse>({
    queryKey: ["orderDetail", activeOrderId],
    queryFn: () =>
      makeApiCall<ApiOrderDetail>({
        endpoint: `/api/me/orders/${encodeURIComponent(activeOrderId || "")}`,
        method: HttpMethodEnum.Get,
      }).then(toOrderDetail),
    enabled: shouldFetchDetail,
    refetchInterval: (query) => {
      const status = query.state.data?.order.status;
      return status !== undefined && isInProgress(status) ? 4000 : false;
    },
  });

  const approveOrderMutation = useMutation<OrderSummary, Error, { orderId: string; confirmTotal?: string }>({
    mutationFn: ({ orderId, confirmTotal }) =>
      makeApiCall<OrderSummary, { decision: string; confirm_total?: string }>({
        endpoint: `/api/me/orders/${encodeURIComponent(orderId)}/approval`,
        method: HttpMethodEnum.Post,
        payload: { decision: "approve", ...(confirmTotal ? { confirm_total: confirmTotal } : {}) },
      }),
    onSuccess: (_, { orderId }) => {
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      queryClient.invalidateQueries({ queryKey: ["orderDetail", orderId] });
    },
  });

  const declineOrderMutation = useMutation<OrderSummary, Error, string>({
    mutationFn: (orderId: string) =>
      makeApiCall<OrderSummary, { decision: string }>({
        endpoint: `/api/me/orders/${encodeURIComponent(orderId)}/approval`,
        method: HttpMethodEnum.Post,
        payload: { decision: "decline" },
      }),
    onSuccess: (_, orderId: string) => {
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      queryClient.invalidateQueries({ queryKey: ["orderDetail", orderId] });
    },
  });

  return {
    orders: Array.isArray(ordersListQuery.data) ? ordersListQuery.data : [],
    isLoadingOrders: ordersListQuery.isLoading,
    orderDetail: orderDetailQuery.data || null,
    isLoadingOrderDetail: orderDetailQuery.isLoading,
    approveOrder: approveOrderMutation.mutateAsync,
    isApprovingOrder: approveOrderMutation.isPending,
    declineOrder: declineOrderMutation.mutateAsync,
    isDecliningOrder: declineOrderMutation.isPending,
  };
}
