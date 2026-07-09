"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  TaskSnapshot,
  cancelTask,
  createTask,
  downloadUrl,
  eventsUrl,
} from "@/lib/api";
import {
  Settings,
  defaultSettings,
  engineConfigFrom,
  loadSettings,
} from "@/lib/settings";

const STATUS_LABELS: Record<TaskSnapshot["status"], string> = {
  running: "翻译中",
  done: "完成",
  error: "失败",
  cancelled: "已取消",
};

export default function Home() {
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [tasks, setTasks] = useState<TaskSnapshot[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [pages, setPages] = useState("");
  const [notice, setNotice] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sourcesRef = useRef<Map<string, EventSource>>(new Map());
  // 原文预览用浏览器本地 objectURL，不经后端；仅本次会话有效
  const originalUrlsRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    setSettings(loadSettings());
    const sources = sourcesRef.current;
    const urls = originalUrlsRef.current;
    return () => {
      sources.forEach((s) => s.close());
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, []);

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

  const startTranslation = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        return setNotice("只支持 PDF 文件");
      }
      const engine = engineConfigFrom(loadSettings());
      if (!engine.api_key) {
        return setNotice("尚未配置 API Key，请先到「设置」填写");
      }
      setNotice("");
      try {
        const task = await createTask(
          file,
          engine,
          "en",
          loadSettings().langOut,
          pages,
        );
        originalUrlsRef.current.set(task.id, URL.createObjectURL(file));
        setTasks((prev) => [task, ...prev]);
        setCurrentId(task.id);
        watchTask(task.id);
      } catch (err) {
        setNotice(`提交失败：${err instanceof Error ? err.message : err}`);
      }
    },
    [pages, watchTask],
  );

  const current = tasks.find((t) => t.id === currentId) ?? null;

  // ---------- 全屏双栏预览（翻译中/完成） ----------
  if (current) {
    const originalUrl = originalUrlsRef.current.get(current.id);
    return (
      <div className="flex flex-col h-screen">
        <header className="flex items-center gap-4 px-4 py-2 border-b border-gray-200 dark:border-gray-700 text-sm">
          <button
            onClick={() => setCurrentId(null)}
            className="text-blue-600 hover:underline shrink-0"
          >
            ← 新任务
          </button>
          <span className="truncate font-medium">{current.filename}</span>
          <span
            className={`shrink-0 text-xs px-2 py-0.5 rounded-full ${
              current.status === "done"
                ? "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300"
                : current.status === "running"
                  ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
                  : "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
            }`}
          >
            {STATUS_LABELS[current.status]}
          </span>
          {current.status === "running" && (
            <div className="flex items-center gap-2 flex-1 min-w-0">
              <div className="h-1.5 flex-1 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                <div
                  className="h-full bg-blue-500 transition-all"
                  style={{ width: `${current.overall_progress}%` }}
                />
              </div>
              <span className="shrink-0 text-xs text-gray-500">
                {current.stage} {current.overall_progress}%
              </span>
              <button
                onClick={() => cancelTask(current.id)}
                className="shrink-0 text-red-500 hover:underline"
              >
                取消
              </button>
            </div>
          )}
          <div className="ml-auto flex gap-3 shrink-0">
            {current.has_dual && (
              <a
                href={downloadUrl(current.id, "dual")}
                className="text-blue-600 hover:underline"
              >
                下载双语版
              </a>
            )}
            {current.has_mono && (
              <a
                href={downloadUrl(current.id, "mono")}
                className="text-blue-600 hover:underline"
              >
                下载纯译文
              </a>
            )}
          </div>
        </header>

        <div className="flex-1 grid grid-cols-2 min-h-0">
          {/* 左栏：原文 */}
          <div className="border-r border-gray-200 dark:border-gray-700 min-h-0">
            {originalUrl ? (
              <iframe
                src={originalUrl}
                className="w-full h-full"
                title="original"
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-gray-400">
                原文预览不可用（页面刷新后丢失，重新上传即可）
              </div>
            )}
          </div>
          {/* 右栏：译文（翻译中显示进度，完成后显示纯译文 PDF） */}
          <div className="min-h-0">
            {current.status === "done" && current.has_mono ? (
              <iframe
                src={downloadUrl(current.id, "mono", true)}
                className="w-full h-full"
                title="translated"
              />
            ) : current.status === "running" ? (
              <div className="flex h-full flex-col items-center justify-center gap-4 px-10">
                <div className="w-full max-w-md h-2 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                  <div
                    className="h-full bg-blue-500 transition-all"
                    style={{ width: `${current.overall_progress}%` }}
                  />
                </div>
                <p className="text-sm text-gray-500">
                  {current.stage || "准备中"} · {current.overall_progress}%
                </p>
                <p className="text-xs text-gray-400">
                  翻译完成后此处自动显示译文
                </p>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center px-10">
                <p className="text-sm text-red-500 break-all">
                  {current.error ?? `任务${STATUS_LABELS[current.status]}`}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ---------- 全屏上传/拖拽（空闲） ----------
  return (
    <div
      className={`flex flex-col h-screen ${dragging ? "bg-blue-50 dark:bg-gray-900" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const file = e.dataTransfer.files?.[0];
        if (file) startTranslation(file);
      }}
    >
      <header className="flex items-center justify-between px-6 py-3 border-b border-gray-200 dark:border-gray-700">
        <h1 className="text-lg font-bold">TranslationPDF</h1>
        <Link href="/settings" className="text-sm text-blue-600 hover:underline">
          设置
        </Link>
      </header>

      <main className="flex-1 flex flex-col items-center justify-center gap-6 px-6">
        <div
          onClick={() => fileInputRef.current?.click()}
          className={`w-full max-w-2xl cursor-pointer rounded-2xl border-2 border-dashed p-16 text-center transition ${
            dragging
              ? "border-blue-500 bg-blue-50 dark:bg-gray-800"
              : "border-gray-300 dark:border-gray-600 hover:border-blue-400"
          }`}
        >
          <p className="text-xl font-medium">
            拖拽 PDF 到页面任意位置，或点击选择文件
          </p>
          <p className="mt-2 text-sm text-gray-500">
            上传即开始翻译 · 引擎 {settings.engineType} · 译为{" "}
            {settings.langOut === "zh" ? "中文" : settings.langOut}
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) startTranslation(file);
            }}
          />
        </div>

        <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
          页码范围（可选）
          <input
            value={pages}
            onChange={(e) => setPages(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            placeholder="如 1-5，留空全文"
            className="w-40 rounded-lg border border-gray-300 dark:border-gray-600 bg-transparent px-3 py-1.5"
          />
        </label>

        {notice && <p className="text-sm text-amber-600">{notice}</p>}

        {tasks.length > 0 && (
          <div className="w-full max-w-2xl space-y-1">
            <h2 className="text-sm font-medium text-gray-500">本次会话任务</h2>
            {tasks.map((task) => (
              <button
                key={task.id}
                onClick={() => setCurrentId(task.id)}
                className="flex w-full items-center justify-between rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2 text-sm hover:border-blue-400"
              >
                <span className="truncate">{task.filename}</span>
                <span className="shrink-0 text-xs text-gray-500">
                  {STATUS_LABELS[task.status]}
                  {task.status === "running" && ` ${task.overall_progress}%`}
                </span>
              </button>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
