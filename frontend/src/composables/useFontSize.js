// useFontSize —— 手稿正文字号共享状态（story.html :589-595 口径：15-21px，默认 17）。
// 模块级单例：topbar A−/A＋ 控件（App.vue）调 inc/dec，手稿段落
// （WriteView/ManuscriptPanel）只读消费；localStorage 记忆（键 storyos.fs），
// 仅影响 .para 渲染字号，不落库、不进后端。
import { ref, readonly } from 'vue'

const KEY = 'storyos.fs'
const MIN = 15
const MAX = 21
const clamp = n => Math.min(MAX, Math.max(MIN, n))

function load() {
  try {
    const v = parseInt(localStorage.getItem(KEY), 10)
    return Number.isFinite(v) ? clamp(v) : 17
  } catch { return 17 } // 隐私模式等读失败 → 默认 17
}

const _fs = ref(load())

export function useFontSize() {
  function setFont(px) {
    _fs.value = clamp(Math.round(Number(px) || 17))
    try { localStorage.setItem(KEY, String(_fs.value)) } catch { /* 写失败忽略 */ }
  }
  return {
    fsSize: readonly(_fs),
    setFont,
    incFont: () => setFont(_fs.value + 1),
    decFont: () => setFont(_fs.value - 1),
  }
}
