import { useRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspaceNotificationsDrawer } from "@/components/layout/WorkspaceNotificationsDrawer";
import { useAppStore } from "@/stores/app-store";

function renderDrawer() {
  function Harness() {
    const anchorRef = useRef<HTMLDivElement>(null);
    return (
      <div ref={anchorRef}>
        <WorkspaceNotificationsDrawer
          open
          onClose={vi.fn()}
          anchorRef={anchorRef}
          onNavigate={vi.fn()}
        />
      </div>
    );
  }

  return render(<Harness />);
}

describe("WorkspaceNotificationsDrawer", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
  });

  it("clears all workspace notifications from the header action", () => {
    useAppStore.getState().pushWorkspaceNotification({ text: "第一条通知" });
    useAppStore.getState().pushWorkspaceNotification({ text: "第二条通知" });

    renderDrawer();

    fireEvent.click(screen.getByRole("button", { name: "清除全部" }));

    expect(useAppStore.getState().workspaceNotifications).toEqual([]);
    expect(screen.queryByRole("button", { name: "清除全部" })).not.toBeInTheDocument();
    expect(screen.getByText("当前没有通知")).toBeInTheDocument();
  });
});
