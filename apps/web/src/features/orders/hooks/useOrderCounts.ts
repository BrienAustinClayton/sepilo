import { useQuery } from "@tanstack/react-query";
import { makeApiCall } from "@/shared/api/makeApiCall";
import { HttpMethodEnum } from "@/shared/enums";
import { OrderCounts } from "../types";

export function useOrderCounts() {
  const countsQuery = useQuery<OrderCounts>({
    queryKey: ["orders", "counts"],
    queryFn: () =>
      makeApiCall<OrderCounts>({
        endpoint: "/api/me/orders/counts",
        method: HttpMethodEnum.Get,
      }),
  });

  return { counts: countsQuery.data ?? null };
}
