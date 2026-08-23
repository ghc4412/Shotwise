import { AlertTriangle, CheckCircle2, DollarSign } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { WorkflowNodeRun, WorkflowRunDetail } from "@/types";

type BudgetRun = WorkflowRunDetail & {
  episode_id?: string | null;
  budget_limit?: number | null;
  spent_amount?: number | null;
  reserved_amount?: number | null;
};

type GateNode = WorkflowNodeRun & { error_code?: string | null };

interface WorkflowRunBudgetPanelProps {
  run: WorkflowRunDetail | null;
}

function formatAmount(value: number): string {
  return new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

export function WorkflowRunBudgetPanel({ run }: WorkflowRunBudgetPanelProps) {
  const { t } = useTranslation("dashboard");
  if (!run) return null;

  const budgetRun = run as BudgetRun;
  const limit = budgetRun.budget_limit;
  const spent = budgetRun.spent_amount ?? 0;
  const reserved = budgetRun.reserved_amount ?? 0;
  const remaining = limit == null ? null : limit - spent - reserved;
  const gateFailures = (run.nodes as GateNode[]).filter((node) => node.error_code === "quality_gate_failed");
  const repairSuggestions = gateFailures.flatMap((node) => {
    const suggestions = node.error_params?.repair_suggestions;
    return Array.isArray(suggestions)
      ? suggestions.filter((suggestion): suggestion is string => typeof suggestion === "string")
      : [];
  });
  if (remaining == null && gateFailures.length === 0 && run.status !== "waiting_review") return null;

  const overBudget = remaining != null && remaining < 0;
  const spentRatio = limit && limit > 0 ? Math.min(100, ((spent + reserved) / limit) * 100) : 0;

  return (
    <section className="border-b border-hairline bg-bg-raised px-4 py-3" aria-labelledby="workflow-run-budget-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2"><DollarSign size={14} className="text-accent-2" aria-hidden="true" /><h2 id="workflow-run-budget-title" className="text-xs font-semibold text-text">{t("flow_run_budget_title")}</h2>{budgetRun.episode_id ? <span className="font-mono text-[10px] text-text-4">{budgetRun.episode_id}</span> : null}</div>
        {run.status === "waiting_review" || gateFailures.length > 0 ? <span className="inline-flex items-center gap-1 rounded border border-warn/40 px-1.5 py-0.5 text-[10px] text-warn"><AlertTriangle size={12} aria-hidden="true" />{t("flow_run_quality_review")}</span> : null}
      </div>
      {limit != null ? <><div className="mt-2 grid gap-2 text-[10px] sm:grid-cols-4"><div><span className="block text-text-4">{t("flow_run_budget_limit")}</span><strong className="font-mono text-text">{formatAmount(limit)}</strong></div><div><span className="block text-text-4">{t("flow_run_budget_spent")}</span><strong className="font-mono text-text">{formatAmount(spent)}</strong></div><div><span className="block text-text-4">{t("flow_run_budget_reserved")}</span><strong className="font-mono text-text">{formatAmount(reserved)}</strong></div><div><span className="block text-text-4">{t("flow_run_budget_remaining")}</span><strong className={overBudget ? "font-mono text-danger" : "font-mono text-good"}>{formatAmount(remaining ?? 0)}</strong></div></div><div className="mt-2 h-1 overflow-hidden rounded-full bg-bg"><div className={overBudget ? "h-full bg-danger" : "h-full bg-accent-2"} style={{ width: spentRatio + "%" }} /></div></> : null}
      {gateFailures.length > 0 ? (
        <div className="mt-3 rounded border border-warn/30 bg-warn/5 p-2 text-[11px]">
          <div className="flex items-center gap-1.5 font-semibold text-warn">
            <AlertTriangle size={12} aria-hidden="true" />
            {t("flow_run_quality_failed")}
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {gateFailures.map((node) => (
              <span
                key={node.node_key}
                className="inline-flex items-center gap-1 rounded border border-warn/30 px-1.5 py-0.5 font-mono text-[10px] text-text-2"
              >
                <CheckCircle2 size={11} className="text-warn" aria-hidden="true" />
                {node.node_key}
              </span>
            ))}
          </div>
          <p className="mt-1 text-text-3">{t("flow_run_quality_hint")}</p>
          {repairSuggestions.length > 0 ? (
            <div className="mt-2">
              <p className="font-medium text-text-2">{t("flow_run_quality_repairs")}</p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-text-3">
                {[...new Set(repairSuggestions)].map((suggestion) => (
                  <li key={suggestion}>{suggestion}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
