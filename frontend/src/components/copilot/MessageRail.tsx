import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { RefObject } from "react";
import type { Turn } from "@/types";
import { turnPlainText } from "./chat/utils";

interface MessageRailProps {
  turns: Turn[];
  scrollContainerRef?: RefObject<HTMLDivElement | null>;
}

export function messageAnchorId(turn: Turn, index: number): string {
  return `assistant-message-${turn.uuid || `turn-${index}`}`;
}

function previewText(turn: Turn): string {
  const text = turnPlainText(turn).replace(/\s+/g, " ").trim();
  return text.length > 96 ? `${text.slice(0, 96)}…` : text;
}

export function MessageRail({ turns, scrollContainerRef }: MessageRailProps) {
  const { t } = useTranslation("dashboard");
  const userMessages = useMemo(
    () =>
      turns
        .map((turn, index) => ({ turn, index, preview: previewText(turn) }))
        .filter(({ turn, preview }) => turn.type === "user" && preview.length > 0),
    [turns],
  );
  const messageKey = userMessages.map(({ turn, index }) => messageAnchorId(turn, index)).join("|");
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [currentIndex, setCurrentIndex] = useState<number | null>(null);

  useEffect(() => {
    const container = scrollContainerRef?.current;
    if (!container || userMessages.length === 0) return;

    let frame = 0;
    const updateCurrentMessage = () => {
      frame = 0;
      const containerRect = container.getBoundingClientRect();
      const viewportCenter = containerRect.top + container.clientHeight / 2;
      let nearestIndex: number | null = null;
      let nearestDistance = Number.POSITIVE_INFINITY;

      userMessages.forEach(({ turn, index }, messageIndex) => {
        const message = document.getElementById(messageAnchorId(turn, index));
        if (!message) return;
        const rect = message.getBoundingClientRect();
        const distance = Math.abs(rect.top + rect.height / 2 - viewportCenter);
        if (distance < nearestDistance) {
          nearestDistance = distance;
          nearestIndex = messageIndex;
        }
      });

      if (nearestIndex !== null) {
        setCurrentIndex((previous) => (previous === nearestIndex ? previous : nearestIndex));
      }
    };
    const scheduleUpdate = () => {
      if (frame === 0) frame = window.requestAnimationFrame(updateCurrentMessage);
    };

    updateCurrentMessage();
    container.addEventListener("scroll", scheduleUpdate, { passive: true });
    window.addEventListener("resize", scheduleUpdate);

    return () => {
      container.removeEventListener("scroll", scheduleUpdate);
      window.removeEventListener("resize", scheduleUpdate);
      if (frame !== 0) window.cancelAnimationFrame(frame);
    };
  }, [messageKey, scrollContainerRef, userMessages]);

  if (userMessages.length === 0) return null;

  const activeIndex = currentIndex !== null && currentIndex < userMessages.length ? currentIndex : userMessages.length - 1;

  const jumpToMessage = (index: number, messageIndex: number) => {
    setCurrentIndex(messageIndex);
    const message = document.getElementById(messageAnchorId(turns[index], index));
    message?.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
  };

  return (
    <nav
      aria-label={t("message_rail_label")}
      className="pointer-events-none absolute right-1.5 top-1/2 z-10 flex h-[68%] min-h-36 w-8 -translate-y-1/2 items-center justify-center overflow-visible"
    >
      <div
        className="relative flex h-full w-8 flex-col justify-evenly overflow-visible py-3"
        data-message-rail="true"
      >
        <span
          aria-hidden="true"
          data-message-rail-line="true"
          className="pointer-events-none absolute bottom-0 left-1/2 top-0 w-px -translate-x-1/2"
          style={{ background: "var(--color-hairline)" }}
        />

        {userMessages.map(({ turn, index, preview }, messageIndex) => {
          const isHovered = hoveredIndex === messageIndex;
          const isCurrent = activeIndex === messageIndex;
          const label = t("message_rail_jump", { count: messageIndex + 1 });
          const nodeColor = isCurrent
            ? "var(--color-text)"
            : isHovered
              ? "var(--color-text-2)"
              : "var(--color-text-4)";
          return (
            <div
              key={messageAnchorId(turn, index)}
              className="relative flex min-h-8 flex-1 items-center justify-center"
            >
              {isHovered && (
                <div
                  role="tooltip"
                  className="pointer-events-none absolute right-full top-1/2 mr-3 max-h-32 w-72 -translate-y-1/2 overflow-hidden rounded-xl border px-3 py-2.5 text-left shadow-xl backdrop-blur-md"
                  style={{
                    borderColor: isCurrent ? "var(--color-hairline-strong)" : "var(--color-hairline-soft)",
                    background: "var(--color-shell-panel)",
                    color: "var(--color-text-2)",
                  }}
                >
                  <p
                    className="line-clamp-2 text-[12px] font-medium leading-[1.45]"
                    style={{ color: "var(--color-text)" }}
                  >
                    {preview}
                  </p>
                  <div className="mt-1 truncate text-[10px] leading-[1.3]" style={{ color: "var(--color-text-3)" }}>
                    {label}
                  </div>
                </div>
              )}
              <button
                type="button"
                aria-label={label}
                aria-current={isCurrent ? "location" : undefined}
                title={label}
                onClick={() => jumpToMessage(index, messageIndex)}
                onMouseEnter={() => setHoveredIndex(messageIndex)}
                onMouseLeave={() => setHoveredIndex(null)}
                onFocus={() => setHoveredIndex(messageIndex)}
                onBlur={() => setHoveredIndex(null)}
                className="group pointer-events-auto relative flex h-8 w-8 items-center justify-center rounded-full focus-ring"
                data-message-rail-node="true"
                data-active={isCurrent ? "true" : "false"}
                data-current={isCurrent ? "true" : "false"}
              >
                <span
                  aria-hidden="true"
                  className={`relative z-[1] rounded-full transition-[width,height,background-color,box-shadow] duration-150 motion-reduce:transition-none ${
                    isCurrent ? "h-3 w-3 motion-safe:animate-pulse" : isHovered ? "h-2.5 w-2.5" : "h-2 w-2"
                  }`}
                  style={{
                    background: nodeColor,
                    boxShadow: isCurrent
                      ? "0 0 0 4px color-mix(in srgb, var(--color-text) 14%, transparent)"
                      : isHovered
                        ? "0 0 0 3px color-mix(in srgb, var(--color-text-2) 12%, transparent)"
                        : undefined,
                  }}
                />
              </button>
            </div>
          );
        })}
      </div>
    </nav>
  );
}
