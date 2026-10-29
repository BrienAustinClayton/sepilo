import { z } from "zod";
import { ShippingAddress } from "./types";

export const addressFormSchema = z.object({
  name: z.string().trim().min(1, "Enter the name the order goes to").max(100, "Keep it under 100 characters"),
  line1: z.string().trim().min(1, "Enter a street address").max(200, "Keep it under 200 characters"),
  line2: z.string().trim().max(200, "Keep it under 200 characters"),
  city: z.string().trim().min(1, "Enter a city").max(100, "Keep it under 100 characters"),
  region: z.string().trim().max(100, "Keep it under 100 characters"),
  postalCode: z.string().trim().regex(/^[A-Za-z0-9 -]{2,20}$/, "Enter a valid postal code"),
  country: z.string().trim().regex(/^[A-Za-z]{2}$/, "Use a 2-letter country code, like US"),
  phone: z
    .string()
    .trim()
    .refine((val: string) => val === "" || /^\+?[0-9 ()-]{6,20}$/.test(val), "Enter a valid phone number"),
});

export type AddressFormValues = z.infer<typeof addressFormSchema>;

export const EMPTY_ADDRESS_FORM: AddressFormValues = {
  name: "",
  line1: "",
  line2: "",
  city: "",
  region: "",
  postalCode: "",
  country: "",
  phone: "",
};

export function toAddressFormValues(address: ShippingAddress | null): AddressFormValues {
  if (!address) return EMPTY_ADDRESS_FORM;
  return {
    name: address.name,
    line1: address.line1,
    line2: address.line2 ?? "",
    city: address.city,
    region: address.region ?? "",
    postalCode: address.postal_code,
    country: address.country,
    phone: address.phone ?? "",
  };
}

export function toAddressPayload(values: AddressFormValues): ShippingAddress {
  const optional = (val: string) => (val === "" ? undefined : val);
  return {
    name: values.name,
    line1: values.line1,
    line2: optional(values.line2),
    city: values.city,
    region: optional(values.region),
    postal_code: values.postalCode,
    country: values.country,
    phone: optional(values.phone),
  };
}
