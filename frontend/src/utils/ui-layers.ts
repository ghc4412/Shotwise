export const UI_LAYERS = {
  assistantLocalPopover: "z-20",
  workspaceFloating: "z-30",
  workspacePopover: "z-40",
  /** 助手浮窗内部 portal 到 body 的 popover：须高于 workspaceFloating(z-30) 的浮窗本身 */
  assistantPopover: "z-45",
  modal: "z-50",
  toast: "z-60",
} as const;
