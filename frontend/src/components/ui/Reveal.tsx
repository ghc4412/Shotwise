import { type CSSProperties, type ReactNode } from "react";
import { useInView } from "@/hooks/useInView";

interface RevealProps {
  children: ReactNode;
  className?: string;
  /** 入场延迟（ms），用于 stagger 依次浮现 */
  delay?: number;
  /** 元素可见比例阈值 */
  threshold?: number;
  /** 进场方向 */
  from?: "up" | "down" | "left" | "right" | "none";
}

const FROM_TRANSFORM: Record<NonNullable<RevealProps["from"]>, string> = {
  up: "translateY(22px)",
  down: "translateY(-22px)",
  left: "translateX(24px)",
  right: "translateX(-24px)",
  none: "none",
};

/**
 * 滚动入场容器：进入视口时上浮淡入。纯展示层，不阻塞内容渲染，
 * 不触发前元素始终在 DOM 中（SEO / 测试 / 无 IO 环境均可见）。
 * reduced-motion 降级由 `.reveal` 的媒体查询完成。
 */
export function Reveal({
  children,
  className = "",
  delay = 0,
  threshold,
  from = "up",
}: RevealProps) {
  const { ref, inView } = useInView<HTMLDivElement>({ threshold });

  const style: CSSProperties = {
    transitionDelay: delay > 0 ? `${delay}ms` : undefined,
    "--reveal-from": FROM_TRANSFORM[from],
  } as CSSProperties;

  return (
    <div
      ref={ref}
      data-reveal-visible={inView || undefined}
      className={`reveal ${className}`}
      style={style}
    >
      {children}
    </div>
  );
}
