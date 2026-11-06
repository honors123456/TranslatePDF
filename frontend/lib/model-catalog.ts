import { API_BASE, EngineConfig } from "./api";

export const MODEL_REFRESH_MS = 7 * 24 * 60 * 60 * 1000;

export interface ModelCatalog {
  models: string[];
  updatedAt: number;
}

export function isCatalogFresh(catalog: ModelCatalog, now = Date.now()): boolean {
  const age = now - catalog.updatedAt;
  return age >= 0 && age < MODEL_REFRESH_MS;
}

export async function catalogKey(engine: EngineConfig): Promise<string> {
  const identity = JSON.stringify([engine.type, engine.base_url, engine.host, engine.api_key]);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(identity));
  return `tpdf-models-${Array.from(new Uint8Array(digest), (v) => v.toString(16).padStart(2, "0")).join("")}`;
}

export function readCatalog(key: string): ModelCatalog | null {
  try {
    const cached = JSON.parse(localStorage.getItem(key) ?? "null");
    if (cached && Array.isArray(cached.models) && cached.models.every((m: unknown) => typeof m === "string") &&
        typeof cached.updatedAt === "number" && Number.isFinite(cached.updatedAt)) return cached;
  } catch {}
  return null;
}

export async function fetchCatalog(engine: EngineConfig, signal: AbortSignal): Promise<ModelCatalog> {
  const response = await fetch(`${API_BASE}/api/models`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(engine), signal,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail ?? "模型列表刷新失败");
  return { models: result.models, updatedAt: Date.now() };
}
