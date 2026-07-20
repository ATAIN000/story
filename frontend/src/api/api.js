/**
 * api.js —— 后端端点薄封装（只管传输，不管字段语义；字段语义见 adapters.js）。
 * P6 端点全量：plan / generate(mode) / deletePlan / intervene / interventions /
 * hitlRespond / trainingStats / paragraphRewrite / characters（backend/main.py）。
 */

const BASE = ''

async function req(path, options = {}) {
  const r = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!r.ok) {
    let detail = `${r.status}`
    try { detail = (await r.json()).detail || detail } catch { /* 非 JSON 错误体 */ }
    throw new Error(detail)
  }
  return r.json()
}

const post = (path, body) =>
  req(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  /* --- 基础 --- */
  config: () => req('/api/config'),
  project: () => req('/api/project'),
  rollback: (tick) => post('/api/project/rollback', { tick }),
  reset: () => post('/api/project/reset'),

  /* --- 生成（P6.2 两阶段：plan → confirm；mode 缺省 auto 与旧调用一致） --- */
  generate: (mode = 'auto') => post('/api/project/generate', { mode }),
  plan: () => post('/api/project/plan'),
  deletePlan: () => req('/api/project/plan', { method: 'DELETE' }),

  /* --- HITL 介入（P5.10 / P6.1） --- */
  intervene: (type, payload = {}, reason = '') =>
    post('/api/intervene', { type, payload, reason }),
  interventions: () => req('/api/interventions'),
  hitlRespond: (requestId, response) =>
    post('/api/hitl/respond', { request_id: requestId, response }),

  /* --- 训练统计（P6.1 B5） --- */
  trainingStats: () => req('/api/training/stats'),

  /* --- 段落重写（P6.3 B2；para_index 协议见 adapters.splitParas） --- */
  paragraphRewrite: (chapter, paraIndex, direction = '') =>
    post('/api/paragraph/rewrite', { chapter, para_index: paraIndex, direction }),

  /* --- 角色卡（P6.4 B4） --- */
  characters: () => req('/api/characters'),

  /* --- Meta-Generator（题材配置，FE-4 用） --- */
  metaConfig: (intent) => post('/api/meta/config', intent),

  /* --- 设置（P6.10 B9/B10） --- */
  settings: () => req('/api/settings'),
  updateSettings: (patch) => post('/api/settings', patch),
  testLlm: (body = {}) => post('/api/settings/test_llm', body),
}
