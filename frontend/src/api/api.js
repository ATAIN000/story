/**
 * api.js —— 后端端点薄封装（只管传输，不管字段语义；字段语义见 adapters.js）。
 * P6 端点全量：plan / generate(mode) / deletePlan / intervene / interventions /
 * hitlRespond / trainingStats / paragraphRewrite / characters（backend/main.py）。
 * P8 抽卡开局：gachaDraw / gachaConfirm / projectInit。
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
    const err = new Error(detail)
    err.status = r.status   // P10.4：调用方按状态码分支（如 gacha confirm 409 项目重名）
    throw err
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

  /* --- 抽卡开局（P8.3-P8.5；confirm body = draw 返回的卡原样，含 synth 的 genre.yaml） --- */
  /* P10.4：projectName 给了则平铺 project_name 键开新项目（重名 → 409，失败零副作用） */
  gachaDraw: (mode = 'library', lock = null) => post('/api/gacha/draw', { mode, lock }),
  gachaConfirm: (card, projectName = null) =>
    post('/api/gacha/confirm', projectName ? { ...card, project_name: projectName } : card),
  projectInit: (genre, culture) => post('/api/project/init', { genre, culture }),

  /* --- 多项目（P10.4） --- */
  projects: () => req('/api/projects'),
  openProject: (name) => post('/api/projects/open', { name }),
  /* 导出是浏览器直接下载（FileResponse zip），不走 req JSON 通道，只给 URL */
  exportProjectUrl: (name) => `/api/projects/${encodeURIComponent(name)}/export`,
  /* P10.6 导入：multipart 上传。FormData 边界由浏览器生成，必须置空 headers
     覆盖掉 req 默认的 Content-Type: application/json */
  importProject: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return req('/api/projects/import', { method: 'POST', headers: {}, body: fd })
  },

  /* --- 设置（P6.10 B9/B10） --- */
  settings: () => req('/api/settings'),
  updateSettings: (patch) => post('/api/settings', patch),
  testLlm: (body = {}) => post('/api/settings/test_llm', body),
}
