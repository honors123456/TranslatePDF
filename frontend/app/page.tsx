"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  DEFAULT_MODELS,
  EngineConfig,
  EngineType,
  TaskSnapshot,
  cancelTask,
  createTask,
  downloadUrl,
  eventsUrl,
  testConnection,
} from "@/lib/api";

const SETTINGS_KEY = "tpdf-settings";

interface Settings {
  engineType: EngineType;
  apiKeys: Partial<Record<EngineType, string>>;
  models: Partial<Record<EngineType, string>>;
  baseUrl: string;
  langOut: string;
}

const defaultSettings: Settings = {
  engineType: "deepseek",
  apiKeys: {},
  models: {},
  baseUrl: "",
  langOut: "zh",
};

const ENGINE_LABELS: Record<EngineType, string> = {
  deepseek: "DeepSeek",
  openai_compatible: "OpenAI 兼容端点",
  claude: "Claude",
  gemini: "Gemini",
};

const STATUS_LABELS: Record<TaskSnapshot["status"], string> = {
  running: "翻译中",
  done: "完成",
  error: "失败",
  cancelled: "已取消",
};

export default function Home() {
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [loaded, setLoaded] = useState(false);
  const [tasks, setTasks] = useState<TaskSnapshot[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [pages, setPages] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [previewId, setPreviewId] = useState<string | null>(null);
  const sourcesRef = useRef<Map<string, EventSource>>(new Map());

  // 设置持久化：只存浏览器 localStorage（BYOK）
  useEffect(() => {
    try {
      const raw = localStorage.getItem(SETTINGS_KEY);
      if (raw) setSettings({ ...defaultSettings, ...JSON.parse(raw) });
    } catch {}
    setLoaded(true);
  }, []);
  useEffect(() => {
    if (loaded) localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  }, [settings, loaded]);

  useEffect(() => {
    const sources = sourcesRef.current;
    return () => sources.forEach((s) => s.close());
  }, []);

  const engineConfig = useCallback((): EngineConfig => {
    const t = settings.engineType;
    return {
      type: t,
      api_key: settings.apiKeys[t] ?? "",
      model: settings.models[t] || undefined,
      base_url: t === "openai_compatible" ? settings.baseUrl : undefined,
    };
  }, [settings]);

  const watchTask = useCallback((id: string) => {
    const source = new EventSource(eventsUrl(id));
    sourcesRef.current.set(id, source);
    source.onmessage = (msg) => {
      const snapshot: TaskSnapshot = JSON.parse(msg.data);
      setTasks((prev) => prev.map((t) => (t.id === id ? snapshot : t)));
      if (snapshot.status !== "running") {
        source.close();
        sourcesRef.current.delete(id);
      }
    };
    source.onerror = () => {
      source.close();
      sourcesRef.current.delete(id);
    };
  }, []);

  async function handleSubmit() {
    if (!file) return setNotice("请先选择 PDF 文件");
    const engine = engineConfig();
    if (!engine.api_key) return setNotice("请先填写 API Key");
    setBusy(true);
    setNotice("");
    try {
      const task = await createTask(file, engine, "en", settings.langOut, pages);
      setTasks((prev) => [task, ...prev]);
      watchTask(task.id);
      setFile(null);
    } catch (err) {
      setNotice(`提交失败：${err instanceof Error ? err.message : err}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleTest() {
    const engine = engineConfig();
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
    <main className="mx-auto max-w-3xl px-4 py-10 space-y-8">
      <header>
        <h1 className="text-2xl font-bold">TranslationPDF</h1>
        <p className="text-sm text-gray-500 mt-1">
          上传 PDF，用自己的 API Key 翻译，保留原排版，双语对照。
        </p>
      </header>

      {/* 引擎设置 */}
      <section className="rounded-xl border border-gray-200 dark:border-gray-700 p-5 space-y-4">
        <h2 className="font-semibold">翻译引擎</h2>
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
        <div className="grid gap-3 sm:grid-cols-2">
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
            <label className="block text-sm sm:col-span-2">
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
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleTest}
            disabled={busy}
            className="rounded-lg border border-gray-300 dark:border-gray-600 px-4 py-2 text-sm hover:border-blue-400 disabled:opacity-50"
          >
            测试连通性
          </button>
          <span className="text-xs text-gray-500">
            Key 只存浏览器本地，随任务传给后端内存使用，不落盘。
          </span>
        </div>
      </section>

      {/* 上传与提交 */}
      <section className="rounded-xl border border-gray-200 dark:border-gray-700 p-5 space-y-4">
        <h2 className="font-semibold">翻译任务</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block text-sm sm:col-span-2">
            <span className="text-gray-600 dark:text-gray-300">PDF 文件</span>
            <input
              type="file"
              accept=".pdf"
              key={file ? file.name : "empty"}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="mt-1 w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-blue-50 file:px-3 file:py-2 file:text-blue-700 dark:file:bg-gray-800 dark:file:text-blue-300"
            />
          </label>
          <label className="block text-sm">
            <span className="text-gray-600 dark:text-gray-300">
              页码范围（可选）
            </span>
            <input
              value={pages}
              onChange={(e) => setPages(e.target.value)}
              placeholder="如 1-5，留空全文"
              className="mt-1 w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-transparent px-3 py-2"
            />
          </label>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleSubmit}
            disabled={busy || !file}
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            开始翻译
          </button>
          <select
            value={settings.langOut}
            onChange={(e) =>
              setSettings((s) => ({ ...s, langOut: e.target.value }))
            }
            className="rounded-lg border border-gray-300 dark:border-gray-600 bg-transparent px-3 py-2 text-sm"
          >
            <option value="zh">译为中文</option>
            <option value="en">译为英文</option>
            <option value="ja">译为日文</option>
          </select>
        </div>
        {notice && <p className="text-sm text-amber-600">{notice}</p>}
      </section>

      {/* 任务列表 */}
      {tasks.length > 0 && (
        <section className="space-y-3">
          <h2 className="font-semibold">任务</h2>
          {tasks.map((task) => (
            <div
              key={task.id}
              className="rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium">
                  {task.filename}
                </span>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full ${
                    task.status === "done"
                      ? "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300"
                      : task.status === "running"
                        ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
                        : "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
                  }`}
                >
                  {STATUS_LABELS[task.status]}
                </span>
              </div>
              {task.status === "running" && (
                <>
                  <div className="h-2 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                    <div
                      className="h-full bg-blue-500 transition-all"
                      style={{ width: `${task.overall_progress}%` }}
                    />
                  </div>
                  <p className="text-xs text-gray-500">
                    {task.stage} · {task.overall_progress}%
                  </p>
                </>
              )}
              {task.error && (
                <p className="text-xs text-red-500 break-all">{task.error}</p>
              )}
              <div className="flex flex-wrap gap-2 text-sm">
                {task.status === "running" && (
                  <button
                    onClick={() => cancelTask(task.id)}
                    className="text-red-500 hover:underline"
                  >
                    取消
                  </button>
                )}
                {task.has_dual && (
                  <>
                    <button
                      onClick={() =>
                        setPreviewId(previewId === task.id ? null : task.id)
                      }
                      className="text-blue-600 hover:underline"
                    >
                      {previewId === task.id ? "收起预览" : "在线预览"}
                    </button>
                    <a
                      href={downloadUrl(task.id, "dual")}
                      className="text-blue-600 hover:underline"
                    >
                      下载双语版
                    </a>
                  </>
                )}
                {task.has_mono && (
                  <a
                    href={downloadUrl(task.id, "mono")}
                    className="text-blue-600 hover:underline"
                  >
                    下载纯译文
                  </a>
                )}
              </div>
              {previewId === task.id && task.has_dual && (
                <iframe
                  src={downloadUrl(task.id, "dual", true)}
                  className="w-full h-[75vh] rounded-lg border border-gray-200 dark:border-gray-700"
                  title={`preview-${task.id}`}
                />
              )}
            </div>
          ))}
        </section>
      )}
    </main>
  );
}
