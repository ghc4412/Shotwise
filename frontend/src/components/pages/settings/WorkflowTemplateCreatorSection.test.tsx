import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkflowTemplateCreatorSection } from "./WorkflowTemplateCreatorSection";

const mocks = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), update: vi.fn(), submit: vi.fn(), withdraw: vi.fn() }));
vi.mock("@/api", () => ({ API: { listWorkflowCreatorTemplates: mocks.list, createWorkflowTemplateDraft: mocks.create, updateWorkflowTemplateDraft: mocks.update, submitWorkflowTemplate: mocks.submit, withdrawWorkflowTemplate: mocks.withdraw } }));

describe("WorkflowTemplateCreatorSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({ items: [] });
    mocks.create.mockResolvedValue({ id: "template-1", status: "draft", name: "Creator template" });
    mocks.update.mockResolvedValue({ id: "template-2", status: "draft", name: "Updated template" });
    mocks.submit.mockResolvedValue({ id: "template-1", status: "submitted" });
    mocks.withdraw.mockResolvedValue({ id: "template-1", status: "draft" });
  });

  it("creates and submits a draft", async () => {
    render(<WorkflowTemplateCreatorSection />);
    fireEvent.change(screen.getByTestId("workflow-creator-name"), { target: { value: "Creator template" } });
    fireEvent.click(screen.getByTestId("workflow-creator-save"));
    await waitFor(() => expect(mocks.create).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("workflow-creator-submit"));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledWith("template-1"));
  });

  it("edits a rejected draft and renders review feedback", async () => {
    mocks.list.mockResolvedValue({ items: [{ id: "template-2", name: "Needs changes", description: "old", template_type: "manga", status: "rejected", contract: { nodes: [], edges: [] }, reviews: [{ id: "review-1", decision: "changes_requested", comment: "Add an export node" }] }] });
    render(<WorkflowTemplateCreatorSection />);
    fireEvent.click(await screen.findByRole("button", { name: /Needs changes/ }));
    fireEvent.change(screen.getByTestId("workflow-creator-name"), { target: { value: "Updated template" } });
    fireEvent.click(screen.getByTestId("workflow-creator-save"));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith("template-2", expect.objectContaining({ name: "Updated template" })));
    expect(screen.getByText(/Add an export node/)).toBeTruthy();
  });
});
