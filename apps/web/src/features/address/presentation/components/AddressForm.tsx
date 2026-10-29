"use client";

import React, { useState } from "react";
import { Button } from "@/shared/presentation/components/Button";
import { Input } from "@/shared/presentation/components/Input";
import { ButtonVariantEnum } from "@/shared/enums";
import { AddressFormValues, addressFormSchema } from "../../schemas";

type FieldErrors = Partial<Record<keyof AddressFormValues, string>>;

interface AddressFormProps {
  initialValues: AddressFormValues;
  isSaving: boolean;
  errorMessage: string | null;
  onSubmit: (values: AddressFormValues) => void;
}

function Field({ label, error, className = "", children }: { label: string; error?: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={`block space-y-1.5 ${className}`}>
      <span className="block text-[13px] font-medium text-fg-2">{label}</span>
      {children}
      {error && (
        <span role="alert" className="block text-xs text-rose-400">
          {error}
        </span>
      )}
    </label>
  );
}

export function AddressForm({ initialValues, isSaving, errorMessage, onSubmit }: AddressFormProps) {
  const [values, setValues] = useState<AddressFormValues>(initialValues);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});

  const updateField = (field: keyof AddressFormValues, value: string) => {
    setValues((prev: AddressFormValues) => ({ ...prev, [field]: value }));
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const result = addressFormSchema.safeParse(values);
    if (!result.success) {
      const nextErrors: FieldErrors = {};
      result.error.issues.forEach((issue) => {
        const field = String(issue.path[0]) as keyof AddressFormValues;
        if (!nextErrors[field]) nextErrors[field] = issue.message;
      });
      setFieldErrors(nextErrors);
      return;
    }
    setFieldErrors({});
    onSubmit(result.data);
  };

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl">
      <Field label="Full name" error={fieldErrors.name} className="sm:col-span-2">
        <Input name="name" required maxLength={100} placeholder="Alice Smith" value={values.name} onChange={(v: string) => updateField("name", v)} />
      </Field>

      <Field label="Address line 1" error={fieldErrors.line1} className="sm:col-span-2">
        <Input name="line1" required maxLength={200} placeholder="Street and number" value={values.line1} onChange={(v: string) => updateField("line1", v)} />
      </Field>

      <Field label="Address line 2" error={fieldErrors.line2} className="sm:col-span-2">
        <Input name="line2" maxLength={200} placeholder="Apartment, suite, unit (optional)" value={values.line2} onChange={(v: string) => updateField("line2", v)} />
      </Field>

      <Field label="City" error={fieldErrors.city}>
        <Input name="city" required maxLength={100} value={values.city} onChange={(v: string) => updateField("city", v)} />
      </Field>

      <Field label="State / region" error={fieldErrors.region}>
        <Input name="region" maxLength={100} placeholder="Optional" value={values.region} onChange={(v: string) => updateField("region", v)} />
      </Field>

      <Field label="Postal code" error={fieldErrors.postalCode}>
        <Input name="postalCode" required maxLength={20} value={values.postalCode} onChange={(v: string) => updateField("postalCode", v)} />
      </Field>

      <Field label="Country code" error={fieldErrors.country}>
        <Input name="country" required maxLength={2} placeholder="US" value={values.country} onChange={(v: string) => updateField("country", v.toUpperCase())} />
      </Field>

      <Field label="Phone" error={fieldErrors.phone} className="sm:col-span-2">
        <Input name="phone" maxLength={20} placeholder="Optional, for delivery questions" value={values.phone} onChange={(v: string) => updateField("phone", v)} />
      </Field>

      {errorMessage !== null && (
        <p role="alert" className="sm:col-span-2 text-xs text-rose-400">
          {errorMessage}
        </p>
      )}

      <div className="sm:col-span-2">
        <Button variant={ButtonVariantEnum.Primary} type="submit" disabled={isSaving} isLoading={isSaving}>
          Save address
        </Button>
      </div>
    </form>
  );
}
