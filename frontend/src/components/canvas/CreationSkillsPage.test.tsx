import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { CreationSkillsPage } from "./CreationSkillsPage";

vi.mock("lucide-react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("lucide-react")>();
  const Icon = ({ "data-testid": testId }: { "data-testid": string }) => <span data-testid={testId} />;
  return {
    ...actual,
    Check: () => <Icon data-testid="icon-check" />,
    Clock3: () => <Icon data-testid="icon-clock" />,
    DollarSign: () => <Icon data-testid="icon-dollar" />,
    FileText: () => <Icon data-testid="icon-file" />,
    Heart: () => <Icon data-testid="icon-heart" />,
    Layers3: () => <Icon data-testid="icon-layers" />,
    Loader2: () => <Icon data-testid="icon-loader" />,
    Paperclip: () => <Icon data-testid="icon-paperclip" />,
    Plus: () => <Icon data-testid="icon-plus" />,
    Search: () => <Icon data-testid="icon-search" />,
    Send: () => <Icon data-testid="icon-send" />,
    ShieldCheck: () => <Icon data-testid="icon-shield" />,
    Sparkles: () => <Icon data-testid="icon-sparkles" />,
    WandSparkles: () => <Icon data-testid="icon-wand" />,
    X: () => <Icon data-testid="icon-close" />,
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      typeof values?.message === "string" ? key + ": " + values.message : key,
  }),
}));

vi.mock("wouter", () => ({
  useLocation: () => ["/", vi.fn()],
}));

const compatibleSkill = {
  id: "novel-to-drama",
  version: 1,
  version_id: "novel-to-drama:v1",
  workflow_revision_id: "workflow-revision-1",
  title: "Official drama Skill",
  summary: "A server-provided Skill",
  category: "剧集",
  inputs: ["document"],
  outputs: ["videos"],
  review_required: true,
  compatibility: { compatible: true, supported_generation_modes: ["storyboard"] },
};

