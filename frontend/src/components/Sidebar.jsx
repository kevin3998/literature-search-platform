import React, { useEffect } from "react";
import { Archive, LayoutDashboard, LibraryBig, MessageSquare, Pin, Plus, Settings, Star, TableProperties, Tag, Telescope, Trash2, Type } from "lucide-react";
import clsx from "clsx";
import { useAppStore } from "../store/useAppStore";

export default function Sidebar() {
  const activeModuleId = useAppStore((s) => s.activeModuleId);
  const homeOpen = useAppStore((s) => s.homeOpen);
  const workflowOpen = useAppStore((s) => s.workflowOpen);
  const structuredExtractionOpen = useAppStore((s) => s.structuredExtractionOpen);
  const settingsOpen = useAppStore((s) => s.settings.open);
  const openHome = useAppStore((s) => s.openHome);
  const openWorkflows = useAppStore((s) => s.openWorkflows);
  const openStructuredExtraction = useAppStore((s) => s.openStructuredExtraction);
  const sessionsById = useAppStore((s) => s.sessionsById);
  const sessionOrderByModule = useAppStore((s) => s.sessionOrderByModule);
  const activeSessionByModule = useAppStore((s) => s.activeSessionByModule);
  const selectModule = useAppStore((s) => s.selectModule);
  const newSession = useAppStore((s) => s.newSession);
  const selectSession = useAppStore((s) => s.selectSession);
  const favoriteSession = useAppStore((s) => s.favoriteSession);
  const pinSession = useAppStore((s) => s.pinSession);
  const archiveSession = useAppStore((s) => s.archiveSession);
  const deleteSession = useAppStore((s) => s.deleteSession);
  const tagSession = useAppStore((s) => s.tagSession);
  const updateActiveSessionMeta = useAppStore((s) => s.updateActiveSessionMeta);
  const updateSessionMeta = useAppStore((s) => s.updateSessionMeta);
  const sessionContextMenu = useAppStore((s) => s.sessionContextMenu);
  const openSessionContextMenu = useAppStore((s) => s.openSessionContextMenu);
  const closeSessionContextMenu = useAppStore((s) => s.closeSessionContextMenu);
  const openSettings = useAppStore((s) => s.openSettings);

  const sessionIds = sessionOrderByModule[activeModuleId] || [];
  const activeSessionId = activeSessionByModule[activeModuleId];
  const literatureOpen = activeModuleId === "literature_search" && !homeOpen && !workflowOpen && !structuredExtractionOpen && !settingsOpen;

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === "Escape") closeSessionContextMenu();
    };
    const onClick = () => closeSessionContextMenu();
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("click", onClick);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("click", onClick);
    };
  }, [closeSessionContextMenu]);

  return (
    <aside className="w-[68px] md:w-[256px] flex-shrink-0 bg-ink-900 text-paper-50 flex flex-col h-full">
      <div className="px-3 md:px-5 pt-6 pb-5 border-b border-white/10">
        <div className="md:hidden mx-auto flex h-8 w-8 items-center justify-center rounded-lg bg-white/10 font-serif text-[18px] text-amber">文</div>
        <div className="hidden md:block font-serif text-[19px] font-semibold leading-tight">文献智能体平台</div>
        <div className="hidden md:block font-mono text-[10px] tracking-[0.18em] text-white/40 mt-1 uppercase">
          本地文献研究平台
        </div>
      </div>

      <nav className="px-2 md:px-3 pt-4 space-y-1">
        <button
          onClick={() => {
            closeSessionContextMenu();
            openHome();
          }}
          title="首页 · 索引健康"
          className={clsx(
            "w-full flex items-start justify-center md:justify-start gap-0 md:gap-2.5 rounded-md px-0 md:px-3 py-2.5 text-left transition-colors",
            homeOpen && !settingsOpen ? "bg-white/10" : "hover:bg-white/5"
          )}
        >
          <LayoutDashboard size={17} className={clsx("mt-0.5 flex-shrink-0", homeOpen && !settingsOpen ? "text-amber" : "text-white/55")} />
          <span className="hidden md:block flex-1 min-w-0">
            <span className={clsx("text-[13.5px] font-medium", homeOpen && !settingsOpen ? "text-white" : "text-white/85")}>首页</span>
            <span className="block text-[11.5px] text-white/40 leading-snug mt-0.5">索引健康</span>
          </span>
        </button>
        <button
          onClick={() => {
            closeSessionContextMenu();
            selectModule("literature_search");
          }}
          title="文献检索 · 实时证据问答"
          className={clsx(
            "w-full flex items-start justify-center md:justify-start gap-0 md:gap-2.5 rounded-md px-0 md:px-3 py-2.5 text-left transition-colors",
            literatureOpen ? "bg-white/10" : "hover:bg-white/5"
          )}
        >
          <LibraryBig size={17} className={clsx("mt-0.5 flex-shrink-0", literatureOpen ? "text-amber" : "text-white/55")} />
          <span className="hidden md:block flex-1 min-w-0">
            <span className={clsx("text-[13.5px] font-medium", literatureOpen ? "text-white" : "text-white/85")}>文献检索</span>
            <span className="block text-[11.5px] text-white/40 leading-snug mt-0.5">实时证据问答</span>
          </span>
        </button>
        <button
          onClick={() => {
            closeSessionContextMenu();
            openWorkflows();
          }}
          title="研究工作流 · 受控任务引擎"
          className={clsx(
            "w-full flex items-start justify-center md:justify-start gap-0 md:gap-2.5 rounded-md px-0 md:px-3 py-2.5 text-left transition-colors",
            workflowOpen && !settingsOpen ? "bg-white/10" : "hover:bg-white/5"
          )}
        >
          <Telescope size={17} className={clsx("mt-0.5 flex-shrink-0", workflowOpen && !settingsOpen ? "text-amber" : "text-white/55")} />
          <span className="hidden md:block flex-1 min-w-0">
            <span className={clsx("text-[13.5px] font-medium", workflowOpen && !settingsOpen ? "text-white" : "text-white/85")}>研究工作流</span>
            <span className="block text-[11.5px] text-white/40 leading-snug mt-0.5">受控任务引擎</span>
          </span>
        </button>
        <button
          onClick={() => {
            closeSessionContextMenu();
            openStructuredExtraction();
          }}
          title="数据抽取 · 结构化材料数据"
          className={clsx(
            "w-full flex items-start justify-center md:justify-start gap-0 md:gap-2.5 rounded-md px-0 md:px-3 py-2.5 text-left transition-colors",
            structuredExtractionOpen && !settingsOpen ? "bg-white/10" : "hover:bg-white/5"
          )}
        >
          <TableProperties size={17} className={clsx("mt-0.5 flex-shrink-0", structuredExtractionOpen && !settingsOpen ? "text-amber" : "text-white/55")} />
          <span className="hidden md:block flex-1 min-w-0">
            <span className={clsx("text-[13.5px] font-medium", structuredExtractionOpen && !settingsOpen ? "text-white" : "text-white/85")}>数据抽取</span>
            <span className="block text-[11.5px] text-white/40 leading-snug mt-0.5">结构化材料数据</span>
          </span>
        </button>
        <button
          onClick={() => {
            closeSessionContextMenu();
            openSettings();
          }}
          title="设置 · 平台与模型"
          className={clsx(
            "w-full flex items-start justify-center md:justify-start gap-0 md:gap-2.5 rounded-md px-0 md:px-3 py-2.5 text-left transition-colors",
            settingsOpen ? "bg-white/10" : "hover:bg-white/5"
          )}
        >
          <Settings size={17} className={clsx("mt-0.5 flex-shrink-0", settingsOpen ? "text-amber" : "text-white/55")} />
          <span className="hidden md:block flex-1 min-w-0">
            <span className={clsx("text-[13.5px] font-medium", settingsOpen ? "text-white" : "text-white/85")}>设置</span>
            <span className="block text-[11.5px] text-white/40 leading-snug mt-0.5">平台与模型</span>
          </span>
        </button>
      </nav>

      {literatureOpen && (
        <div className="hidden md:flex items-center justify-between px-5 pt-6 pb-2">
          <span className="font-mono text-[10px] tracking-[0.14em] text-white/35 uppercase">对话记录</span>
          <button
            onClick={() => newSession("literature_search")}
            className="text-white/45 hover:text-amber transition-colors"
            title="新建对话"
          >
            <Plus size={15} />
          </button>
        </div>
      )}

      {literatureOpen && activeSessionId && sessionsById[activeSessionId] && (
        <div className="hidden md:block px-3 pb-2">
          <input
            value={sessionsById[activeSessionId].title || ""}
            onChange={(e) => updateActiveSessionMeta({ title: e.target.value || "新对话" })}
            className="w-full rounded-md bg-white/5 border border-white/10 px-2 py-1.5 text-[12px] text-white/80 outline-none focus:border-amber"
            title="重命名当前会话"
          />
        </div>
      )}

      <div className="hidden md:block flex-1 overflow-y-auto px-3 pb-4 space-y-0.5" onScroll={closeSessionContextMenu}>
        {literatureOpen && sessionIds.map((sid) => {
          const s = sessionsById[sid];
          if (!s) return null;
          const active = sid === activeSessionId;
          return (
            <button
              key={sid}
              onClick={() => selectSession(activeModuleId, sid)}
              onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
                openSessionContextMenu(sid, e.clientX, e.clientY);
              }}
              className={clsx(
                "w-full flex items-center gap-2 rounded-md px-3 py-2 text-left text-[12.5px] transition-colors",
                active ? "bg-white/10 text-white" : "text-white/55 hover:bg-white/5 hover:text-white/80"
              )}
            >
              <MessageSquare size={13} className="flex-shrink-0 opacity-60" />
              {s.pinned && <Pin size={11} className="text-amber flex-shrink-0" />}
              <span className="min-w-0 flex-1">
                <span className="block truncate">{s.title}</span>
                {s.tags?.length > 0 && <span className="block truncate text-[10px] text-white/35">{s.tags.join(", ")}</span>}
              </span>
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.stopPropagation();
                  favoriteSession(sid, !s.favorite);
                }}
                className={clsx("flex-shrink-0", s.favorite ? "text-amber" : "text-white/25 hover:text-amber")}
                title="收藏"
              >
                <Star size={12} fill={s.favorite ? "currentColor" : "none"} />
              </span>
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.stopPropagation();
                  const raw = window.prompt("标签，用逗号分隔", (s.tags || []).join(", "));
                  if (raw !== null) tagSession(sid, raw.split(",").map((item) => item.trim()).filter(Boolean));
                }}
                className="text-white/25 hover:text-white/70 flex-shrink-0"
                title="标签"
              >
                #
              </span>
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.stopPropagation();
                  archiveSession(sid, true);
                }}
                className="text-white/25 hover:text-red-300 flex-shrink-0"
                title="归档"
              >
                <Archive size={12} />
              </span>
            </button>
          );
        })}
      </div>

      {sessionContextMenu && sessionsById[sessionContextMenu.sessionId] && (
        <SessionContextMenu
          menu={sessionContextMenu}
          session={sessionsById[sessionContextMenu.sessionId]}
          onClose={closeSessionContextMenu}
          actions={{
            selectSession: () => selectSession(activeModuleId, sessionContextMenu.sessionId),
            rename: async () => {
              const raw = window.prompt("重命名会话", sessionsById[sessionContextMenu.sessionId].title || "新对话");
              if (raw !== null) await updateSessionMeta(sessionContextMenu.sessionId, { title: raw || "新对话" });
            },
            favorite: () => favoriteSession(sessionContextMenu.sessionId, !sessionsById[sessionContextMenu.sessionId].favorite),
            pin: () => pinSession(sessionContextMenu.sessionId, !sessionsById[sessionContextMenu.sessionId].pinned),
            tag: () => {
              const s = sessionsById[sessionContextMenu.sessionId];
              const raw = window.prompt("标签，用逗号分隔", (s.tags || []).join(", "));
              if (raw !== null) tagSession(sessionContextMenu.sessionId, raw.split(",").map((item) => item.trim()).filter(Boolean));
            },
            archive: () => archiveSession(sessionContextMenu.sessionId, true),
            delete: () => {
              if (window.confirm("删除后会从侧边栏隐藏，但数据库保留软删除记录。确认删除？")) {
                deleteSession(sessionContextMenu.sessionId);
              }
            },
          }}
        />
      )}
    </aside>
  );
}

