import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API } from "../../../api";
import { WorkflowTemplateUpgradeNotice } from "./WorkflowTemplateUpgradeNotice";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => ({
      workflow_template_upgrade_title: "Template upgrade available",
      workflow_template_upgrade_revision: "Latest published revision: 3",
      workflow_template_upgrade_show_details: "View changes",
      workflow_template_upgrade_hide_details: "Hide changes",
      workflow_template_upgrade_cost: "Estimated cost change: 0",
      workflow_template_upgrade_compatible: "Compatible with this project",
      workflow_template_upgrade_incompatible: "Compatibility check failed",
      workflow_template_upgrade_nodes_added: "Added nodes: 1",
      workflow_template_upgrade_nodes_removed: "Removed nodes: 0",
      workflow_template_upgrade_nodes_changed: "Changed nodes: 1",
      workflow_template_upgrade_edges_changed: "Changed edges: 1",
      workflow_template_upgrade_apply: "Create upgraded revision",
      workflow_template_upgrade_applying: "Applying…",
      workflow_template_upgrade_confirmation_required: "Only compatible revisions can be applied.",
      workflow_template_upgrade_load_error: "Unable to check for template upgrades.",
      workflow_template_upgrade_apply_error: "Unable to apply the template upgrade.",
    }[key] ?? key),
  }),
}));

vi.mock("../../../api", () => ({
  API: {
    getWorkflowTemplateUpgrade: vi.fn(),
    applyWorkflowTemplateUpgrade: vi.fn(),
  },
}));

const getUpgrade = vi.mocked(API.getWorkflowTemplateUpgrade);
const applyUpgrade = vi.mocked(API.applyWorkflowTemplateUpgrade);

describe("WorkflowTemplateUpgradeNotice", () => {
  beforeEach(() => vi.clearAllMocks());

  it("hides when no upgrade is available", async () => {
    getUpgrade.mockResolvedValue({ available: false });
    render(<WorkflowTemplateUpgradeNotice definitionId="definition-1" />);
    await waitFor(() => expect(getUpgrade).toHaveBeenCalledWith("definition-1"));
    expect(screen.queryByTestId("workflow-template-upgrade-notice")).not.toBeInTheDocument();
  });

  it("previews and applies a compatible upgrade", async () => {
    getUpgrade.mockResolvedValue({
      available: true,
      compatible: true,
      latest_revision_no: 3,
      changes: {
        added_nodes: ["voice"],
        removed_nodes: [],
        changed_nodes: ["export"],
        added_edges: ["voice->export"],
        removed_edges: [],
      },
    });
    applyUpgrade.mockResolvedValue({
      upgrade: { available: true, compatible: true },
      revision: { id: "revision-3", status: "published" },
    });
    const onApplied = vi.fn();
    render(<WorkflowTemplateUpgradeNotice definitionId="definition-1" onApplied={onApplied} />);
    expect(await screen.findByTestId("workflow-template-upgrade-notice")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View changes" }));
    expect(screen.getByText("Added nodes: 1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create upgraded revision" }));
    await waitFor(() => expect(applyUpgrade).toHaveBeenCalledWith("definition-1"));
    expect(onApplied).toHaveBeenCalledTimes(1);
  });
});
