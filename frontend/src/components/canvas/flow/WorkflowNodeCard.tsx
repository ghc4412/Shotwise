import { memo, useEffect, useRef, useState } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { AlertTriangle, Check, Circle, Clock3, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { nodeTypeDef, nodeTypeLabelKey } from "./node-registry";
import type { WorkflowNodeData } from "./workflow-utils";

function StatusIcon({ status }: { status: string }) {
  const cls = "h-3 w-3";
  if (status === "succeeded") return <Check aria-hidden className={cls} />;
  if (status === "running") return <Loader2 aria-hidden className={`${cls} motion-safe:animate-spin`} />;
  if (status === "failed") return <AlertTriangle aria-hidden className={cls} />;
  if (status === "paused" || status === "waiting_review" || status === "queued") return <Clock3 aria-hidden className={cls} />;
  if (status === "cancelled") return <X aria-hidden className={cls} />;
  return <Circle aria-hidden className={cls} />;
}

function statusTone(status: string): { color: string; background: string } {
  switch (status) {
    case "succeeded":
      return { color: "var(--color-good)", background: "oklch(0.93 0.045 155 / 0.5)" };
    case "running":
    case "queued":
      return { color: "var(--color-accent-2)", background: "var(--color-accent-dim)" };
    case "failed":
      return { color: "var(--color-danger)", background: "oklch(0.95 0.035 25 / 0.5)" };
    case "paused":
    case "waiting_review":
    case "retry_wait":
      return { color: "var(--color-warn)", background: "oklch(0.95 0.05 85 / 0.5)" };
    case "cancelled":
      return { color: "var(--color-text-4)", background: "var(--color-shell-btn)" };
    default:
      return { color: "var(--color-text-3)", background: "transparent" };
  }
}

function WorkflowNodeCardInner({ id, data, selected }: NodeProps<Node<WorkflowNodeData>>) {
  const { t } = useTranslation("dashboard");
  const def = nodeTypeDef(data.nodeType);
  const tone = data.status ? statusTone(data.status) : null;
  const progress = data.progress == null ? null : Math.round(data.progress * 100);
  const dimmed = data.disabled;
  return (
    <article
      className={`relative w-[200px] rounded-md border bg-bg-raised shadow-sm transition-shadow ${
        selected ? "shadow-md" : ""
      }`}
      style={{
        borderColor: dimmed ? "var(--color-hairline)" : def.color,
        opacity: dimmed ? 0.55 : 1,
      }}
      data-node-key={id}
    >
      {/* input ports */}
      {def.inputs.map((port) => (
        <Handle
          key={`in-${port.id}`}
          id={`in-${port.id}`}
          type="target"
          position={Position.Left}
          className="!h-2.5 !w-2.5 !border-0"
          style={{ background: def.color }}
          title={port.label}
        />
      ))}
      {/* output ports */}
      {def.outputs.map((port, index) => (
        <Handle
          key={`out-${port.id}`}
          id={`out-${port.id}`}
          type="source"
          position={Position.Right}
          className="!h-2.5 !w-2.5 !border-0"
          style={{
            background: def.color,
            top: `${18 + index * 22}%`,
          }}
          title={port.label}
        />
      ))}

      <div className="flex items-center justify-between gap-2 border-b border-hairline-soft px-2.5 py-1.5">
        <span
          className="inline-block h-2 w-2 shrink-0 rounded-full"
          style={{ background: def.color }}
          aria-hidden
        />
        <span className="min-w-0 flex-1 truncate text-[11px] font-semibold text-text">
          {t(nodeTypeLabelKey(data.nodeType))}
        </span>
        {data.status ? (
          <span
            className="inline-flex h-5 items-center gap-1 rounded border px-1 text-[9px] font-semibold"
            style={{ color: tone?.color, background: tone?.background, borderColor: tone?.color }}
            title={data.status}
          >
            <StatusIcon status={data.status} />
            {data.attemptNo ? `A${data.attemptNo}` : null}
          </span>
        ) : null}
      </div>

      <div className="min-h-[34px] px-2.5 py-1.5">
        <div className="line-clamp-1 font-mono text-[9px] text-text-4">{id}</div>
        {data.status === "running" || progress != null ? (
          <div className="mt-1.5 h-[3px] overflow-hidden rounded bg-black/20">
            <span
              className="block h-full transition-[width] duration-300"
              style={{ width: `${progress ?? 0}%`, background: tone?.color ?? def.color }}
            />
          </div>
        ) : null}
        {data.status ? (
          <div className="mt-1 font-mono text-[9px] text-text-4">{data.phaseCode ?? data.status}</div>
        ) : null}
        {dimmed ? <div className="mt-1 text-[9px] text-text-4">disabled</div> : null}
      </div>
    </article>
  );
}

export const WorkflowNodeCard = memo(WorkflowNodeCardInner);

export interface GroupNodeData extends Record<string, unknown> {
  label: string;
  color: string;
}

interface GroupNodeProps extends NodeProps<Node<GroupNodeData>> {
  onRename?: (label: string) => void;
}

function GroupNodeInner({ data, selected, onRename }: GroupNodeProps) {
  const { t } = useTranslation("dashboard");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(data.label);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);
  return (
    <div
      className="h-full w-full rounded-lg border-2 border-dashed p-1"
      style={{
        borderColor: selected ? data.color : "var(--color-hairline)",
        background: "color-mix(in oklab, transparent 60%, var(--color-bg-raised))",
      }}
      onDoubleClick={(event) => {
        event.stopPropagation();
        setDraft(data.label);
        setEditing(true);
      }}
    >
      <div className="flex items-center gap-1.5 px-1 py-0.5">
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: data.color }} aria-hidden />
        {editing ? (
          <input
            ref={inputRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={() => {
              setEditing(false);
              if (draft.trim() && draft !== data.label) onRename?.(draft.trim());
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                setEditing(false);
                if (draft.trim() && draft !== data.label) onRename?.(draft.trim());
              }
              if (event.key === "Escape") setEditing(false);
            }}
            className="w-full min-w-0 rounded border border-accent bg-bg px-1 text-[11px] font-semibold text-text outline-none"
            aria-label={t("flow_group_rename")}
          />
        ) : (
          <span className="min-w-0 truncate text-[10px] font-semibold text-text-2" title={t("flow_group_rename_hint")}>
            {data.label}
          </span>
        )}
      </div>
    </div>
  );
}

export const GroupNode = memo(GroupNodeInner);
