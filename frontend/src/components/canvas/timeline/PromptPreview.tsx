import { useState } from "react";
import { Check, ChevronDown, Copy, Eye, EyeOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import { copyText } from "@/utils/clipboard";

export type PromptPreviewShape = "structured" | "plain_text" | "unknown";

export interface PromptPreviewReference {
  kind: "character" | "scene" | "prop" | "product" | "image" | "other";
  label: string;
  value: string;
}

export interface PromptPreviewRequest {
  id: string;
  label: string;
  originalPrompt: string;
  /** Null means that the current UI has no compiled request snapshot to display. */
  effectivePrompt: string | null;
  shape: PromptPreviewShape;
  provider?: string | null;
  model?: string | null;
  references?: PromptPreviewReference[];
  durationSeconds?: number | null;
  resolution?: string | null;
  capabilityAdjustments?: string[];
  warnings?: string[];
  /** A safe-to-display request summary. Secret fields are redacted again at render time. */
  requestSummary?: unknown;
}

/**
 * Public UI seam for the read-only preview. Producers may pass a future enqueue snapshot here,
 * but this component always derives its display and copy text from the redacted form.
 */
export interface PromptPreviewModel {
  source: "current_draft" | "enqueue_snapshot";
  requests: PromptPreviewRequest[];
}

interface RedactionLabels {
  redacted: string;
  circular: string;
}

const DEFAULT_REDACTION_LABELS: RedactionLabels = {
  redacted: "[REDACTED]",
  circular: "[circular]",
};
const secretKeyPattern = /^(?:x[-_])?(?:api[-_]?key|key|authorization|auth|access[-_]?token|refresh[-_]?token|token|secret|password|cookie|set[-_]?cookie|credential|session|bearer)(?:[-_].*)?$/i;
const inlineSecretPattern = /\b(authorization|auth|x[-_]?api[-_]?key|api[-_]?key|key|token|secret|password|cookie|session)\s*[:=]\s*([^\s,;"']+)/gi;
const bearerPattern = /\bbearer\s+[^\s,;"']+/gi;

function redactInlineSecrets(value: string, redacted: string): string {
  return value
    .replace(inlineSecretPattern, (_match, field: string) => `${field}=${redacted}`)
    .replace(bearerPattern, `Bearer ${redacted}`);
}

function isSecretKey(key: string): boolean {
  return secretKeyPattern.test(key.trim());
}

/** Converts arbitrary request metadata into a display-safe clone. */
export function redactPreviewValue(
  value: unknown,
  seen = new WeakSet<object>(),
  labels: RedactionLabels = DEFAULT_REDACTION_LABELS,
): unknown {
  if (typeof value === "string") return redactInlineSecrets(value, labels.redacted);
  if (value === null || typeof value !== "object") return value;
  if (seen.has(value)) return labels.circular;
  seen.add(value);

  if (Array.isArray(value)) {
    const result = value.map((item) => redactPreviewValue(item, seen, labels));
    seen.delete(value);
    return result;
  }

  const result: Record<string, unknown> = {};
  for (const [key, child] of Object.entries(value)) {
    result[key] = isSecretKey(key) ? labels.redacted : redactPreviewValue(child, seen, labels);
  }
  seen.delete(value);
  return result;
}

function safeText(value: string, labels: RedactionLabels): string {
  return redactInlineSecrets(value, labels.redacted);
}

function formatSummary(value: unknown, labels: RedactionLabels): string {
  const replacer = (_key: string, child: unknown): unknown =>
    typeof child === "bigint" ? `${child}` : child;
  return JSON.stringify(
    redactPreviewValue(value, new WeakSet<object>(), labels),
    replacer,
    2,
  ) ?? labels.circular;
}

function summaryScalar(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") return `${value}`;
  return "—";
}

function renderSummaryRows(value: unknown, labels: RedactionLabels, depth = 0): React.ReactNode {
  if (value === null || typeof value !== "object") {
    return <span className="break-all">{summaryScalar(value)}</span>;
  }
  if (Array.isArray(value)) {
    return (
      <div className="flex flex-col gap-1">
        {value.map((item, index) => (
          <div key={index} className="pl-2" style={{ borderLeft: "1px solid var(--color-hairline-soft)" }}>
            {renderSummaryRows(item, labels, depth + 1)}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className={depth === 0 ? "flex flex-col gap-1.5" : "flex flex-col gap-1 pl-2"}>
      {Object.entries(value).map(([key, child]) => (
        <div key={key} className="grid grid-cols-[minmax(80px,auto)_1fr] gap-x-2 text-[10.5px]">
          <span className="break-all" style={{ color: "var(--color-text-4)" }}>
            {key}
          </span>
          <span style={{ color: "var(--color-text-2)" }}>{renderSummaryRows(child, labels, depth + 1)}</span>
        </div>
      ))}
    </div>
  );
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-x-2 gap-y-1 text-[11px]">
      <span style={{ color: "var(--color-text-4)" }}>{label}</span>
      <div className="min-w-0" style={{ color: "var(--color-text-2)" }}>
        {children}
      </div>
    </div>
  );
}

function PromptBlock({ label, value, labels }: { label: string; value: string; labels: RedactionLabels }) {
  return (
    <div className="rounded-md p-2 text-[11px] leading-relaxed" style={{ background: "var(--color-shell-field)", border: "1px solid var(--color-hairline-soft)" }}>
      <div className="mb-1 text-[10px] font-bold uppercase" style={{ color: "var(--color-text-4)", letterSpacing: "0.7px" }}>
        {label}
      </div>
      <pre className="whitespace-pre-wrap break-words font-sans" style={{ color: "var(--color-text-2)" }}>
        {safeText(value, labels) || "—"}
      </pre>
    </div>
  );
}

export function PromptPreview({ preview }: { preview: PromptPreviewModel }) {
  const { t } = useTranslation("dashboard");
  const redactionLabels: RedactionLabels = {
    redacted: t("prompt_preview_redacted"),
    circular: t("prompt_preview_circular"),
  };
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const redactedSummary = preview.requests.map((request) => ({
    id: request.id,
    request_summary: redactPreviewValue(request.requestSummary ?? {}, new WeakSet<object>(), redactionLabels),
  }));

  const handleCopy = async () => {
    try {
      await copyText(formatSummary(redactedSummary, redactionLabels));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section
      aria-label={t("prompt_preview_title")}
      className="rounded-lg p-3"
      style={{ border: "1px solid var(--color-hairline-soft)", background: "var(--panel-spec-bar-bg)" }}
    >
      <div className="mb-3 flex items-center gap-1.5">
        <Eye className="h-3.5 w-3.5" aria-hidden="true" style={{ color: "var(--color-accent-2)" }} />
        <h3 className="text-[12px] font-semibold" style={{ color: "var(--color-text-2)" }}>
          {t("prompt_preview_title")}
        </h3>
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => void handleCopy()}
          aria-label={t("prompt_preview_copy")}
          className="focus-ring inline-flex items-center gap-1 rounded px-1.5 py-1 text-[10.5px]"
          style={{ color: "var(--color-text-3)" }}
        >
          {copied ? <Check className="h-3 w-3" aria-hidden="true" /> : <Copy className="h-3 w-3" aria-hidden="true" />}
          {copied ? t("prompt_preview_copied") : t("prompt_preview_copy")}
        </button>
      </div>

      <p className="mb-3 text-[10.5px] leading-relaxed" style={{ color: "var(--color-text-4)" }}>
        {preview.source === "enqueue_snapshot"
          ? t("prompt_preview_source_enqueue")
          : t("prompt_preview_source_draft")}
      </p>

      <div className="flex flex-col gap-4">
        {preview.requests.map((request) => {
          const summary = redactPreviewValue(request.requestSummary ?? {}, new WeakSet<object>(), redactionLabels);
          const effectivePrompt = request.effectivePrompt ?? request.originalPrompt;
          return (
            <div key={request.id} className="flex flex-col gap-2.5">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-semibold" style={{ color: "var(--color-text-2)" }}>
                  {safeText(request.label, redactionLabels)}
                </span>
                <span className="num rounded px-1.5 py-0.5 text-[9.5px]" style={{ background: "var(--color-shell-btn-2)", color: "var(--color-text-3)" }}>
                  {request.shape}
                </span>
              </div>

              <PromptBlock label={t("prompt_preview_original")} value={request.originalPrompt} labels={redactionLabels} />
              <PromptBlock label={t("prompt_preview_effective")} value={effectivePrompt} labels={redactionLabels} />
              {request.effectivePrompt === null && (
                <p className="text-[10.5px]" style={{ color: "var(--color-text-4)" }}>
                  {t("prompt_preview_effective_unavailable")}
                </p>
              )}

              <div className="flex flex-col gap-1.5">
                <DetailRow label={t("prompt_preview_provider_model")}>
                  {request.provider || request.model
                    ? [request.provider, request.model].filter(Boolean).map((value) => safeText(value!, redactionLabels)).join(" / ")
                    : t("prompt_preview_unavailable")}
                </DetailRow>
                <DetailRow label={t("prompt_preview_references")}>
                  {request.references?.length
                    ? request.references.map((reference) => `${safeText(reference.label, redactionLabels)}: ${safeText(reference.value, redactionLabels)}`).join(" · ")
                    : t("prompt_preview_none")}
                </DetailRow>
                <DetailRow label={t("prompt_preview_duration_resolution")}>
                  {[request.durationSeconds == null ? null : t("duration_seconds_value_text", { value: request.durationSeconds }), request.resolution]
                    .filter(Boolean)
                    .join(" · ") || t("prompt_preview_unavailable")}
                </DetailRow>
                <DetailRow label={t("prompt_preview_adjustments")}>
                  {request.capabilityAdjustments?.length
                    ? request.capabilityAdjustments.map((value) => safeText(value, redactionLabels)).join(" · ")
                    : t("prompt_preview_none")}
                </DetailRow>
                <DetailRow label={t("prompt_preview_warnings")}>
                  {request.warnings?.length ? request.warnings.map((value) => safeText(value, redactionLabels)).join(" · ") : t("prompt_preview_none")}
                </DetailRow>
              </div>

              <div className="rounded-md p-2" style={{ background: "var(--color-shell-field)", border: "1px solid var(--color-hairline-soft)" }}>
                <div className="mb-1.5 text-[10px] font-bold uppercase" style={{ color: "var(--color-text-4)", letterSpacing: "0.7px" }}>
                  {t("prompt_preview_request_summary")}
                </div>
                {renderSummaryRows(summary, redactionLabels)}
              </div>

              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                aria-expanded={expanded}
                className="focus-ring inline-flex items-center gap-1 self-start rounded px-1 py-0.5 text-[10.5px]"
                style={{ color: "var(--color-text-3)" }}
              >
                {expanded ? <EyeOff className="h-3 w-3" aria-hidden="true" /> : <ChevronDown className="h-3 w-3" aria-hidden="true" />}
                {t("prompt_preview_advanced")}
              </button>
              {expanded && (
                <pre
                  className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md p-2 text-[10px] leading-relaxed"
                  style={{ background: "var(--color-shell-field)", border: "1px solid var(--color-hairline-soft)", color: "var(--color-text-3)" }}
                >
                  {formatSummary(request.requestSummary ?? {}, redactionLabels)}
                </pre>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
