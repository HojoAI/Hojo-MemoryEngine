import axios from "axios";

import { apiBaseURL, gatewayURL as resolveGatewayURL } from "./runtime-config";

const baseURL = apiBaseURL();
const gatewayURL = resolveGatewayURL(baseURL);

export function createApiClient() {
  const apiKey = localStorage.getItem("MOS_API_KEY") || "";
  const tenantId = localStorage.getItem("MOS_TENANT_ID") || "1";
  const orgId = localStorage.getItem("MOS_ORG_ID") || "1";
  const headers: Record<string, string> = {
    "X-Tenant-Id": tenantId,
    "X-Org-Id": orgId,
  };
  // Do not send Supabase UUID as X-User-Id — API expects int; user_id comes from API key.
  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
  }
  return axios.create({
    baseURL: `${gatewayURL}/api/v1`,
    headers,
  });
}

export let api = createApiClient();

/** Recreate axios client after credentials change. */
export function refreshApiClient() {
  api = createApiClient();
  return api;
}

export type ApiEnvelope<T> = { code: number; message: string; data: T };
