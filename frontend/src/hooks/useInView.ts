import { useEffect, useRef, useState } from "react";

interface UseInViewOptions {
  /** 元素可见比例阈值（0-1），默认 0.12 */
  threshold?: number;
  /** 视口外扩/收缩（IntersectionObserver rootMargin），默认从底部收 8% 触发 */
  rootMargin?: string;
  /** 是否只触发一次（触发后断开观察），默认 true */
  once?: boolean;
}

/**
 * 滚动进入视口检测（IntersectionObserver 封装，用于滚动动效层的入场动画）。
 *
 * - 触发后默认断开观察，只入场一次，避免反复播放；
 * - jsdom / 不支持 IntersectionObserver 的环境直接视为可见，测试与老浏览器不白屏；
 * - `prefers-reduced-motion` 的降级由调用方（CSS transition / Reveal 组件）负责，
 *   本 hook 只负责「进入视口」这件事。
 */
export function useInView<T extends HTMLElement>(options: UseInViewOptions = {}) {
  const { threshold = 0.12, rootMargin = "0px 0px -8% 0px", once = true } = options;
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      // jsdom / 老浏览器无 IO：仍走异步路径，避免同步 setState 触发 cascading render
      const id = window.setTimeout(() => setInView(true), 0);
      return () => window.clearTimeout(id);
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          setInView(true);
          if (once) io.disconnect();
          break;
        }
      },
      { threshold, rootMargin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [threshold, rootMargin, once]);

  return { ref, inView };
}
