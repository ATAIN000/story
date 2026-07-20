// useGeneration —— 生成中全局锁（评审 8.3-#3：后端全局单例 engine 不支持并发
// 生成，前端必须显式处理「生成中点再次生成/段落操作」）。
// 模块级单例：锁期间生成按钮禁用；写作台段落操作可据 generating 做只读提示。
import { ref, readonly } from 'vue'

const _generating = ref(false)
const _stage = ref('') // 供 topbar stage-pill 展示（如「第 4 章 · 生成中」）

/**
 * 重入拒绝标记（P6.6 传导修复）：runGeneration 在锁中被调用时返回它。
 * 旧实现返回 undefined，与「fn 恰好返回 undefined」不可区分，调用方无法
 * 识别拒绝并提示「正在生成中」；用 Symbol 保证不与任何 fn 返回值碰撞。
 */
export const GEN_REJECTED = Symbol('storyos.gen-rejected')

export function useGeneration() {
  /**
   * 在全局锁内执行一个生成类异步操作；已在锁中则拒绝并返回 GEN_REJECTED。
   * 用法：const r = await runGeneration(fn, stage)；r === GEN_REJECTED → toast。
   */
  async function runGeneration(fn, stage = '') {
    if (_generating.value) return GEN_REJECTED
    _generating.value = true
    _stage.value = stage
    try {
      return await fn()
    } finally {
      _generating.value = false
      _stage.value = ''
    }
  }

  return {
    generating: readonly(_generating),
    stage: readonly(_stage),
    runGeneration,
  }
}
