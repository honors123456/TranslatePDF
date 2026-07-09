import { EngineConfig, EngineType } from "./api";

const SETTINGS_KEY = "tpdf-settings";

export interface Settings {
  engineType: EngineType;
  apiKeys: Partial<Record<EngineType, string>>;
  models: Partial<Record<EngineType, string>>;
  baseUrl: string;
  langOut: string;
}

export const defaultSettings: Settings = {
  engineType: "deepseek",
  apiKeys: {},
  models: {},
  baseUrl: "",
  langOut: "zh",
};

export const ENGINE_LABELS: Record<EngineType, string> = {
  deepseek: "DeepSeek",
  openai_compatible: "OpenAI 兼容端点",
  claude: "Claude",
  gemini: "Gemini",
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
    api_key: settings.apiKeys[t] ?? "",
    model: settings.models[t] || undefined,
    base_url: t === "openai_compatible" ? settings.baseUrl : undefined,
  };
}
