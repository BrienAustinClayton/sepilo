import { Suspense } from "react";
import { AddressPage } from "@/features/address/presentation/pages/AddressPage";

export const metadata = { title: "Shipping address | Sepilo" };

export default function Page() {
  return (
    <Suspense>
      <AddressPage />
    </Suspense>
  );
}
