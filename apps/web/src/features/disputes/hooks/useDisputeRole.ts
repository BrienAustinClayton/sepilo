import { useMe } from "@/lib/useMe";
import { DisputeRoleEnum } from "../enums";

export function useDisputeRole() {
  const me = useMe();
  return {
    isLoadingRole: me === null,
    isManager: me?.role === DisputeRoleEnum.Manager,
  };
}
