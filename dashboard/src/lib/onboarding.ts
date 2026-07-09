import axios from "axios";
import type { ApiEnvelope } from "./api";
import { gatewayURL } from "./runtime-config";

function onboardingHeaders(adminSecret?: string): Record<string, string> {
  const headers: Record<string, string> = {};
  const supabaseUserId = localStorage.getItem("MOS_SUPABASE_USER_ID");
  if (supabaseUserId) {
    headers["X-Supabase-User-Id"] = supabaseUserId;
  }
  if (adminSecret) {
    headers["X-Admin-Secret"] = adminSecret;
  }
  return headers;
}

const client = axios.create({
  baseURL: `${gatewayURL()}/api/v1`,
});

export type ApiKeySummary = {
  id: number;
  name: string;
  key_prefix: string;
  tenant_id: number;
  org_id: number;
  user_id: number;
  revoked_at?: string | null;
};

export type OnboardingProfile = {
  tenant_id: number;
  org_id: number;
  user_id: number;
  email: string;
  display_name?: string | null;
  tenant_code?: string | null;
  org_code?: string | null;
  api_keys: ApiKeySummary[];
};

export type ApiKeyIssue = {
  tenant_id: number;
  org_id: number;
  user_id: number;
  api_key_id: number;
  api_key: string;
  key_prefix: string;
};

export type TenantBootstrapResult = ApiKeyIssue;

export async function fetchOnboardingProfile(): Promise<OnboardingProfile> {
  const { data } = await client.get<ApiEnvelope<OnboardingProfile>>("/onboarding/me", {
    headers: onboardingHeaders(),
  });
  return data.data;
}

export async function applyApiKey(payload: {
  email: string;
  display_name?: string;
  name?: string;
}): Promise<ApiKeyIssue> {
  const { data } = await client.post<ApiEnvelope<ApiKeyIssue>>(
    "/onboarding/api-key/apply",
    {
      email: payload.email,
      display_name: payload.display_name,
      name: payload.name ?? "dashboard",
    },
    { headers: onboardingHeaders() },
  );
  return data.data;
}

export async function createTenant(
  body: {
    tenant_code: string;
    tenant_name: string;
    org_code: string;
    org_name: string;
    email: string;
    display_name?: string;
    api_key_name?: string;
    supabase_user_id?: string;
  },
  adminSecret: string,
): Promise<TenantBootstrapResult> {
  const { data } = await client.post<ApiEnvelope<TenantBootstrapResult>>(
    "/onboarding/tenant",
    body,
    { headers: onboardingHeaders(adminSecret) },
  );
  return data.data;
}

export async function listApiKeys(): Promise<ApiKeySummary[]> {
  const apiKey = localStorage.getItem("MOS_API_KEY") || "";
  const tenantId = localStorage.getItem("MOS_TENANT_ID") || "1";
  const orgId = localStorage.getItem("MOS_ORG_ID") || "1";
  const { data } = await client.get<ApiEnvelope<ApiKeySummary[]>>("/onboarding/api-keys", {
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "X-Tenant-Id": tenantId,
      "X-Org-Id": orgId,
    },
  });
  return data.data;
}

export async function createApiKey(name: string): Promise<ApiKeyIssue> {
  const apiKey = localStorage.getItem("MOS_API_KEY") || "";
  const tenantId = localStorage.getItem("MOS_TENANT_ID") || "1";
  const orgId = localStorage.getItem("MOS_ORG_ID") || "1";
  const { data } = await client.post<ApiEnvelope<ApiKeyIssue>>(
    "/onboarding/api-keys",
    { name },
    {
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "X-Tenant-Id": tenantId,
        "X-Org-Id": orgId,
      },
    },
  );
  return data.data;
}
