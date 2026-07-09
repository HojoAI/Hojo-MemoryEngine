import { refreshApiClient } from "./api";

/** Persist Memory Engine API credentials in localStorage and refresh axios client. */
export function applyCredentials(tenantId: string, orgId: string, apiKey: string): void {
  localStorage.setItem("MOS_TENANT_ID", tenantId);
  localStorage.setItem("MOS_ORG_ID", orgId);
  localStorage.setItem("MOS_API_KEY", apiKey);
  refreshApiClient();
}

export function getAdminSecret(): string {
  return sessionStorage.getItem("MOS_ADMIN_SECRET") || "";
}

export function setAdminSecret(secret: string): void {
  if (secret) {
    sessionStorage.setItem("MOS_ADMIN_SECRET", secret);
  } else {
    sessionStorage.removeItem("MOS_ADMIN_SECRET");
  }
}
