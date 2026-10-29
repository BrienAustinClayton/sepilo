import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiCallError } from "@/shared/api/ApiCallError";
import { makeApiCall } from "@/shared/api/makeApiCall";
import { signInAgainFor } from "@/features/auth/utils";
import { resetMe } from "@/lib/useMe";
import { HttpMethodEnum } from "@/shared/enums";
import { AddressResponse, ShippingAddress } from "../types";

export function useShippingAddress() {
  const queryClient = useQueryClient();

  const addressQuery = useQuery<AddressResponse>({
    queryKey: ["shippingAddress"],
    queryFn: () =>
      makeApiCall<AddressResponse>({
        endpoint: "/api/me/address",
        method: HttpMethodEnum.Get,
      }),
  });

  const saveAddressMutation = useMutation<AddressResponse, Error, ShippingAddress>({
    mutationFn: (payload: ShippingAddress) =>
      makeApiCall<AddressResponse, ShippingAddress>({
        endpoint: "/api/me/address",
        method: HttpMethodEnum.Put,
        payload,
        silent: true,
      }).catch((error: unknown) => {
        if (error instanceof ApiCallError && error.errorCode === "reauth_required") {
          return signInAgainFor("/address").then(() => Promise.reject(error));
        }
        return Promise.reject(error);
      }),
    onSuccess: () => {
      resetMe();
      queryClient.invalidateQueries({ queryKey: ["shippingAddress"] });
    },
  });

  return {
    address: addressQuery.data?.address ?? null,
    isLoadingAddress: addressQuery.isLoading,
    saveAddress: saveAddressMutation.mutateAsync,
    isSaving: saveAddressMutation.isPending,
  };
}
