export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type EngineType = "deepseek" | "openai_compatible" | "claude" | "gemini";

export interface EngineConfig {
  type: EngineType;
  api_key: string;
  model?: string;
  base_url?: string;
}

export interface TaskSnapshot {
  id: string;
  filename: string;
  status: "running" | "done" | "error" | "cancelled";
  stage: string;
  overall_progress: number;
  error: string | null;
  has_mono: boolean;
  has_dual: boolean;
  created_at: number;
  finished_at: number | null;
}

export const DEFAULT_MODELS: Record<EngineType, string> = {
  deepseek: "deepseek-chat",
  claude: "claude-opus-4-8",
  gemini: "gemini-2.5-flash",
  openai_compatible: "",
};

export async function createTask(
  file: File,
  engine: EngineConfig,
  langIn: string,
  langOut: string,
  pages: string,
): Promise<TaskSnapshot> {
  const form = new FormData();
  form.append("file", file);
  form.append("engine", JSON.stringify(engine));
  form.append("lang_in", langIn);
  form.append("lang_out", langOut);
  if (pages.trim()) form.append("pages", pages.trim());
  const resp = await fetch(`${API_BASE}/api/tasks`, { method: "POST", body: form });
  if (!resp.ok) throw new Error((await resp.json()).detail ?? resp.statusText);
  return resp.json();
}

export async function cancelTask(id: string): Promise<void> {
  await fetch(`${API_BASE}/api/tasks/${id}/cancel`, { method: "POST" });
}

export async function testConnection(engine: EngineConfig): Promise<{
  ok: boolean;
  model?: string;
  status?: number;
  detail?: string;
}> {
  const resp = await fetch(`${API_BASE}/api/test-connection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(engine),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail ?? resp.statusText);
  return resp.json();
}

export function downloadUrl(id: string, kind: "dual" | "mono", inline = false) {
  return `${API_BASE}/api/tasks/${id}/download?kind=${kind}${inline ? "&inline=true" : ""}`;
}

export function eventsUrl(id: string) {
  return `${API_BASE}/api/tasks/${id}/events`;
}
