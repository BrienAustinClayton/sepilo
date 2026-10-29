import { z } from "zod";

export const connectCustomAgentSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(100),
  publicKey: z.string().trim().min(1, "Public key is required"),
  deviceId: z
    .string()
    .trim()
    .transform((val: string) => (val.length > 0 ? val : null)),
});
