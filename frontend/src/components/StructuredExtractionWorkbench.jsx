import React, { useEffect } from "react";
import { AlertCircle } from "lucide-react";
import { useAppStore } from "../store/useAppStore";
import ExtractionTaskList from "./structured-extraction/ExtractionTaskList";
import ExtractionTaskOverview from "./structured-extraction/ExtractionTaskOverview";

export default function StructuredExtractionWorkbench() {
  const view = useAppStore((s) => s.structuredExtraction.view);
  const error = useAppStore((s) => s.structuredExtraction.error);
  const loadExtractionTasks = useAppStore((s) => s.loadExtractionTasks);

  useEffect(() => {
    loadExtractionTasks().catch(() => {});
  }, [loadExtractionTasks]);

  return (
    <main className="flex-1 min-h-0 bg-paper-50 overflow-hidden">
      <div className="h-full flex flex-col">
        {error && (
          <div className="flex-shrink-0 border-b border-red-200 bg-red-50 px-5 py-2.5 text-[13px] text-red-700 flex items-center gap-2">
            <AlertCircle size={15} />
            <span className="truncate">{error}</span>
          </div>
        )}
        {view === "detail" ? <ExtractionTaskOverview /> : <ExtractionTaskList />}
      </div>
    </main>
  );
}
