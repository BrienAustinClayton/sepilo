export interface ShippingAddress {
  name: string;
  line1: string;
  line2?: string;
  city: string;
  region?: string;
  postal_code: string;
  country: string;
  phone?: string;
}

export interface AddressResponse {
  address: ShippingAddress | null;
  updated_at: string | null;
}
