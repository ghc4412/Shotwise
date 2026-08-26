import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkflowTemplateReviewSection } from "./WorkflowTemplateReviewSection";

const mocks = vi.hoisted(() => ({ list: vi.fn(), review: vi.fn() }));

vi.mock("@/api", () => ({ API: { listWorkflowReviewQueue: mocks.list, reviewWorkflowTemplate: mocks.review } }));

describe("WorkflowTemplateReviewSection", () => {
  beforeEach(() => {
    mocks.list.mockResolvedValue({ items: [{ id: "template-1", name: "Template One", template_type: "manga", status: "under_review", revision_version: 3, estimated_episode_cost: 2.5, risk_tags: ["copyright"], nodes: [{ node_key: "script" }, { node_key: "export" }], edges: [{ source_node_key: "script", target_node_key: "export" }], review_history: [] }] });
    mocks.review.mockResolvedValue({ id: "template-1", status: "published" });
  });

  it("loads the queue and displays graph validation details", async () => {
    render(<WorkflowTemplateReviewSection />);
    expect((await screen.findAllByText("Template One")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Static checks passed|静态校验通过|Kiểm tra tĩnh đạt/).length).toBeGreaterThan(0);
    expect(mocks.list).toHaveBeenCalledWith({ template_type: undefined, risk_tag: undefined });
  });

  it("records an approval with the administrator comment", async () => {
    render(<WorkflowTemplateReviewSection />);
    await screen.findAllByText("Template One");
    fireEvent.change(screen.getByTestId("workflow-review-decision"), { target: { value: "approve" } });
    fireEvent.change(screen.getByTestId("workflow-review-comment"), { target: { value: "Approved after review" } });
    fireEvent.click(screen.getByTestId("workflow-review-submit"));
    await waitFor(() => expect(mocks.review).toHaveBeenCalledWith("template-1", { decision: "approve", comment: "Approved after review" }));
  });
});
