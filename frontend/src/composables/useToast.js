// useToast —— 全局轻提示（story.html :533 toast() 的 Vue 版）。
// 模块级单例：任何组件/composable 调用共享同一队列，由 ToastHost 渲染。
import { reactive } from 'vue'

let seq = 0
const toasts = reactive([])

function push(message, type = '', ttl = 3200) {
  const id = ++seq
  toasts.push({ id, message: String(message), type })
  setTimeout(() => {
    const i = toasts.findIndex(t => t.id === id)
    if (i >= 0) toasts.splice(i, 1)
  }, ttl)
}

export function useToast() {
  return {
    toasts,
    toast: (m, ttl) => push(m, '', ttl),
    toastError: (m, ttl = 4200) => push(m, 'err', ttl),
  }
}
