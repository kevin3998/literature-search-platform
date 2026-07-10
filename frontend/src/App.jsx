import React, { useEffect } from "react";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import ChatPanel from "./components/ChatPanel";
import LiteratureSearchWorkbench from "./components/LiteratureSearchWorkbench";
import ResultsPanel from "./components/ResultsPanel";
import SettingsModal from "./components/SettingsModal";
import HomeDashboard from "./components/HomeDashboard";
import WorkflowView from "./components/WorkflowView";
import StructuredExtractionWorkbench from "./components/StructuredExtractionWorkbench";
import AuthScreen from "./components/AuthScreen";
import { useAppStore } from "./store/useAppStore";
import { AlertTriangle, X } from "lucide-react";

export default function App() {
  const bootstrapAuth = useAppStore((s) => s.bootstrapAuth);
  const authStatus = useAppStore((s) => s.auth.status);
  const modulesLoaded = useAppStore((s) => s.modulesLoaded);
  const activeModuleId = useAppStore((s) => s.activeModuleId);
  const homeOpen = useAppStore((s) => s.homeOpen);
  const workflowOpen = useAppStore((s) => s.workflowOpen);
  const structuredExtractionOpen = useAppStore((s) => s.structuredExtractionOpen);
  const appError = useAppStore((s) => s.appError);
  const clearAppError = useAppStore((s) => s.clearAppError);

  useEffect(() => {
    bootstrapAuth();
  }, [bootstrapAuth]);

  if (authStatus === "checking") {
    return (
      <div className="h-screen flex items-center justify-center bg-paper-50 text-ink-500 text-[13px] font-mono">
        正在检查登录状态…
      </div>
    );
  }

  if (authStatus === "login_required") {
    return <AuthScreen />;
  }

  if ((!modulesLoaded || !activeModuleId) && !appError) {
    return (
      <div className="h-screen flex items-center justify-center bg-paper-50 text-ink-500 text-[13px] font-mono">
        正在连接后端服务…
      </div>
    );
  }

  return (
    <div className="h-screen flex bg-paper-50">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar />
        {appError && <AppErrorBanner error={appError} onClose={clearAppError} />}
        {!activeModuleId ? (
          <div className="flex-1 flex items-center justify-center bg-paper-50 text-ink-500 text-[13px]">
            后端暂不可用，请检查开发服务状态。
          </div>
        ) : homeOpen ? (
          <HomeDashboard />
        ) : workflowOpen ? (
          <WorkflowView />
        ) : structuredExtractionOpen ? (
          <StructuredExtractionWorkbench />
        ) : activeModuleId === "literature_search" ? (
          <LiteratureSearchWorkbench />
        ) : (
          <div className="flex-1 flex min-h-0">
            <ChatPanel />
            <ResultsPanel />
          </div>
        )}
      </div>
      {/* Settings opens as a centered modal over the current workbench so closing
          it returns the user to the exact prior session/workbench state. */}
      <SettingsModal />
    </div>
  );
}

function AppErrorBanner({ error, onClose }) {
  return (
    <div className="flex-shrink-0 border-b border-red-200 bg-red-50 px-5 py-2.5 text-red-700">
      <div className="flex items-center gap-2 text-[13px]">
        <AlertTriangle size={15} className="flex-shrink-0" />
        <span className="min-w-0 flex-1 truncate">{error.message}</span>
        <button
          type="button"
          onClick={onClose}
          className="flex-shrink-0 rounded p-1 text-red-600 hover:bg-red-100"
          aria-label="关闭错误提示"
          title="关闭"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
