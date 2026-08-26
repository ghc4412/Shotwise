import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { WorkflowTemplateLauncher } from "./WorkflowTemplateLauncher";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) => typeof values?.defaultValue === "string" ? values.defaultValue : key,
  }),
}));

const templates = [
  {
    id: "manga-1",
    scope: "marketplace" as const,
    name_key: "flow_template_manga",
    description_key: "flow_template_manga_desc",
    name: "Manga storyboard",
    description: "A manga production workflow",
    template_type: "manga" as const,
    status: "published",
    stats: { views: 10, derivations: 3, run_count: 4, successful_run_count: 3, success_rate: 75, average_cost: 2, average_duration_seconds: 20, rating: 4.5 },
    nodes: [],
    edges: [],
  },
  {
    id: "drama-1",
    scope: "marketplace" as const,
    name_key: "flow_template_drama",
    description_key: "flow_template_drama_desc",
    name: "Short drama",
    description: "A short drama workflow",
    template_type: "short_drama" as const,
    status: "published",
    stats: { views: 2, derivations: 1, run_count: 0, successful_run_count: 0, success_rate: 0, average_cost: 0, average_duration_seconds: 0, rating: null },
    nodes: [],
    edges: [],
  },
];

describe("WorkflowTemplateLauncher", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(API, "listWorkflowTemplates").mockResolvedValue({ items: templates });
  });

  it("loads published templates and filters by content type", async () => {
    render(<WorkflowTemplateLauncher projectName="demo" />);

    expect(await screen.findByText("Manga storyboard")).toBeInTheDocument();
    expect(screen.getByText("Short drama")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "flow_templates_manga" }));

    expect(screen.getByText("Manga storyboard")).toBeInTheDocument();
    expect(screen.queryByText("Short drama")).not.toBeInTheDocument();
  });

 it("derives the selected template into the current project", async () => {
   const derive = vi.spyOn(API, "deriveWorkflowTemplate").mockResolvedValue({
     definition_id: "definition-1",
     revision_id: "revision-1",
     template_id: "manga-1",
   });
   const onDerived = vi.fn();
   render(<WorkflowTemplateLauncher projectName="demo" onDerived={onDerived} />);

   fireEvent.click(await screen.findByRole("button", { name: "flow_templates_manga" }));
   fireEvent.click(await screen.findByRole("button", { name: "creation_skill_use" }));

   await waitFor(() => expect(derive).toHaveBeenCalledWith("manga-1", {
     workspace_id: "default",
     project_id: "demo",
     name: "Manga storyboard — demo",
   }));
   await waitFor(() => expect(onDerived).toHaveBeenCalledTimes(1));
   expect(await screen.findByRole("button", { name: "creation_skill_used" })).toBeDisabled();
 });

  it("submits a template rating", async () => {
    const rate = vi.spyOn(API, "rateWorkflowTemplate").mockResolvedValue({
      template_id: "manga-1",
      rating: 5,
      rating_count: 1,
    });
    render(<WorkflowTemplateLauncher projectName="demo" />);
    await screen.findByText("Manga storyboard");
    fireEvent.click(screen.getByTestId("workflow-template-rate-manga-1-5"));
    await waitFor(() => expect(rate).toHaveBeenCalledWith("manga-1", 5));
  });

  it("translates unpublished template errors instead of exposing the error code", async () => {
    vi.spyOn(API, "deriveWorkflowTemplate").mockRejectedValue(new Error("workflow_template_not_published"));
    render(<WorkflowTemplateLauncher projectName="demo" />);

    const useButtons = await screen.findAllByRole("button", { name: "creation_skill_use" });
    fireEvent.click(useButtons[0]);

    expect(await screen.findByText("这个创作 Skill 尚未发布，暂时无法使用。")).toBeInTheDocument();
    expect(screen.queryByText("workflow_template_not_published")).not.toBeInTheDocument();
  });
});
