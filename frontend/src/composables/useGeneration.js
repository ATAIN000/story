// useGeneration —— 生成中全局锁（评审 8.3-#3：后端全局单例 engine 不支持并发
// 生成，前端必须显式处理「生成中点再次生成/段落操作」）。
// 模块级单例：锁期间生成按钮禁用；写作台段落操作可据 generating 做只读提示。
import { ref, readonly } from 'vue'

const _generating = ref(false)
const _stage = ref('') // 供 topbar stage-pill 展示（如「第 4 章 · 生成中」）

export function useGeneration() {
  /**
   * 在全局锁内执行一个生成类异步操作；已在锁中则直接拒绝（返回 undefined）。
   * 用法：await runGeneration(async () => { ...await api.generate()... })
   */
  async function runGeneration(fn, stage = '') {
    if (_generating.value) return undefined
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
