import { z } from "zod";
import { DisputeDecisionEnum, DisputeReasonEnum } from "./enums";
import { amountMatches } from "./utils";

export const DESCRIPTION_MIN = 10;
export const DESCRIPTION_MAX = 2000;
export const NOTE_MIN = 3;
export const NOTE_MAX = 1000;

export const createDisputeSchema = z.object({
  reason: z.nativeEnum(DisputeReasonEnum),
  description: z
    .string()
    .trim()
    .min(DESCRIPTION_MIN, `Describe the problem in at least ${DESCRIPTION_MIN} characters`)
    .max(DESCRIPTION_MAX, `Keep it under ${DESCRIPTION_MAX} characters`),
});

export function buildDecisionSchema(total: string) {
  return z
    .object({
      decision: z.nativeEnum(DisputeDecisionEnum),
      note: z
        .string()
        .trim()
        .min(NOTE_MIN, `Add a note of at least ${NOTE_MIN} characters`)
        .max(NOTE_MAX, `Keep the note under ${NOTE_MAX} characters`),
      confirmTotal: z.string().trim(),
    })
    .superRefine((value, ctx) => {
      if (value.decision === DisputeDecisionEnum.Refund && !amountMatches(value.confirmTotal, total)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["confirmTotal"],
          message: `Type $${Number(total).toFixed(2)} to confirm the refund`,
        });
      }
    });
}
