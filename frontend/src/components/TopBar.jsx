import React from "react";
import { useAppStore } from "../store/useAppStore";

export default function TopBar() {
  const modules = useAppStore((s) => s.modules);
  const activeModuleId = useAppStore((s) => s.activeModuleId);
  const homeOpen = useAppStore((s) => s.homeOpen);
  const workflowOpen = useAppStore((s) => s.workflowOpen);
  const structuredExtractionOpen = useAppStore((s) => s.structuredExtractionOpen);
  const settingsOpen = useAppStore((s) => s.settings.open);
  const session = useAppStore((s) => {
    const sid = s.activeSessionByModule[s.activeModuleId];
    return s.sessionsById[sid];
  });
  const mod = modules.find((m) => m.id === activeModuleId);
  let title = mod?.name || "文献检索";
  let subtitle = session?.title || "实时证据问答";
  if (homeOpen) {
    title = "首页";
    subtitle = "索引健康";
  } else if (workflowOpen) {
    title = "研究工作流";
    subtitle = "受控研究任务引擎";
  } else if (structuredExtractionOpen) {
    title = "数据抽取";
    subtitle = "材料结构化数据工作台";
  } else if (settingsOpen) {
    title = "设置";
    subtitle = "平台与模型";
  }

  return (
    <div className="h-14 flex-shrink-0 flex items-center justify-between px-6 border-b border-line bg-paper-0">
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="font-serif text-[15px] text-ink-900 truncate">{title}</span>
        <span className="text-line">/</span>
        <span className="text-[13px] text-ink-500 truncate">{subtitle}</span>
      </div>
      <div className="flex items-center gap-2 text-[12px] text-ink-500 flex-shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-teal" />
        本地文献库已连接
      </div>
    </div>
  );
}
