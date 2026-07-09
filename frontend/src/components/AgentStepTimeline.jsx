import React from "react";
import { Check, Loader2, X } from "lucide-react";

function StepIcon({ status }) {
  if (status === "running") return <Loader2 size={12} className="animate-spin text-amber" />;
  if (status === "error") return <X size={12} className="text-red-500" />;
  return <Check size={12} className="text-teal" />;
}

export default function AgentStepTimeline({ steps }) {
  if (!steps || steps.length === 0) return null;
  return (
    <div className="rounded-md border border-line bg-ink-900/[0.03] px-3.5 py-2.5 font-mono text-[11.5px] text-ink-700 space-y-1.5">
      {steps.map((s, i) => (
        <div key={i} className="flex items-center gap-2">
          <StepIcon status={s.status} />
          <span className={s.status === "running" ? "text-ink-700" : "text-ink-500"}>
            {s.label}
            {s.detail ? <span className="text-ink-400"> · {s.detail}</span> : null}
          </span>
        </div>
      ))}
    </div>
  );
}