function SessionContextMenu({ menu, session, onClose, actions }) {
  const width = 184;
  const height = 236;
  const left = Math.min(menu.x, window.innerWidth - width - 8);
  const top = Math.min(menu.y, window.innerHeight - height - 8);

  const item = (label, Icon, handler, danger = false) => (
    <button
      className={clsx(
        "w-full flex items-center gap-2 px-3 py-2 text-left text-[12.5px] rounded-md",
        danger ? "text-red-600 hover:bg-red-50" : "text-ink-700 hover:bg-paper-100"
      )}
      onClick={(e) => {
        e.stopPropagation();
        onClose();
        handler();
      }}
    >
      <Icon size={14} />
      <span>{label}</span>
    </button>
  );

  return (
    <div
      className="fixed z-50 rounded-lg border border-line bg-paper-0 shadow-xl p-1.5"
      style={{ left, top, width }}
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      <div className="px-2 py-1.5 border-b border-line mb-1">
        <div className="text-[12px] text-ink-900 truncate">{session.title}</div>
        {session.tags?.length > 0 && <div className="font-mono text-[10px] text-ink-500 truncate">{session.tags.join(", ")}</div>}
      </div>
      {item("打开", MessageSquare, actions.selectSession)}
      {item("重命名", Type, actions.rename)}
      {item(session.favorite ? "取消收藏" : "收藏", Star, actions.favorite)}
      {item(session.pinned ? "取消置顶" : "置顶", Pin, actions.pin)}
      {item("设置标签", Tag, actions.tag)}
      {item("归档", Archive, actions.archive)}
      <div className="border-t border-line mt-1 pt-1">{item("删除", Trash2, actions.delete, true)}</div>
    </div>
  );
}
