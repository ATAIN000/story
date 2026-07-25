// useGeneration —— 生成中全局锁 + 生成态 store（P23.3：切走再回来状态丢失修复）。
//
// 历史版本（评审 8.3-#3）只是模块级布尔锁 _generating。问题：WriteView 的 flow/
// genReport 是组件局部 ref，App.vue 动态组件无 keep-alive，切走即 unmount，进度态
// 丢失；且后端无"查询进行中生成"的接口，切回来无处恢复。
//
// 现在改造：模块级持完整生成态 _genState，runGeneration 走 /generate/async 启动后台
// 任务 + 轮询 /generation-status 更新态；WriteView 只读 _genState 渲染（即便组件
// 销毁重建，全局态有值就能渲染）。syncFromBackend 供 WriteView mount 时调，从后端
// 恢复"正在生成第 N 章"。
import { ref, readonly, computed } from 'vue'
import { api } from '../api/api'

/**
 * 重入拒绝标记（P6.6 传导修复）：runGeneration 在锁中被调用时返回它。
 * 旧实现返回 undefined，与「fn 恰好返回 undefined」不可区分，调用方无法
 * 识别拒绝并提示「正在生成中」；用 Symbol 保证不与任何 fn 返回值碰撞。
 */
export const GEN_REJECTED = Symbol('storyos.gen-rejected')

// 模块级单例：跨组件、跨视图存活
const _genState = ref({
  busy: false,          // 后端有进行中的生成任务
  chapterNo: null,      // 正在生成的章号
  startedAt: null,
  stage: '',            // started/generating/done/error
  finished: false,
  result: null,         // 完成后的章节记录
  error: null,
  projectName: null,
})
const _stage = ref('')  // 顶栏 stage-pill 展示文案（如「第 4 章 · 生成中」）

let _pollTimer = null   // 轮询定时器句柄

const POLL_INTERVAL = 4000  // 4 秒一轮；~10 分钟约 150 次轻量 GET

function _applyBackendSnapshot(snap) {
  if (!snap) return
  _genState.value = {
    busy: snap.busy,
    chapterNo: snap.chapter_no,
    startedAt: snap.started_at,
    stage: snap.stage || '',
    finished: snap.finished,
    result: snap.result,
    error: snap.error,
    projectName: snap.project_name,
  }
}

function _stopPolling() {
  if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
}

let _ws = null   // WebSocket 句柄

function _stopWS() {
  if (_ws) { try { _ws.close() } catch { /* ignore */ }; _ws = null }
}

/** 轮询回退（WS 失败时用） */
function _startPolling(onFinish) {
  _stopPolling()
  const tick = async () => {
    try {
      const snap = await api.generationStatus()
      _applyBackendSnapshot(snap)
      if (snap.finished) {
        _stopPolling()
        if (typeof onFinish === 'function') onFinish(snap)
        return
      }
    } catch { /* 轮询失败不致命，下一轮重试 */ }
    _pollTimer = setTimeout(tick, POLL_INTERVAL)
  }
  _pollTimer = setTimeout(tick, POLL_INTERVAL)
}

function _startWS(onFinish, onProgress) {
  _stopWS()
  _stopPolling()
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${proto}//${location.host}/api/project/generate/stream`
  const ws = new WebSocket(wsUrl)
  _ws = ws
  let wsFailed = false

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data)
      if (msg.type === 'progress') {
        // 进度日志条目（stage + detail）
        if (typeof onProgress === 'function') onProgress(msg)
        // 更新全局 stage
        _genState.value = { ..._genState.value, stage: msg.stage, stageDetail: msg.detail || '' }
      } else if (msg.type === 'status') {
        // 状态更新（stage/busy）
        _genState.value = { ..._genState.value, stage: msg.stage || '', stageDetail: msg.detail || '' }
      } else if (msg.type === 'complete') {
        _stopWS()
        _stage.value = ''
        if (typeof onFinish === 'function') onFinish({ finished: true, result: msg.result })
      } else if (msg.type === 'error') {
        _stopWS()
        _stage.value = ''
        if (typeof onFinish === 'function') onFinish({ finished: true, error: msg.msg })
      } else if (msg.type === 'idle') {
        // 无在跑任务（可能已结束），用 snapshot 恢复
        _stopWS()
        if (msg.snapshot) _applyBackendSnapshot(msg.snapshot)
      }
    } catch { /* ignore parse errors */ }
  }
  ws.onerror = () => {
    // WS 失败 → 回退轮询
    if (!wsFailed) {
      wsFailed = true
      _stopWS()
      _startPolling(onFinish)
    }
  }
  ws.onclose = () => {
    // WS 关闭且非 complete/error → 回退轮询（防丢消息）
    if (!wsFailed && _genState.value.busy) {
      _startPolling(onFinish)
    }
  }
}

