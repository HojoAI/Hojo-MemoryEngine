declare global {
  interface Window {
    __RUNTIME_CONFIG__?: Partial<Record<RuntimeConfigKey, string>>;
  }
}

type RuntimeConfigKey = "VITE_API_BASE_URL" | "VITE_APISIX_URL";

const BUILD_TIME: Record<RuntimeConfigKey, string | undefined> = {
  VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL,
  VITE_APISIX_URL: import.meta.env.VITE_APISIX_URL,
};

/** Read config injected at container start (K8s env) or Vite build-time env (local dev). */
export function runtimeEnv(key: RuntimeConfigKey, fallback = ""): string {
  const fromRuntime = window.__RUNTIME_CONFIG__?.[key];
  if (fromRuntime) {
    return fromRuntime;
  }
  return BUILD_TIME[key] || fallback;
}

export function apiBaseURL(fallback = "http://127.0.0.1:6030"): string {
  return runtimeEnv("VITE_API_BASE_URL", fallback) || fallback;
}

export function gatewayURL(fallback = "http://127.0.0.1:6030"): string {
  return runtimeEnv("VITE_APISIX_URL") || runtimeEnv("VITE_API_BASE_URL", fallback) || fallback;
}
