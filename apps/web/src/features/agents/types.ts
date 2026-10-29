import { AgentStatusEnum } from "./enums";

export interface ShoppingAgent {
  id: string;
  name: string;
  status: AgentStatusEnum;
  created_at: string;
  public_key: string;
  managed: boolean;
  device_id: string | null;
}

export interface ConnectAgentPayload {
  name: string;
  public_key: string;
  device_id: string | null;
}

