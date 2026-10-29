import { Suspense } from "react";
import { DisputesPage } from "@/features/disputes/presentation/pages/DisputesPage";

export const metadata = { title: "Disputes | Sepilo" };

export default function Page() {
  return (
    <Suspense>
      <DisputesPage />
    </Suspense>
  );
}
