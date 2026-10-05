import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "@/i18n";
import { GalleryToolbar } from "./GalleryToolbar";

function renderToolbar(props: Partial<React.ComponentProps<typeof GalleryToolbar>> = {}) {
  return render(
    <I18nextProvider i18n={i18n}>
      <GalleryToolbar title="Characters" count={3} onGenerateDesigns={vi.fn()} {...props} />
    </I18nextProvider>,
  );
}

describe("GalleryToolbar relationship entry", () => {
  it("renders the relationship graph button before the library action", () => {
    const onViewRelations = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <GalleryToolbar title="Characters" count={2} onViewRelations={onViewRelations} onPickFromLibrary={vi.fn()} />
      </I18nextProvider>,
    );

    const buttons = screen.getAllByRole("button");
    expect(buttons[0]?.textContent).toMatch(/查看关系图谱|View Relationship Graph|Xem sơ đồ quan hệ/i);
    fireEvent.click(buttons[0]!);
    expect(onViewRelations).toHaveBeenCalledTimes(1);
  });
});

describe("GalleryToolbar batch design generation", () => {
  it("offers missing-only and full regeneration scopes", () => {
    const onGenerateDesigns = vi.fn();
    renderToolbar({ count: 3, pendingDesignCount: 2, onGenerateDesigns });

    const trigger = screen.getByRole("button", {
      name: /一键生成设计图|Generate design image|Tạo ảnh thiết kế/i,
    });
    fireEvent.click(trigger);

    expect(
      screen.getByRole("menu", {
        name: /批量生成设计图|Batch generate design images|Tạo hàng loạt ảnh thiết kế/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/待生成 2 个|2 pending|Còn 2 mục/i)).toBeInTheDocument();
    expect(screen.getByText(/共 3 个|3 total|Tổng 3 mục/i)).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("menuitem", {
        name: /仅生成缺失设计图|Generate missing only|Chỉ tạo ảnh còn thiếu/i,
      }),
    );
    expect(onGenerateDesigns).toHaveBeenCalledWith("missing");

    fireEvent.click(trigger);
    fireEvent.click(
      screen.getByRole("menuitem", {
        name: /全部重新生成|Regenerate all|Tạo lại tất cả/i,
      }),
    );
    expect(onGenerateDesigns).toHaveBeenLastCalledWith("all");
  });

  it("disables missing-only once every design exists but keeps regeneration available", () => {
    renderToolbar({ count: 3, pendingDesignCount: 0 });

    fireEvent.click(
      screen.getByRole("button", {
        name: /一键生成设计图|Generate design image|Tạo ảnh thiết kế/i,
      }),
    );

    expect(screen.getByText(/已全部生成|All generated|Đã tạo đủ/i)).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", {
        name: /仅生成缺失设计图|Generate missing only|Chỉ tạo ảnh còn thiếu/i,
      }),
    ).toBeDisabled();
    expect(
      screen.getByRole("menuitem", {
        name: /全部重新生成|Regenerate all|Tạo lại tất cả/i,
      }),
    ).not.toBeDisabled();
  });

  it("reports the trigger collapsed while disabled even if the menu was opened", () => {
    const onGenerateDesigns = vi.fn();
    const props = { count: 3, pendingDesignCount: 0, onGenerateDesigns };
    const view = render(
      <I18nextProvider i18n={i18n}>
        <GalleryToolbar title="Characters" {...props} />
      </I18nextProvider>,
    );
    const findTrigger = () =>
      screen.getByRole("button", {
        name: /一键生成设计图|Generate design image|Tạo ảnh thiết kế/i,
      });

    fireEvent.click(findTrigger());
    expect(findTrigger()).toHaveAttribute("aria-expanded", "true");

    view.rerender(
      <I18nextProvider i18n={i18n}>
        <GalleryToolbar title="Characters" {...props} generateDesignsDisabled />
      </I18nextProvider>,
    );
    expect(findTrigger()).toHaveAttribute("aria-expanded", "false");
  });
});