import { EngineConfig, EngineType } from "./api";

const SETTINGS_KEY = "tpdf-settings";

export interface Settings {
  engineType: EngineType;
  apiKeys: Partial<Record<EngineType, string>>;
  models: Partial<Record<EngineType, string>>;
  baseUrl: string;
  ollamaHost: string;
  langOut: string;
}

export const defaultSettings: Settings = {
  engineType: "codex",
  apiKeys: {},
  models: {},
  baseUrl: "",
  ollamaHost: "http://127.0.0.1:11434",
  langOut: "zh",
};

export const ENGINE_LABELS: Record<EngineType, string> = {
  deepseek: "DeepSeek",
  openai_compatible: "OpenAI 兼容端点",
  claude: "Claude",
  gemini: "Gemini",
  ollama: "本地模型（Ollama）",
  codex: "Codex 账号额度",
};

export function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) return { ...defaultSettings, ...JSON.parse(raw) };
  } catch {}
  return defaultSettings;
}

export function saveSettings(settings: Settings) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

export function engineConfigFrom(settings: Settings): EngineConfig {
  const t = settings.engineType;
  return {
    type: t,
    api_key: t === "codex" || t === "ollama" ? "" : settings.apiKeys[t] ?? "",
    model: settings.models[t] || undefined,
    base_url: t === "openai_compatible" ? settings.baseUrl : undefined,
    host: t === "ollama" ? settings.ollamaHost : undefined,
  };
}
