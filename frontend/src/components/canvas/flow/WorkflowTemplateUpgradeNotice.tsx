import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "../../../api";
import type { WorkflowTemplateUpgrade } from "../../../types/workflow";

type WorkflowTemplateUpgradeNoticeProps = {
  definitionId: string | null;
  onApplied?: () => void;
};

export function WorkflowTemplateUpgradeNotice({
  definitionId,
  onApplied,
}: WorkflowTemplateUpgradeNoticeProps) {
  const { t } = useTranslation("dashboard");
  const [upgrade, setUpgrade] = useState<WorkflowTemplateUpgrade | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!definitionId) {
      return () => { active = false; };
    }
    void API.getWorkflowTemplateUpgrade(definitionId)
      .then((value) => {
        if (active) {
          setError(null);
          setUpgrade(value);
        }
      })
      .catch(() => { if (active) setError(t("workflow_template_upgrade_load_error")); });
    return () => { active = false; };
  }, [definitionId, t]);

  if (!definitionId || !upgrade?.available) {
    return error ? <p className="text-sm text-red-700">{error}</p> : null;
  }

  const applyUpgrade = async () => {
    if (!definitionId || !upgrade.compatible) return;
    setBusy(true);
    setError(null);
    try {
      await API.applyWorkflowTemplateUpgrade(definitionId);
      onApplied?.();
      setUpgrade(null);
    } catch {
      setError(t("workflow_template_upgrade_apply_error"));
    } finally {
      setBusy(false);
    }
  };

  const changes = upgrade.changes;
  return (
    <section
      className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950"
      data-testid="workflow-template-upgrade-notice"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">{t("workflow_template_upgrade_title")}</h3>
          <p className="mt-1">
            {t("workflow_template_upgrade_revision", { revision: upgrade.latest_revision_no ?? "—" })}
          </p>
        </div>
        <button
          type="button"
          className="rounded border border-amber-400 px-3 py-1.5 hover:bg-amber-100"
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? t("workflow_template_upgrade_hide_details") : t("workflow_template_upgrade_show_details")}
        </button>
      </div>
      {expanded && (
        <div className="mt-3 space-y-2 border-t border-amber-200 pt-3">
          <p>{t("workflow_template_upgrade_cost", { delta: upgrade.estimated_cost_delta ?? 0 })}</p>
          <p className={upgrade.compatible ? "text-emerald-700" : "text-red-700"}>
            {upgrade.compatible ? t("workflow_template_upgrade_compatible") : t("workflow_template_upgrade_incompatible")}
          </p>
          {changes && (
            <ul className="list-disc space-y-1 pl-5">
              <li>{t("workflow_template_upgrade_nodes_added", { count: changes.added_nodes.length })}</li>
              <li>{t("workflow_template_upgrade_nodes_removed", { count: changes.removed_nodes.length })}</li>
              <li>{t("workflow_template_upgrade_nodes_changed", { count: changes.changed_nodes.length })}</li>
              <li>{t("workflow_template_upgrade_edges_changed", { count: changes.added_edges.length + changes.removed_edges.length })}</li>
            </ul>
          )}
          {upgrade.compatibility_reasons?.map((reason) => (
            <p key={reason} className="text-red-700">{reason}</p>
          ))}
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy || !upgrade.compatible}
          className="rounded bg-amber-700 px-3 py-1.5 text-white disabled:cursor-not-allowed disabled:opacity-50"
          onClick={() => void applyUpgrade()}
        >
          {busy ? t("workflow_template_upgrade_applying") : t("workflow_template_upgrade_apply")}
        </button>
        {!upgrade.compatible && <span>{t("workflow_template_upgrade_confirmation_required")}</span>}
        {error && <span className="text-red-700">{error}</span>}
      </div>
    </section>
  );
}
