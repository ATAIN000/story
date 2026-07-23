/**
 * api.js —— 后端端点薄封装（只管传输，不管字段语义；字段语义见 adapters.js）。
 * P6 端点全量：plan / generate(mode) / deletePlan / intervene / interventions /
 * hitlRespond / trainingStats / paragraphRewrite / characters（backend/main.py）。
 * P20 抽卡开局：gachaBegin / gachaSessionConfirm / gachaCancel（session 模式）。
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

  /* --- 抽卡开局（P20：临时工作区 session 模式） ---
     begin(genre_name) → {session_id, genre_title, genre, culture}
     sessionDeriveCast(sid, worldview, language) → {cast: [...]}
     sessionCrossCheck(sid, worldview, cast) → {warnings: [...]}
     sessionConfirm(sid, projectName, {worldview?, cast?, macro_plan?}) → {ok, project}
     cancel(sid) → {ok}
     genres() → 题材列表（GET）
     synthGenre() → AI 合成题材卡 */
  /* P22：题材浏览（搜索/筛选/分页）。params: {q?, tags?, tier?, family?,
     offset?, limit?}——空值参数不上链（URLSearchParams 空串则不挂 ?）。 */
  gachaGenres: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return req('/api/gacha/genres' + (qs ? `?${qs}` : ''))
  },
  gachaSynth: () => post('/api/gacha/synth'),
  gachaBegin: (genreName, culture = null) =>
    post('/api/gacha/begin', culture ? { genre_name: genreName, culture } : { genre_name: genreName }),
  gachaSessionDeriveCast: (sid, worldview = {}, language = {}) =>
    post(`/api/gacha/${sid}/derive_cast`, { worldview, language }),
  gachaSessionCrossCheck: (sid, worldview = null, cast = null) =>
    post(`/api/gacha/${sid}/cross_check`, { worldview, cast }),
  gachaSessionConfirm: (sid, projectName, extras = {}) =>
    post(`/api/gacha/${sid}/confirm`, { project_name: projectName, ...extras }),
  gachaCancel: (sid) => post(`/api/gacha/${sid}/cancel`),

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

  /* --- 世界观架构（P12.5：10 层分步向导 + 级联校验） ---
     schema() → {layers[L0..L3], presets[10], param_count, layers_covered}
     evaluate(profile) → profile: {L0:{param:value},...}，返回 {allowed, violations} */
  worldviewSchema: () => req('/api/worldview/schema'),
  worldviewEvaluate: (profile) => post('/api/worldview/evaluate', { profile }),
  /* P15.2：人物原型推导 — 已迁移到 session 端点（gachaSessionDeriveCast） */

  /* --- 宏观规划（P17.5：开局向导第⑤段） ---
     templates() → {templates[{name, description, beat_count}]}
     planGet() → 当前项目 macro_plan.json（无 → 404）
     P20: 宏观生成改用 WebSocket（GachaView 内直连） */
  /* P22: 可选 genre —— 带时后端按题材标记 recommended（前端据此置顶/高亮） */
  macroTemplates: (genre = '') =>
    req('/api/macro/templates' + (genre ? `?genre=${encodeURIComponent(genre)}` : '')),
  macroPlanGet: () => req('/api/macro/plan'),

  /* P18.1: 跨层冲突检测 — 已迁移到 session 端点（gachaSessionCrossCheck） */

  /* P18.3: 宏观进度 + 偏差检测 */
  macroProgress: () => req('/api/macro/progress'),
  macroDeviation: () => req('/api/macro/deviation'),
}
