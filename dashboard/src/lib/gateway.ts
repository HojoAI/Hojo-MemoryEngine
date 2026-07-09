/**
 * API gateway root (no trailing slash, no /api/v1 suffix).
 * Production: set via pipeline build-arg VITE_API_BASE_URL (or optional VITE_APISIX_URL).
 * Local dev: omit env vars and use Vite proxy (/api -> 127.0.0.1:6030).
 */
export function resolveGatewayUrl(): string {
  const fromEnv = import.meta.env.VITE_APISIX_URL || import.meta.env.VITE_API_BASE_URL;
  if (typeof fromEnv === "string" && fromEnv.trim()) {
    return fromEnv.trim().replace(/\/$/, "");
  }
  if (import.meta.env.DEV) {
    return "";
  }
  throw new Error(
    "API gateway URL 未配置：请在镜像构建流水线中设置 build-arg VITE_API_BASE_URL",
  );
}

/** Axios baseURL for Memory Engine REST API (/api/v1). */
export function apiV1BaseUrl(): string {
  const root = resolveGatewayUrl();
  return root ? `${root}/api/v1` : "/api/v1";
}
