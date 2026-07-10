import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

export default class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Uncaught UI error", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const message = this.state.error?.message || "界面渲染失败";
    return (
      <div className="flex h-screen items-center justify-center bg-paper-50 px-4">
        <div className="w-full max-w-[460px] rounded-lg border border-red-200 bg-paper-0 p-5 shadow-xl">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-red-50 text-red-600">
              <AlertTriangle size={17} />
            </span>
            <div className="min-w-0 flex-1">
              <h1 className="font-serif text-[18px] text-ink-900">界面遇到渲染错误</h1>
              <p className="mt-1 text-[13px] leading-relaxed text-ink-500">
                当前页面状态无法继续显示，可以刷新后回到最近保存的会话。
              </p>
              <div className="mt-3 rounded-md border border-line bg-paper-50 px-3 py-2 font-mono text-[11px] text-ink-500">
                {message}
              </div>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="mt-4 inline-flex items-center gap-1.5 rounded-md bg-ink-900 px-3 py-1.5 text-[12.5px] text-paper-50 hover:bg-ink-800"
              >
                <RefreshCw size={13} /> 刷新页面
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }
}
