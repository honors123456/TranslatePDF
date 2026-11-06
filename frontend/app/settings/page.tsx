"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { DEFAULT_MODELS, EngineType, testConnection } from "@/lib/api";
import { catalogKey, fetchCatalog, isCatalogFresh, ModelCatalog, readCatalog } from "@/lib/model-catalog";
import {
  ENGINE_LABELS,
  Settings,
  defaultSettings,
  engineConfigFrom,
  loadSettings,
  saveSettings,
} from "@/lib/settings";

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [catalogNotice, setCatalogNotice] = useState("");
  const [refresh, setRefresh] = useState(0);
  const appliedRefresh = useRef(0);
  const [checking, setChecking] = useState(false);
  const t = settings.engineType;
  const apiKey = settings.apiKeys[t] ?? "";
  const baseUrl = settings.baseUrl;
  const host = settings.ollamaHost;
  const selectedModel = settings.models[t] || DEFAULT_MODELS[t];
  const availableModels = catalog?.models ?? [];
  const modelAvailable = availableModels.includes(selectedModel);

  useEffect(() => {
    setSettings(loadSettings());
    setLoaded(true);
  }, []);
  useEffect(() => {
    if (loaded) saveSettings(settings);
  }, [settings, loaded]);

  useEffect(() => {
    if (!loaded) return;
    const controller = new AbortController();
    const engine = {
      type: t, api_key: t === "codex" || t === "ollama" ? "" : apiKey,
      base_url: t === "openai_compatible" ? baseUrl : undefined,
      host: t === "ollama" ? host : undefined,
    };
    let forceRefresh = refresh !== appliedRefresh.current;
    appliedRefresh.current = refresh;
    let running = false;
    async function update() {
      if (running || controller.signal.aborted) return;
      if (t !== "codex" && t !== "ollama" && !apiKey) {
        setCatalogNotice("填写 API Key 后自动获取模型列表。");
        return;
      }
      if (t === "openai_compatible" && !baseUrl) {
        setCatalogNotice("填写 Base URL 后自动获取模型列表。");
        return;
      }
      running = true;
      try {
        const key = await catalogKey(engine);
        if (controller.signal.aborted) return;
        const cached = readCatalog(key);
        setCatalog(cached);
        const force = forceRefresh;
        forceRefresh = false;
        if (!force && cached && isCatalogFresh(cached)) return;
        setChecking(true);
        setCatalogNotice("正在刷新模型列表…");
        const next = await fetchCatalog(engine, controller.signal);
        if (controller.signal.aborted) return;
        setCatalog(next);
        setCatalogNotice("");
        try { localStorage.setItem(key, JSON.stringify(next)); } catch {}
      } catch (error) {
        if (!controller.signal.aborted) setCatalogNotice(
          `刷新失败，保留已有列表，请检查配置后重试。${error instanceof Error ? error.message : ""}`,
        );
      } finally {
        running = false;
        if (!controller.signal.aborted) setChecking(false);
      }
    }
    const reset = setTimeout(() => {
      setCatalog(null);
      setCatalogNotice("");
      setChecking(false);
    }, 0);
    const timeout = setTimeout(update, 600);
    const interval = setInterval(update, 60 * 1000);
    return () => { controller.abort(); clearTimeout(reset); clearTimeout(timeout); clearInterval(interval); };
  }, [loaded, t, apiKey, baseUrl, host, refresh]);

  async function handleTest() {
    if (!modelAvailable) return setNotice("请先从模型列表中选择可用模型。");
    const engine = engineConfigFrom(settings);
    if (engine.type !== "ollama" && engine.type !== "codex" && !engine.api_key) {
      return setNotice("请先填写 API Key");
    }
    setBusy(true);
    setNotice("测试中…");
    try {
      const result = await testConnection(engine);
      setNotice(
        result.ok
          ? `连通性正常（${result.model}）`
          : `连接失败${result.status ? `（HTTP ${result.status}）` : ""}：${result.detail ?? "未知错误"}`,
      );
    } catch (err) {
      setNotice(`测试失败：${err instanceof Error ? err.message : err}`);
    } finally {
      setBusy(false);
    }
  }


  return (
    <main className="mx-auto max-w-2xl px-4 py-10 space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">翻译引擎设置</h1>
        <Link href="/" className="text-sm text-blue-600 hover:underline">
          ← 返回翻译
        </Link>
      </header>

      <section className="rounded-xl border border-gray-200 dark:border-gray-700 p-5 space-y-4">
        <div className="flex flex-wrap gap-2">
          {(Object.keys(ENGINE_LABELS) as EngineType[]).map((key) => (
            <button
              key={key}
              onClick={() => setSettings((s) => ({ ...s, engineType: key }))}
              className={`px-3 py-1.5 rounded-full text-sm border transition ${
                t === key
                  ? "bg-blue-600 text-white border-blue-600"
                  : "border-gray-300 dark:border-gray-600 hover:border-blue-400"
              }`}
            >
              {ENGINE_LABELS[key]}
            </button>
          ))}
        </div>

        {t !== "ollama" && t !== "codex" && (
          <label className="block text-sm">
            <span className="text-gray-600 dark:text-gray-300">API Key</span>
            <input
              type="password"
              value={settings.apiKeys[t] ?? ""}
              onChange={(e) =>
                setSettings((s) => ({
                  ...s,
                  apiKeys: { ...s.apiKeys, [t]: e.target.value },
                }))
              }
              placeholder="sk-..."
              className="mt-1 w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-transparent px-3 py-2"
            />
          </label>
        )}

        {t === "codex" && (
          <p className="text-sm text-gray-500">
            使用后端所在电脑的 Codex 登录账号额度，无需 API Key。请先用运行后端的同一用户执行 codex login。默认模型为 gpt-6-luna，连接测试会消耗少量账号额度。PDF 文本会发送给 Codex 服务。
          </p>
        )}

        <label className="block text-sm">
          <span className="text-gray-600 dark:text-gray-300">模型</span>
          <select
            value={modelAvailable ? selectedModel : ""}
            disabled={availableModels.length === 0}
            aria-describedby="model-list-status"
            onChange={(e) =>
              setSettings((s) => ({
                ...s,
                models: { ...s.models, [t]: e.target.value },
              }))
            }
            className="mt-1 w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-transparent px-3 py-2 disabled:opacity-50"
          >
            <option value="" disabled>
              {checking && availableModels.length === 0 ? "正在加载模型列表…"
                : availableModels.length === 0 ? "暂无模型，请先获取模型列表" : "请选择模型"}
            </option>
            {availableModels.map((model) => <option key={model} value={model}>{model}</option>)}
          </select>
        </label>

        <div id="model-list-status" className="text-xs text-gray-500 space-y-2">
          <p>模型列表每 7 天自动刷新；未打开设置页时，下次打开补刷。请从列表中选择模型。</p>
          {catalog && selectedModel && !modelAvailable && <p role="status">原模型 {selectedModel} 不在当前列表中，请重新选择。</p>}
          {catalog && <p>列表更新时间：{new Date(catalog.updatedAt).toLocaleString("zh-CN")}，共 {catalog.models.length} 个模型。模型权限及翻译兼容性请通过连接测试确认。</p>}
          {catalogNotice && <p role="status">{catalogNotice}</p>}
          <button type="button" disabled={checking} onClick={() => setRefresh((v) => v + 1)}
            className="text-blue-600 hover:underline disabled:opacity-50">立即刷新模型列表</button>
        </div>

        {t === "openai_compatible" && (
          <label className="block text-sm">
            <span className="text-gray-600 dark:text-gray-300">Base URL</span>
            <input
              value={settings.baseUrl}
              onChange={(e) =>
                setSettings((s) => ({ ...s, baseUrl: e.target.value }))
              }
              placeholder="https://api.example.com/v1"
              className="mt-1 w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-transparent px-3 py-2"
            />
          </label>
        )}

        {t === "ollama" && (
          <div className="space-y-1">
            <label className="block text-sm">
              <span className="text-gray-600 dark:text-gray-300">Ollama 地址</span>
              <input
                value={settings.ollamaHost}
                onChange={(e) =>
                  setSettings((s) => ({ ...s, ollamaHost: e.target.value }))
                }
                placeholder="http://127.0.0.1:11434"
                className="mt-1 w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-transparent px-3 py-2"
              />
            </label>
            <p className="text-xs text-gray-500">
              使用前需启动 Ollama，并执行 ollama pull translategemma:12b 下载默认模型。
            </p>
          </div>
        )}

        <label className="block text-sm">
          <span className="text-gray-600 dark:text-gray-300">目标语言</span>
          <select
            value={settings.langOut}
            onChange={(e) =>
              setSettings((s) => ({ ...s, langOut: e.target.value }))
            }
            className="mt-1 w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-transparent px-3 py-2"
          >
            <option value="zh">中文</option>
            <option value="en">英文</option>
            <option value="ja">日文</option>
          </select>
        </label>

        <div className="flex items-center gap-3 pt-1">
          <button
            onClick={handleTest}
            disabled={busy || !modelAvailable}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            测试连通性
          </button>
          {notice && <span className="text-sm text-amber-600">{notice}</span>}
        </div>
      </section>

      <p className="text-xs text-gray-500">
        设置自动保存。API Key 只存浏览器本地，随任务传给后端内存使用，不落盘、不写日志；Codex 和 Ollama 模式不需要 API Key。
      </p>
    </main>
  );
}
