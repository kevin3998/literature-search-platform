import React, { useEffect } from "react";
import { FileText } from "lucide-react";
import { useAppStore } from "../store/useAppStore";

function formatSize(kb) {
  if (kb == null) return "";
  if (kb > 1024) return `${(kb / 1024).toFixed(1)} MB`;
  return `${kb.toFixed(0)} KB`;
}

function formatDate(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleDateString("zh-CN");
}

export default function LibraryBrowser() {
  const library = useAppStore((s) => s.library);
  const libraryLoaded = useAppStore((s) => s.libraryLoaded);
  const loadLibrary = useAppStore((s) => s.loadLibrary);

  useEffect(() => {
    if (!libraryLoaded) loadLibrary();
  }, [libraryLoaded, loadLibrary]);

  return (
    <div className="space-y-1.5">
      <p className="text-[11.5px] text-ink-500 mb-2">
        共 {library.length} 个文件 · 由后端 <code className="font-mono">LIBRARY_DIR</code> 配置指向
      </p>
      {library.map((f) => (
        <div
          key={f.path}
          className="flex items-center gap-2.5 rounded-md border border-line bg-paper-0 px-3 py-2.5"
        >
          <FileText size={15} className="text-ink-500 flex-shrink-0" />
          <span className="flex-1 min-w-0 text-[12.5px] text-ink-800 truncate">{f.name}</span>
          <span className="font-mono text-[10.5px] text-ink-500 flex-shrink-0">
            {formatSize(f.size_kb)} · {formatDate(f.modified)}
          </span>
        </div>
      ))}
    </div>
  );
}
