import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Turn } from "@/types";
import { MessageRail, messageAnchorId } from "./MessageRail";

describe("MessageRail", () => {
  const turns: Turn[] = [
    { type: "assistant", uuid: "a-1", content: [{ type: "text", text: "回复" }] },
    { type: "user", uuid: "u-1", content: [{ type: "text", text: "第一条任务" }] },
    { type: "assistant", uuid: "a-2", content: [{ type: "text", text: "处理第一条" }] },
    { type: "user", uuid: "u-2", content: [{ type: "text", text: "第二条任务内容很长，用于验证悬停时仍然会被截断为紧凑预览，不遮挡主要内容。" }] },
  ];

  beforeEach(() => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  it("renders one centered rail node per non-empty user message", () => {
    const { container } = render(<MessageRail turns={turns} />);
    const rail = screen.getByRole("navigation", { name: "消息导航" });
    const nodes = container.querySelectorAll("[data-message-rail-node]");

    expect(screen.getByRole("navigation", { name: "消息导航" })).toBeInTheDocument();
    expect(container.querySelector("[data-message-rail-line]")).toBeInTheDocument();
    expect(rail).toHaveClass("top-1/2", "-translate-y-1/2");
    expect(nodes).toHaveLength(2);
    expect(nodes[0]).toHaveAttribute("data-current", "false");
    expect(nodes[1]).toHaveAttribute("data-current", "true");
  });

  it("uses a dark hover color for an unselected message and hides its card after leaving", () => {
    render(<MessageRail turns={turns} />);
    const node = screen.getByRole("button", { name: "跳转到第 1 条消息" });

    expect(node.querySelector("span")).toHaveStyle({ background: "var(--color-text-4)" });
    fireEvent.mouseEnter(node);
    expect(node.querySelector("span")).toHaveStyle({ background: "var(--color-text-2)" });
    const card = screen.getByRole("tooltip");
    expect(card).toHaveTextContent("第一条任务");
    expect(card).toHaveTextContent("跳转到第 1 条消息");

    fireEvent.mouseLeave(node);
    expect(node.querySelector("span")).toHaveStyle({ background: "var(--color-text-4)" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("keeps the message card visible while the node is focused", () => {
    render(<MessageRail turns={turns} />);
    const node = screen.getByRole("button", { name: "跳转到第 1 条消息" });

    fireEvent.focus(node);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    fireEvent.blur(node);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("smoothly scrolls to and marks the selected user message", () => {
    const target = document.createElement("div");
    target.id = messageAnchorId(turns[1], 1);
    document.body.appendChild(target);
    const scrollIntoView = vi.spyOn(target, "scrollIntoView");
    render(<MessageRail turns={turns} />);

    const node = screen.getByRole("button", { name: "跳转到第 1 条消息" });
    fireEvent.click(node);

    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "center",
      inline: "nearest",
    });
    expect(node).toHaveAttribute("aria-current", "location");
    expect(node).toHaveAttribute("data-active", "true");
    expect(node).toHaveAttribute("data-current", "true");
    expect(node.querySelector("span")).toHaveStyle({ background: "var(--color-text)" });
  });
});
