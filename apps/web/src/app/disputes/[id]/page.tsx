export const instant = false;

import { Suspense } from "react";
import { ServerDisputeDetailPageProps } from "@/features/disputes/pageTypes";
import { DisputeDetailPage } from "@/features/disputes/presentation/pages/DisputeDetailPage";

export default async function Page({ params }: ServerDisputeDetailPageProps) {
  const resolvedParams = await params;

  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-3xl w-full px-6 py-10">
          <p className="text-sm text-fg-muted">Loading dispute...</p>
        </div>
      }
    >
      <DisputeDetailPage disputeId={resolvedParams.id} />
    </Suspense>
  );
}
