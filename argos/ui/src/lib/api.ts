let token = "";

export function initTokenFromLocation(): void {
  const fromUrl = new URLSearchParams(location.search).get("token");
  const stored = localStorage.getItem("argos_token");
  token = fromUrl || stored || "";
  if (token) localStorage.setItem("argos_token", token);
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const sep = path.includes("?") ? "&" : "?";
  const url = token ? `${path}${sep}token=${encodeURIComponent(token)}` : path;
  const headers: Record<string, string> = {};
  let body: string | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  const res = await fetch(url, { method: options.method ?? "GET", headers, body });
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* sin cuerpo */
  }
  if (!res.ok) {
    const detail = data as { detail?: string; error?: string } | null;
    throw new Error(detail?.detail || detail?.error || `HTTP ${res.status}`);
  }
  return data as T;
}

export function fileUrl(runName: string, path: string): string {
  const base = `/api/runs/${encodeURIComponent(runName)}/file/${path}`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}
