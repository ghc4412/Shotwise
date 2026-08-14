import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { AgentDiscoveredModel, AgentModelMapEntry } from "@/types/agent-credential";

import { ModelMapEditor } from "../ModelMapEditor";

const discovered: AgentDiscoveredModel[] = [
  { model_id: "deepseek-v4-flash", display_name: "DeepSeek V4 Flash", context_window: 1048576 },
  { model_id: "deepseek-v4-pro", display_name: "DeepSeek V4 Pro", context_window: null },
];

function Harness({
  initial = [],
  models = [],
}: {
  initial?: AgentModelMapEntry[];
  models?: AgentDiscoveredModel[];
}) {
  const [entries, setEntries] = useState<AgentModelMapEntry[]>(initial);
  return (
    <ModelMapEditor
      entries={entries}
      onChange={setEntries}
      discoveredModels={models}
      onDiscover={vi.fn()}
      discovering={false}
      discoverError={null}
    />
  );
}

describe("ModelMapEditor", () => {
  it("renders header, buttons and empty hint when no entries", () => {
    render(<Harness />);
    expect(screen.getByText("模型映射")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /获取模型列表/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /添加模型/ })).toBeInTheDocument();
    expect(screen.getByText(/暂无模型映射/)).toBeInTheDocument();
  });

  it("adds an empty row on Add Model click", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /添加模型/ }));
    const menuName = screen.getByLabelText(/菜单显示名/) as HTMLInputElement;
    const requestModel = screen.getByLabelText(/实际请求模型/) as HTMLInputElement;
    const contextWindow = screen.getByLabelText(/上下文窗口/) as HTMLInputElement;
    expect(menuName.value).toBe("");
    expect(requestModel.value).toBe("");
    expect(contextWindow.value).toBe("");
  });

  it("shows no picker button before discovery", () => {
    render(<Harness initial={[{ menu_name: "", request_model: "", context_window: null }]} />);
    expect(screen.queryByLabelText(/选择模型/)).not.toBeInTheDocument();
  });

  it("picks a discovered model and autofills the row", () => {
    render(
      <Harness
        initial={[{ menu_name: "", request_model: "", context_window: null }]}
        models={discovered}
      />,
    );
    fireEvent.click(screen.getByLabelText(/选择模型/));
    fireEvent.click(screen.getByRole("button", { name: /DeepSeek V4 Flash/ }));

    expect((screen.getByLabelText(/菜单显示名/) as HTMLInputElement).value).toBe(
      "DeepSeek V4 Flash",
    );
    expect((screen.getByLabelText(/实际请求模型/) as HTMLInputElement).value).toBe(
      "deepseek-v4-flash",
    );
    expect((screen.getByLabelText(/上下文窗口/) as HTMLInputElement).value).toBe("1048576");
  });

  it("leaves context window empty when model has no context_window info", () => {
    render(
      <Harness
        initial={[{ menu_name: "", request_model: "", context_window: null }]}
        models={discovered}
      />,
    );
    fireEvent.click(screen.getByLabelText(/选择模型/));
    fireEvent.click(screen.getByRole("button", { name: /DeepSeek V4 Pro/ }));

    expect((screen.getByLabelText(/菜单显示名/) as HTMLInputElement).value).toBe("DeepSeek V4 Pro");
    expect((screen.getByLabelText(/实际请求模型/) as HTMLInputElement).value).toBe("deepseek-v4-pro");
    expect((screen.getByLabelText(/上下文窗口/) as HTMLInputElement).value).toBe("");
  });

  it("removes a row on delete", () => {
    render(
      <Harness
        initial={[
          { menu_name: "A", request_model: "a", context_window: null },
          { menu_name: "B", request_model: "b", context_window: null },
        ]}
      />,
    );
    expect(screen.getAllByLabelText(/菜单显示名/)).toHaveLength(2);
    fireEvent.click(screen.getAllByLabelText(/删除该映射/)[0]);
    const remaining = screen.getAllByLabelText(/菜单显示名/) as HTMLInputElement[];
    expect(remaining).toHaveLength(1);
    expect(remaining[0].value).toBe("B");
  });
});
