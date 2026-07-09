"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { DEFAULT_MODELS, EngineType, testConnection } from "@/lib/api";
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

  useEffect(() => {
    setSettings(loadSettings());
    setLoaded(true);
  }, []);
  useEffect(() => {
    if (loaded) saveSettings(settings);
  }, [settings, loaded]);

  async function handleTest() {
    const engine = engineConfigFrom(settings);
    if (!engine.api_key) return setNotice("请先填写 API Key");
    setBusy(true);
    setNotice("测试中…");
    try {
      const result = await testConnection(engine);
      setNotice(
        result.ok
          ? `连通性正常（${result.model}）`
          : `连接失败（HTTP ${result.status ?? "?"}）：${result.detail ?? ""}`,
      );
    } catch (err) {
      setNotice(`测试失败：${err instanceof Error ? err.message : err}`);
    } finally {
      setBusy(false);
    }
  }

  const t = settings.engineType;

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

        <label className="block text-sm">
          <span className="text-gray-600 dark:text-gray-300">模型</span>
          <input
            value={settings.models[t] ?? ""}
            onChange={(e) =>
              setSettings((s) => ({
                ...s,
                models: { ...s.models, [t]: e.target.value },
              }))
            }
            placeholder={DEFAULT_MODELS[t] || "必填"}
            className="mt-1 w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-transparent px-3 py-2"
          />
        </label>

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
            disabled={busy}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            测试连通性
          </button>
          {notice && <span className="text-sm text-amber-600">{notice}</span>}
        </div>
      </section>

      <p className="text-xs text-gray-500">
        设置自动保存。API Key 只存浏览器本地，随任务传给后端内存使用，不落盘、不写日志。
      </p>
    </main>
  );
}
