import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { WorkflowRunDetail } from "@/types";
import { WorkflowRunBudgetPanel } from "./WorkflowRunBudgetPanel";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

function makeRun(overrides: Record<string, unknown> = {}) {
  return { id: "run-1", status: "running", version: 1, nodes: [], budget_limit: 10, spent_amount: 4.25, reserved_amount: 1.5, episode_id: "episode-3", ...overrides } as unknown as WorkflowRunDetail;
}

describe("WorkflowRunBudgetPanel", () => {
  it("shows the episode budget breakdown and remaining amount", () => {
    render(<WorkflowRunBudgetPanel run={makeRun()} />);
    expect(screen.getByText("flow_run_budget_limit")).toBeInTheDocument();
    expect(screen.getByText("10.00")).toBeInTheDocument();
    expect(screen.getAllByText("4.25")).toHaveLength(2);
    expect(screen.getByText("1.50")).toBeInTheDocument();
    expect(screen.getByText("episode-3")).toBeInTheDocument();
  });

  it("surfaces quality gate failures without a budget limit", () => {
    render(<WorkflowRunBudgetPanel run={makeRun({ budget_limit: null, status: "waiting_review", nodes: [{ node_key: "quality-check", error_code: "quality_gate_failed" }] })} />);
    expect(screen.getByText("flow_run_quality_failed")).toBeInTheDocument();
    expect(screen.getByText("quality-check")).toBeInTheDocument();
    expect(screen.getByText("flow_run_quality_review")).toBeInTheDocument();
  });

  it("shows deduplicated quality gate repair suggestions", () => {
    render(
      <WorkflowRunBudgetPanel
        run={makeRun({
          budget_limit: null,
          status: "waiting_review",
          nodes: [
            {
              node_key: "quality-check",
              error_code: "quality_gate_failed",
              error_params: {
                repair_suggestions: ["缩短字幕或调整安全区", "缩短字幕或调整安全区"],
              },
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("flow_run_quality_repairs")).toBeInTheDocument();
    expect(screen.getAllByText("缩短字幕或调整安全区")).toHaveLength(1);
  });

  it("does not render when the run has no budget or quality review state", () => {
    const { container } = render(<WorkflowRunBudgetPanel run={makeRun({ budget_limit: null })} />);
    expect(container).toBeEmptyDOMElement();
  });
});
