"use client";

import React from "react";
import { MapPin } from "lucide-react";
import { ShippingAddressCardProps } from "../../componentTypes";

export function ShippingAddressCard({ address }: ShippingAddressCardProps) {
  const region = address.region ?? address.state;
  const cityLine = [address.city, region, address.postal_code].filter((part): part is string => Boolean(part)).join(", ");
  const lines = [address.name, address.line1, address.line2, cityLine, address.country].filter(
    (line): line is string => Boolean(line),
  );

  if (lines.length === 0) return null;

  return (
    <div className="saas-card p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
        <MapPin className="h-4 w-4 text-blue-400" strokeWidth={1.8} aria-hidden="true" />
        Ships to
      </h2>
      <address className="mt-2 text-sm not-italic text-fg-2 space-y-0.5">
        {lines.map((line) => (
          <div key={line}>{line}</div>
        ))}
      </address>
    </div>
  );
}