describe("CreationSkillsPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState({}, "", "/");
    window.localStorage.clear();
  });

  it("keeps a saved Skill after the page is remounted", async () => {
    vi.spyOn(API, "listCreationSkills").mockResolvedValue({ items: [] });

    const first = render(<CreationSkillsPage projectName="demo" />);
    const title = await screen.findByText("电影感镜头语言");
    const card = title.closest("article") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "creation_skills_market_save" }));

    expect(window.localStorage.getItem("shotwise-creation-skills-saved:demo")).toContain("cinematic-shot-language");

    first.unmount();
    render(<CreationSkillsPage projectName="demo" />);
    fireEvent.click(await screen.findByRole("button", { name: "creation_skills_market_tab_saved" }));

    expect(await screen.findByText("电影感镜头语言")).toBeInTheDocument();
  });

  it("renders 12 local Skills on the first page", async () => {
    vi.spyOn(API, "listCreationSkills").mockResolvedValue({ items: [] });

    render(<CreationSkillsPage projectName="demo" />);

    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(12));
    expect(screen.getAllByRole("article")).toHaveLength(12);
    expect(screen.getByRole("navigation", { name: "creation_skills_market_pagination" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "creation_skills_market_next" })).toBeEnabled();
  });

  it("paginates the Skill catalog by 12 cards", async () => {
    vi.spyOn(API, "listCreationSkills").mockResolvedValue({ items: [] });

    render(<CreationSkillsPage projectName="demo" />);

    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(12));
    fireEvent.click(screen.getByRole("button", { name: "creation_skills_market_next" }));

    expect(screen.getAllByRole("article")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "creation_skills_market_previous" })).toBeEnabled();
    expect(screen.getByText("creation_skills_market_page")).toBeInTheDocument();
  });

  it("renders only compatible Skills from the server catalog", async () => {
    vi.spyOn(API, "listCreationSkills").mockResolvedValue({
      items: [
        compatibleSkill,
        {
          ...compatibleSkill,
          id: "reference-image-video",
          version_id: "reference-image-video:v1",
          title: "Incompatible Skill",
          compatibility: { compatible: false, reasons: ["generation_mode"] },
        },
      ],
    });

    render(<CreationSkillsPage projectName="demo" />);

    expect(await screen.findByText("Official drama Skill")).toBeInTheDocument();
    expect(screen.queryByText("Incompatible Skill")).not.toBeInTheDocument();
    expect(screen.getByText("电影感镜头语言")).toBeInTheDocument();
  });

  it("shows a catalog error instead of local fallback Skills", async () => {
    vi.spyOn(API, "listCreationSkills").mockRejectedValue(new Error("catalog unavailable"));

    render(<CreationSkillsPage projectName="demo" />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("catalog unavailable"));
    expect(screen.getByText("电影感镜头语言")).toBeInTheDocument();
  });

  it("previews a plan using the server-frozen Skill version", async () => {
    vi.spyOn(API, "listCreationSkills").mockResolvedValue({ items: [compatibleSkill] });
    vi.spyOn(API, "listCreationResources").mockResolvedValue({ items: [{ id: "doc-1", label: "Source", type: "document" }] });
    vi.spyOn(API, "listMediaAssets").mockResolvedValue({ items: [] });
    const preview = vi.spyOn(API, "previewCreationPlan").mockResolvedValue({ plan_id: "plan-1", estimated_cost: 3, steps: ["videos"], compatibility_report: { compatible: true } });

    render(<CreationSkillsPage projectName="demo" />);
    const officialCard = (await screen.findByText("Official drama Skill")).closest("article");
    fireEvent.click(within(officialCard as HTMLElement).getByRole("button", { name: "creation_skills_prepare" }));
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "creation_plan_preview" }));

    await waitFor(() =>
      expect(preview).toHaveBeenCalledWith(
        "demo",
        expect.objectContaining({
          creation_skill_version_id: "novel-to-drama:v1",
          workflow_revision: "workflow-revision-1",
          resource_ids: ["doc-1"],
        }),
      ),
    );
  });

  it("keeps the entry focused on Creation Skills instead of an advanced workflow page", async () => {
    vi.spyOn(API, "listCreationSkills").mockResolvedValue({ items: [compatibleSkill] });

    render(<CreationSkillsPage projectName="demo" />);

    await screen.findByText("Official drama Skill");
    expect(screen.queryByRole("button", { name: "creation_skills_open_advanced_flow" })).not.toBeInTheDocument();
  });

  it("wires the creation prompt action menus", async () => {
    vi.spyOn(API, "listCreationSkills").mockResolvedValue({ items: [] });
    vi.spyOn(API, "listMediaAssets").mockResolvedValue({ items: [{ id: "asset-1", name: "Reference image", type: "image" }] });

    render(<CreationSkillsPage projectName="demo" />);

    fireEvent.click(await screen.findByRole("button", { name: "creation_prompt_add" }));
    expect(screen.getByRole("menuitem", { name: "creation_prompt_local_upload" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "creation_prompt_library_add" }));
    expect(await screen.findByRole("dialog", { name: "creation_prompt_library_add" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "creation_prompt_close" }));
    fireEvent.click(screen.getByRole("button", { name: "creation_prompt_model" }));
    expect(screen.getByRole("dialog", { name: "creation_prompt_model" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "creation_prompt_video" }));
    expect(screen.getByText("Veo 3.1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "creation_prompt_model" }));
    fireEvent.click(screen.getByRole("button", { name: "creation_prompt_mode" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /creation_prompt_manual_mode/ }));
    fireEvent.click(screen.getByRole("button", { name: "creation_prompt_mode" }));
    expect(screen.getByRole("menuitemradio", { name: /creation_prompt_manual_mode/ })).toHaveAttribute("aria-checked", "true");
  });

  it("preselects URL resources and carries episode context into the preview", async () => {
    window.history.pushState({}, "", "/?resource_id=doc-1&resource_type=document&episode=2");
    vi.spyOn(API, "listCreationSkills").mockResolvedValue({ items: [compatibleSkill] });
    vi.spyOn(API, "listCreationResources").mockResolvedValue({ items: [{ id: "doc-1", label: "Source", type: "document" }] });
    vi.spyOn(API, "listMediaAssets").mockResolvedValue({ items: [] });
    const preview = vi.spyOn(API, "previewCreationPlan").mockResolvedValue({ plan_id: "plan-1", estimated_cost: 3, steps: ["videos"], compatibility_report: { compatible: true } });

    render(<CreationSkillsPage projectName="demo" />);
fireEvent.click((await screen.findAllByRole("button", { name: "creation_skills_prepare" }))[0]);
    await waitFor(() => expect(screen.getByRole("checkbox")).toBeChecked());
    fireEvent.click(screen.getByRole("button", { name: "creation_plan_preview" }));

    await waitFor(() => expect(preview).toHaveBeenCalledWith("demo", expect.objectContaining({ parameters: { episode: 2 }, resource_ids: ["doc-1"] })));
  });

  it("confirms that a started Skill is now in the task radar", async () => {
    vi.spyOn(API, "listCreationSkills").mockResolvedValue({ items: [compatibleSkill] });
    vi.spyOn(API, "listCreationResources").mockResolvedValue({ items: [{ id: "doc-1", label: "Source", type: "document" }] });
    vi.spyOn(API, "listMediaAssets").mockResolvedValue({ items: [] });
    vi.spyOn(API, "previewCreationPlan").mockResolvedValue({ plan_id: "plan-1", estimated_cost: 3, steps: ["videos"], compatibility_report: { compatible: true } });
    vi.spyOn(API, "startCreationPlan").mockResolvedValue({ workflow_run_id: "run-1" });

    render(<CreationSkillsPage projectName="demo" />);
fireEvent.click((await screen.findAllByRole("button", { name: "creation_skills_prepare" }))[0]);
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "creation_plan_preview" }));
    fireEvent.click(await screen.findByRole("button", { name: "creation_plan_start" }));

    expect(await screen.findByRole("status")).toHaveTextContent("creation_plan_started");
    expect(screen.getByRole("status")).toHaveTextContent("task_hud_title");
  });
});
