import { AgentKind } from "@/lib/types";
import { AgentStatusEnum } from "./enums";

export interface ShoppingAgent {
  id: string;
  name: string;
  status: AgentStatusEnum;
  created_at: string;
  public_key: string;
  managed: boolean;
  kind: AgentKind;
  device_id: string | null;
}

export interface ConnectAgentPayload {
  name: string;
  public_key: string;
  device_id: string | null;
}

