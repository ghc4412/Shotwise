/**
 * 检测当前 SPA 是否运行在原生宿主（通过 preload 注入 `window.shotwise`）里。
 *
 * 宿主端 preload 在 `window.shotwise` 暴露一个标识对象（含
 * `platform === "desktop"` 与 `os`）；浏览器直接访问的部署不加载该 preload，
 * `window.shotwise` 始终是 undefined，因此存在性检查即可区分两种运行环境。
 *
 * 用法：
 *   if (isDesktop()) { ... }                       // 显隐 / 布局差异化
 *   const cmd = isMac() ? "⌘" : "Ctrl";             // 快捷键标签
 */

interface ShotwiseClientApi {
  readonly platform: "desktop";
  readonly os: string;
}

declare global {
  interface Window {
    shotwise?: ShotwiseClientApi & Record<string, unknown>;
  }
}

export function isDesktop(): boolean {
  return typeof window !== "undefined" && window.shotwise?.platform === "desktop";
}

export function isMac(): boolean {
  return typeof window !== "undefined" && window.shotwise?.os === "darwin";
}

export function isWindows(): boolean {
  return typeof window !== "undefined" && window.shotwise?.os === "win32";
}