/**
 * 从后端同步生成态（WriteView mount 时调）：查 /generation-status，若 busy 则
 * 恢复 _genState 并启动轮询；onFinish 在轮询到 finished 时回调（收尾进 review）。
 */
async function syncFromBackend(onFinish, onProgress) {
  try {
    const snap = await api.generationStatus()
    _applyBackendSnapshot(snap)
    if (snap.busy) {
      _stage.value = `第 ${snap.chapter_no} 章 · 生成中`
      _startWS(onFinish, onProgress)   // WS 优先，失败回退轮询
      return true   // 恢复了进行中的生成
    }
    // 后端无在跑任务，但本地态可能残留（如后端重启）→ 清场
    if (_genState.value.busy) {
      _genState.value = { ..._genState.value, busy: false }
    }
  } catch { /* 查询失败忽略，不阻塞渲染 */ }
  return false
}

export function useGeneration() {
  /**
   * 在全局锁内执行一个生成类异步操作；已在锁中则拒绝并返回 GEN_REJECTED。
   *
   * 改造后（P23.3）：mode='async' 走后台任务 + 轮询；fn 返回最终章节记录。
   * 仍兼容旧同步用法（mode='sync' 或 fn 自行 await 同步接口），供回滚等非生成操作复用锁。
   *
   * 用法（章节生成，走异步）：
   *   const rec = await runGeneration({ async: true, mode: 'confirm', chapterNo: 5,
   *                                     stageLabel: '第 5 章 · 生成中' },
   *                                   async (snap) => { /* 轮询每轮回调，可选 *​/ },
   *                                   async (finalSnap) => { /* 完成回调 *​/ })
   * 用法（旧同步，如回滚）：
   *   await runGeneration(async () => { await api.rollback(tick) }, `回滚到 tick ${tick}`)
   */
  async function runGeneration(fnOrOpts, stage = '', onPoll, onFinish) {
    // 兼容旧签名：runGeneration(fn, stage)
    if (typeof fnOrOpts === 'function') {
      if (_genState.value.busy) return GEN_REJECTED
      _stage.value = stage
      // 旧同步路径不设 _genState.busy（那是后端任务标志），用单独的本地执行锁
      // 这里复用 _stage 作顶栏指示；执行完清掉
      try {
        return await fnOrOpts()
      } finally {
        _stage.value = ''
      }
    }

    // 新签名：runGeneration({ async, mode, chapterNo, stageLabel }, onPoll, onFinish)
    const opts = fnOrOpts || {}
    if (_genState.value.busy) return GEN_REJECTED

    if (opts.async) {
      // 异步通道：启动后台任务 + 轮询
      try {
        const started = await api.generateAsync(opts.mode || 'confirm')
        _genState.value = {
          ..._genState.value,
          busy: true,
          chapterNo: started.chapter_no,
          startedAt: started.started_at,
          stage: 'started',
          finished: false,
          result: null,
          error: null,
          projectName: null,
        }
        _stage.value = opts.stageLabel || `第 ${started.chapter_no} 章 · 生成中`
      } catch (e) {
        // 启动失败（如 409 已在生成）：尝试 sync 一下看是否真在跑
        await syncFromBackend(onFinish)
        if (_genState.value.busy) return GEN_REJECTED
        throw e
      }
      // 启动 WS 进度推送（失败回退轮询）；onFinish 在收到 complete 时触发
      return new Promise((resolve, reject) => {
        _startWS(async (finalSnap) => {
          _stage.value = ''
          try {
            if (typeof onFinish === 'function') {
              const r = await onFinish(finalSnap)
              resolve(r)
            } else if (finalSnap.result) {
              resolve(finalSnap.result)
            } else if (finalSnap.error) {
              reject(new Error(finalSnap.error))
            } else {
              resolve(finalSnap.result)
            }
          } catch (err) { reject(err) }
        }, typeof onPoll === 'function' ? onPoll : null)
      })
    }

    // 默认：当作旧同步 fn 调用
    if (typeof fnOrOpts === 'function') {
      if (_genState.value.busy) return GEN_REJECTED
      _stage.value = stage
      try { return await fnOrOpts() } finally { _stage.value = '' }
    }
    throw new Error('useGeneration.runGeneration: 参数不合法')
  }

  return {
    generating: readonly(computed(() => _genState.value.busy || _stage.value !== '')),
    genState: readonly(_genState),
    stage: readonly(_stage),
    runGeneration,
    syncFromBackend,
    stopPolling: _stopPolling,
    stopWS: _stopWS,
  }
}
