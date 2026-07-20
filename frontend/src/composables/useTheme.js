// useTheme —— 双主题（story.html :580-588 主题切换的 Vue 版 + D7 修复）。
// - data-theme="day|night" 挂在 document.body 上（与 story.html CSS 选择器口径一致）
// - 初始：localStorage 记忆优先，否则 prefers-color-scheme 检测（8.4-#2 修复）
// - 切换时派发自定义事件 'storyos:theme-changed'：P6.9 图谱/时间线等图表类
//   组件监听此事件重读取色并重绘（对应 story.html refreshPalette + 8.2-#6
//   「所有图形组件统一订阅主题变量」）。
import { ref } from 'vue'

const STORAGE_KEY = 'storyos-theme'
export const THEME_EVENT = 'storyos:theme-changed'

const theme = ref('day')

function detectInitial() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'day' || saved === 'night') return saved
  } catch { /* localStorage 不可用时退回系统检测 */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches
    ? 'night' : 'day'
}

function apply(t) {
  theme.value = t
  document.body.dataset.theme = t
  try { localStorage.setItem(STORAGE_KEY, t) } catch { /* 忽略持久化失败 */ }
  window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: t }))
}

/** 应用启动时调用一次（main.js，mount 前），避免首屏主题闪跳 */
export function initTheme() {
  apply(detectInitial())
}

export function useTheme() {
  return {
    theme,
    toggleTheme: () => apply(theme.value === 'night' ? 'day' : 'night'),
    isNight: () => theme.value === 'night',
  }
}
