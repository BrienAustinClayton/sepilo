"use client";

import React, { useState } from "react";
import { ApiCallError } from "@/shared/api/ApiCallError";
import { ToastTypeEnum } from "@/shared/enums";
import { showToast } from "@/shared/toast/toastManager";
import { useShippingAddress } from "../../hooks/useShippingAddress";
import { AddressFormValues, toAddressFormValues, toAddressPayload } from "../../schemas";
import { AddressForm } from "../components/AddressForm";

export function AddressPage() {
  const { address, isLoadingAddress, saveAddress, isSaving } = useShippingAddress();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSave = (values: AddressFormValues) => {
    setErrorMessage(null);
    saveAddress(toAddressPayload(values))
      .then(() => showToast("Shipping address saved", ToastTypeEnum.Success))
      .catch((error: unknown) => {
        setErrorMessage(error instanceof ApiCallError ? error.message : "Could not save the address. Try again.");
      });
  };

  return (
    <div className="max-w-3xl">
      <div className="mb-6 space-y-1">
        <h1 className="text-xl font-semibold tracking-tight">Shipping address</h1>
        <p className="text-sm text-fg-muted max-w-2xl">Sepilo only pays for orders that ship to this address.</p>
      </div>

      <div className="saas-card overflow-hidden p-5">
        {isLoadingAddress ? (
          <div className="text-sm text-fg-muted">Loading address...</div>
        ) : (
          <AddressForm
            initialValues={toAddressFormValues(address)}
            isSaving={isSaving}
            errorMessage={errorMessage}
            onSubmit={handleSave}
          />
        )}
      </div>
    </div>
  );
}
