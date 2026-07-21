/**
 * adapters.js —— DTO → ViewModel 适配层（评审 8.3-#6：契约漂移防线）。
 *
 * 铁律：组件只消费本模块输出的视图模型，不直接碰 API 原始字段。
 * 字段口径以后端为准（story_engine/engine.py project_snapshot / DecisionCard /
 * _present_world_state / characters_view）；这里做：字段重命名（snake→camel）、
 * 缺省补默认值、派生字段（如 splitParas），只增不改语义。
 */

/* ===== 段落协议（P6.3，与后端 engine._split_paragraphs 逐字一致） =====
 * final.text 按 \n\n 切分，剔除空白块；首块若为标题行（^标题[:：]）不计入
 * 段序号——返回数组下标即 para_index，0 基，从正文第一段起。 */
const TITLE_RE = /^标题[:：]/

export function splitParas(text) {
  const paras = String(text || '')
    .split('\n\n')
    .map(p => p.trim())
    .filter(Boolean)
  if (paras.length && TITLE_RE.test(paras[0])) paras.shift()
  return paras
}

/* ===== 决策卡（chapters[].decision_card / snapshot.pending_plan → VM） =====
 * 源：showrunner/decision.py DecisionCard.to_dict() */
export function toCardVM(card) {
  if (!card) return null
  return {
    episode: card.episode ?? 0,
    advance: card.advance ?? [],           // 推进的轨道 id
    seed: card.seed ?? [],                 // 本章新埋伏笔轨道
    midTouch: card.mid_touch ?? [],        // 中触轨道
    dormant: card.dormant ?? [],           // 休眠轨道
    sternberg: card.sternberg_distribution ?? {},
    // CFPG 到期回收（rail「本章关联·回收中」）：源 ForeshadowPool.due_payoffs
    activePayoffs: (card.active_payoffs ?? []).map(p => ({
      id: p.foreshadow_id ?? '',
      content: p.content ?? '',
      payoff: p.payoff ?? '',
      trigger: p.trigger ?? '',
      plantedChapter: p.planted_chapter ?? 0,
      overdue: !!p.overdue,                // 老化债（priority 升级）
    })),
    beats: card.beats ?? [],               // [{scene, primitives, ...}]
    snyder: card.snyder_coverage ?? {},
    targetArc: card.target_arc ?? '',
    gaps: card.gaps ?? [],
    endingHook: card.ending_hook ?? null,
    themeTouch: card.theme_touch ?? false,
    // 本章种下的伏笔计划（rail「本章关联·本章种下」）
    newForeshadows: (card.new_foreshadows ?? []).map(f => ({
      track: f.track ?? '',
      content: f.content ?? '',
      trigger: f.trigger ?? '',
      payoff: f.payoff ?? '',
    })),
    planGoals: card.plan_goals ?? [],
    poolStats: card.pool_stats ?? {},      // {active, overdue, queued}
    /* pacing 区分三态（brief）：undefined=旧数据整区隐藏；null=首章无历史；
     * object=有实测。?? 会把 undefined 折成 null，故用显式判定保留原值。 */
    pacing: 'pacing' in card ? card.pacing : undefined,
    trackNames: card.track_names ?? {},    // {轨道id: 展示名}（P3.10）
    // P3.3+ 补充字段（adapter 透传；旧持久化章无字段 → 空数组/undefined，消费方 v-if 防御）
    concretenessCurve: card.concreteness_curve ?? [],  // Step 6 CONCOCT 每 beat 具体度（与 beats 同序）
    queuedForeshadows: (card.queued_foreshadows ?? []).map(q => ({   // Step 9 满池排队
      track: q.track ?? '',
      content: q.content ?? '',
      trigger: q.trigger ?? '',
      payoff: q.payoff ?? '',
    })),
    creativeSeeds: (card.creative_seeds ?? []).map(s => ({   // P3.7 跨域融合（env 门控默认关）
      domains: s.domains ?? [],
      emergent: s.emergent ?? '',
      novelty: s.novelty ?? null,
      surprise: s.surprise ?? null,
    })),
  }
}

/* ===== 章节（snapshot.chapters[] → VM） =====
 * 源：engine.generate_chapter 写入 chapters.json 的记录 + snapshot 补充的
 * rolled_back 判据（superseded 或 tick_range 尾 > head） */
export function toChapterVM(rec) {
  if (!rec) return null
  const text = (rec.final && rec.final.text) || ''
  const paras = splitParas(text)
  return {
    no: rec.chapter,
    title: rec.title || `第${rec.chapter}章`,
    text,                                  // final.text 原文（含标题行）
    paras,                                 // 段落协议切分结果（0 基）
    paraCount: paras.length,
    rolledBack: !!rec.rolled_back,
    tickRange: rec.tick_range ?? [0, 0],
    timestamp: rec.timestamp ?? '',
    durationMs: rec.duration_ms ?? 0,
    llmMode: rec.llm_mode ?? '',
    generationMode: rec.generation_mode ?? '',   // scripted | llm
    card: toCardVM(rec.decision_card),
    draftViolationCount: (rec.draft && rec.draft.violation_count) ?? 0,
    committedEvents: (rec.final && rec.final.committed_events) ?? [],
    foreshadowUpdates: rec.foreshadow_updates ?? [],
    evaluation: rec.evaluation ?? null,    // P4.5 自评（无 → null）
    narrativeIr: rec.narrative_ir ?? null, // P5.6 IR-first 摘要（无 → null）
  }
}

/* ===== 世界状态（snapshot.world_state → VM） =====
 * 源：engine._present_world_state */
export function toWorldVM(ws) {
  if (!ws) return null
  const minds = Object.entries(ws.minds ?? {}).map(([id, m]) => ({
    id,
    role: m.role ?? '',
    knows: m.knows ?? [],
    secrets: m.secrets ?? [],
    goals: m.goals ?? [],
    affect: m.affect ?? 0,
    doesntKnow: m.doesnt_know ?? [],
  }))
  const narrative = ws.narrative ?? {}
  return {
    tick: ws.tick ?? 0,
    physical: ws.physical ?? [],
    relationships: (ws.relationships ?? []).map(r => ({
      pair: r.pair ?? '',                  // "A|B"
      type: r.type ?? '',
      intensity: r.intensity ?? 0,
      history: r.history ?? [],
    })),
    minds,
    narrative: {
      act: narrative.act ?? 0,
      chapter: narrative.chapter ?? 0,
      tension: narrative.tension ?? 0,
      currentScene: narrative.current_scene ?? '',
      trackProgress: narrative.track_progress ?? {},
      causalLinks: narrative.causal_links ?? [],
      lastStoryTime: narrative.last_story_time ?? '',
    },
    // 伏笔池（CFPG 三元组）：源 types.ForeshadowTriple asdict
    foreshadows: (ws.foreshadows ?? []).map(fs => ({
      id: fs.foreshadow_id ?? '',
      content: fs.content ?? '',
      plantedChapter: fs.planted_chapter ?? 0,
      plantedAtTick: fs.planted_at_tick ?? 0,
      triggerCondition: fs.trigger_condition ?? '',
      payoff: fs.payoff ?? '',
      paidOff: !!fs.payed_off,
      paidAtChapter: fs.payed_at_chapter ?? null,
      required: fs.required !== false,
    })),
    characters: ws.characters ?? {},
  }
}

/* ===== 角色卡（GET /api/characters → VM，P6.4 B4） ===== */
export function toCharacterVM(c) {
  if (!c) return null
  return {
    id: c.id ?? '',
    role: c.role ?? '',
    knows: c.knows ?? [],
    secrets: c.secrets ?? [],
    goals: c.goals ?? [],
    relations: c.relations ?? [],
    voice: c.voice ?? null,   // Actor voice_hint → 种子档案 voice → null（不编造）
    arc: c.arc ?? null,       // 恒 null（P6.4 口径）
  }
}

/* ===== 人物视图 VM（GET /api/characters 数组 → CharsView VM，P6.9） =====
 * 源：characters_view 返回的 list[{id, role, knows, secrets, goals, relations, voice, arc}]。
 * 本 VM 额外做：
 * - 派生 relations 汇总（去重 pair，保留双向中较强的那条作为代表）
 * - 派生 useGraph 标志（节点数 ≤8 才启用 SVG 图谱，否则视图降级为关系表——评审 8.3-#4）
 * - 派生 faction：后端无显式字段，按首个关系 type 不可靠，故恒 'role'（统一色）；
 *   组件层用 id 首字 hash 做色彩散列即可，不在 adapter 编造（不编造铁律） */
export function toCharactersVM(list) {
  if (!Array.isArray(list)) return { characters: [], relations: [], useGraph: false }
  const characters = list.map(toCharacterVM).filter(Boolean)
  /* relations 去重：pair key 用「字典序较小者|较大者」，强度（intensity）取最大 */
  const relMap = new Map()
  for (const ch of characters) {
    for (const r of (ch.relations ?? [])) {
      const a = ch.id, b = r.target
      if (!b) continue
      const key = a < b ? `${a}|${b}` : `${b}|${a}`
      const prev = relMap.get(key)
      if (!prev || (r.intensity ?? 0) > (prev.intensity ?? 0)) {
        relMap.set(key, {
          a, b,
          type: r.type || '关系',
          intensity: r.intensity ?? 0,
          note: r.note ?? null,
        })
      }
    }
  }
  const relations = Array.from(relMap.values())
    .sort((x, y) => (y.intensity ?? 0) - (x.intensity ?? 0))
  return {
    characters,
    relations,
    useGraph: characters.length > 0 && characters.length <= 8,
  }
}

/* ===== 运行配置（GET /api/config → VM，P6.6 传导修复） =====
 * 源：backend/main.py config()。plugins 为 {挂载点: [名称...]} 原样透传
 * （P6.10 插件视图消费），pluginCount 为各挂载点插件数之和（App 徽标）。
 * P9.1：displayNames 为 {id: 中文 title} 合并表（registry.display_map），
 * 视图一律经 displayName() 解析显示名，id 仅作功能键/小字副标。 */
export function toConfigVM(cfg) {
  if (!cfg) return null
  const plugins = cfg.plugins ?? {}
  const axes = cfg.axes ?? {}
  const kernel = cfg.kernel ?? {}
  return {
    llmMode: cfg.llm_mode ?? '',
    llmModel: cfg.llm_model ?? '',
    baseUrl: cfg.base_url ?? null,           // mock → null（不编造）
    plugins,
    pluginCount: Object.values(plugins)
      .reduce((n, names) => n + (Array.isArray(names) ? names.length : 0), 0),
    displayNames: cfg.display_names ?? {},   // P9.1 {id: title}，无 title 后端已回落 id
    axes: {
      genre: axes.genre ?? '',
      culture: axes.culture ?? '',
      language: axes.language ?? 'zh',
    },
    kernel: {
      syscalls: kernel.syscalls ?? [],
      actors: kernel.actors ?? [],
    },
  }
}

/* P9.1 显示名解析：cfg 为 toConfigVM 的 VM（也宽容接受原始 config JSON）。
 * 查不到（如 synth 新题材尚未入库）原样回落 id。 */
export function displayName(cfg, id) {
  if (!id) return id ?? ''
  const map = cfg?.displayNames ?? cfg?.display_names ?? {}
  return map[id] || id
}

/* ===== 项目列表（GET /api/projects → VM，P10.4） =====
 * 源：backend/main.py _list_projects：[{name, genre, culture, chapter_count,
 * head_tick, last_opened_at, current}]。题材/文化中文 title 由视图经
 * displayName(config, id) 解析（与 nav 脚注同一口径，adapter 不重复持有
 * displayNames）；lastOpened 为派生展示串「MM-dd HH:mm」（源是本地 ISO
 * 秒级串，直接截取不做时区换算）。 */
export function toProjectsVM(list) {
  if (!Array.isArray(list)) return []
  return list.map(p => ({
    name: p.name ?? '',
    genre: p.genre ?? '',
    culture: p.culture ?? '',
    chapterCount: p.chapter_count ?? 0,
    headTick: p.head_tick ?? 0,
    lastOpenedAt: p.last_opened_at ?? '',
    lastOpened: p.last_opened_at
      ? String(p.last_opened_at).slice(5, 16).replace('T', ' ') : '',
    current: !!p.current,
  }))
}

/* ===== 生成回放（POST /api/project/generate 返回体 → VM，P6.6 步骤回放） =====
 * 源：engine._generate_chapter_llm_path / _generate_chapter_actor_path 的
 * record（与 chapters.json 落盘同形）。只取回放所需字段，只增不改。
 * 空稿回退标记：后端无显式字段（engine._produce_draft_text 内部消化回退），
 * fellBack 按「非剧本通道且 narrative_ir 缺失」推断 —— 也可能是 IR_FIRST=0
 * 门控关闭，故只作提示不作判决（brief 口径：推断并注明）。 */
export function toGenReportVM(rec) {
  if (!rec) return null
  const draft = rec.draft ?? {}
  const final = rec.final ?? {}
  const corr = rec.correction ?? null
  const ev = rec.evaluation ?? null
  const ir = rec.narrative_ir ?? null
  const fsUp = rec.foreshadow_updates ?? {}
  const mode = rec.generation_mode ?? ''
  return {
    chapterNo: rec.chapter ?? 0,
    title: rec.title ?? '',
    mode,                                     // scripted | llm | actor
    durationMs: rec.duration_ms ?? 0,
    card: toCardVM(rec.decision_card),
    draftChars: String(draft.text ?? '').length,
    violationCount: draft.violation_count ?? 0,
    violations: draft.violations ?? [],       // [{event, check, reason}]
    corrected: !!corr,
    correctionNote: (corr && corr.note) ?? '',
    recheckPassed: corr ? (corr.recheck_passed ?? null) : null,  // null=未复验（actor 文本修正）
    eventCount: (final.committed_events ?? []).length,
    tickRange: rec.tick_range ?? [0, 0],
    snapshotId: rec.snapshot_id ?? '',
    foreshadow: {
      planted: (fsUp.planted ?? []).length,
      payedOff: (fsUp.payed_off ?? []).length,
    },
    evaluation: ev ? {                        // P4.5 自评（有则：轮数/评语计数）
      rounds: ev.rounds ?? 0,
      bestRound: ev.best_round ?? null,
      critiques: (ev.critiques ?? []).length,
    } : null,
    narrativeIr: ir ? {                       // P5.6 IR-first 摘要（有则）
      beats: ir.beats ?? 0,
      events: ir.events ?? 0,
      dialogue: ir.dialogue ?? 0,
      pov: ir.pov ?? '',
      order: ir.order ?? '',
    } : null,
    fellBack: !ir && mode !== '' && mode !== 'scripted',
  }
}

/* ===== 介入事件（GET /api/interventions → VM，rail 介入流） =====
 * 源：event_store 中 event_type=author_intervention 的 WorldEvent。
 * 后端原样返回 {event_id, event_type, timestamp, world_tick, branch_id, payload}；
 * payload 形如 {type, reason, chapter?, before?, after?, goal_update?, ...}。
 * 这里只挑展示字段，类型色由 rail 模板按 ivType 查表。 */
const IV_LABEL = {
  textual: '改字',
  structural: '诊断',
  character: '人物',
  intent: '记一笔',
  evaluation: '诊断',
}

export function toInterventionVM(e) {
  if (!e) return null
  const p = e.payload ?? {}
  const type = p.type ?? ''
  const ivLabel = IV_LABEL[type] ?? type
  /* 摘要：按类型取最具识别度的字段，超过 48 字截断 */
  let body = ''
  if (type === 'textual') {
    const no = p.chapter ?? '?'
    const before = String(p.before ?? '').slice(0, 22)
    const after = String(p.after ?? '').slice(0, 22)
    body = `第${no}章 ¶ ${before || '…'} → ${after || '…'}`
  } else if (type === 'intent') {
    const note = p.goal_update || p.constraint || p.reason || ''
    body = String(note).slice(0, 48) || '作者意图已记录'
  } else if (type === 'evaluation') {
    body = `第${p.chapter ?? '?'}章 · ${String(p.note ?? p.quality ?? '').slice(0, 40) || '质量标注'}`
  } else if (type === 'structural') {
    body = `第${p.chapter ?? '?'}章 · ${p.action ?? '结构介入'}`
  } else if (type === 'character') {
    body = `${p.character ?? '?'} · ${p.belief ?? p.forget ?? '人物介入'}`
  } else {
    body = String(p.reason ?? type ?? '介入').slice(0, 48)
  }
  return {
    id: e.event_id ?? '',
    tick: e.world_tick ?? 0,
    timestamp: e.timestamp ?? '',
    ivType: type,
    ivLabel,
    body,
    reason: p.reason ?? '',
  }
}

/* ===== 训练统计（GET /api/training/stats → VM，rail 训练信号） =====
 * 源：backend/main.py training_stats_snapshot：{skills, preferences, style, recent_skills}。
 * 只取三个计数 + recent_skills 首条名（供技能结晶 hover 展示）。 */
export function toTrainingStatsVM(s) {
  if (!s) return null
  return {
    skills: s.skills ?? 0,
    preferences: s.preferences ?? 0,
    style: s.style ?? 0,
    recent: (s.recent_skills ?? []).map(r => ({
      name: r.name ?? '',
      source: r.source_intervention ?? '',
      createdAt: r.created_at ?? '',
    })),
  }
}

/* ===== 本章关联（chapter VM + card VM → rail「本章关联」VM，CFPG） =====
 * 消费 chapter.card（决策卡 VM）+ chapter.foreshadowUpdates。决策卡 VM 已在
 * toCardVM 里铺好 activePayoffs/newForeshadows/poolStats（P6.7 段落任务里继承
 * 的 CFPG 字段展开）。这里只是整合成 rail 友好的三段视图。 */
export function toChapterContextVM(chapter) {
  if (!chapter) return null
  const card = chapter.card ?? {}
  const fs = Array.isArray(chapter.foreshadowUpdates)
    ? { planted: [], payedOff: [] }
    : (chapter.foreshadowUpdates ?? {})
  return {
    /* 到期回收中（CFPG due_payoffs） */
    payoffs: card.activePayoffs ?? [],
    /* 本章种下（决策卡 new_foreshadows + 实际 planted） */
    newSeeds: card.newForeshadows ?? [],
    plantedCount: fs.planted?.length ?? 0,
    payedCount: fs.payed_off?.length ?? 0,
    /* 池状态 */
    pool: card.poolStats ?? {},
  }
}

/* ===== 设置（GET/POST /api/settings → VM，P6.10 B9） =====
 * 源：engine.settings_view() — {eval_enabled, ir_first, eval_max_rounds,
 * llm_mode, llm_model, base_url_masked}。POST 返回同结构（更新后）。
 * 这里只做字段名规整（snake→camel），不改语义。 */
export function toSettingsVM(s) {
  if (!s) return null
  return {
    evalEnabled: s.eval_enabled ?? false,
    irFirst: s.ir_first ?? false,
    evalMaxRounds: s.eval_max_rounds ?? 3,
    llmMode: s.llm_mode ?? '',
    llmModel: s.llm_model ?? '',
    baseUrlMasked: s.base_url_masked ?? '',
  }
}

/* ===== MetaConfig 预览（POST /api/meta/config 返回 → VM，P6.10 题材实验室） =====
 * 源：StoryConfig.to_dict() — {genre, culture, language, target_length, ...}。
 * 后端未暴露 validate_combo 字段（简化的：本视图只展示配置 + 前端再请求 /api/config
 * 不行——validate_combo 已在 generate_config 内调用，失败抛异常）。这里只取展示字段。 */
export function toMetaConfigVM(cfg) {
  if (!cfg) return null
  return {
    genre: cfg.genre ?? '',
    culture: cfg.culture ?? '',
    language: cfg.language ?? 'zh',
    targetLength: cfg.target_length ?? 12,
    theme: cfg.theme ?? '',
    platform: cfg.platform ?? 'novel',
    rawKeys: Object.keys(cfg),
  }
}

/* ===== 抽卡开局卡（POST /api/gacha/draw 返回 → VM，P8.6） =====
 * 源：meta/gacha.py _draw_library / _synth_genre。
 * 卡面只展示 name/source/desc（genre.yaml 不消费——synth 落盘复核是后端
 * confirm 领土，视图另持原始卡作 confirm payload）；rule_packs 缺省 []；
 * note 恒 string|null（synth 降级/mock 短路说明，视图 toast）；空 archetype
 * （库内无原型包）→ name ''，视图兜底文案。 */
export function toGachaCardVM(card) {
  if (!card) return null
  const genre = card.genre ?? {}
  const culture = card.culture ?? {}
  const arch = card.archetype ?? {}
  return {
    mode: card.mode ?? 'library',
    genre: {
      name: genre.name ?? '',
      source: genre.source ?? 'library',   // library | synth（徽标文案由视图映射）
      desc: genre.desc ?? '',
    },
    culture: {
      name: culture.name ?? '',
      desc: culture.desc ?? '',
    },
    archetype: {
      name: arch.name ?? '',
      desc: arch.desc ?? '',
      voiceHint: arch.voice_hint ?? '',
    },
    rulePacks: (card.rule_packs ?? []).map(p => ({
      name: p.name ?? '',
      desc: p.desc ?? '',
    })),
    note: card.note ?? null,
  }
}

/* ===== 世界观架构（P12.5：GET /api/worldview/schema → VM；P12.7：L4-L9 激活） =====
 * 源：story_engine/worldview/layers.py LAYERS（L0-L9，共 71 参数）+
 *     presets.py preset_summaries()（10 骨架）+ evaluate 端点返回。
 * schema 端点带出 {layers, presets, param_count, layers_covered}；
 * 这里把 layers 拍平成「按层分组、每参数带 options+label+hint+chain」的视图。
 * 后端已全量暴露 L0-L9，前端不再硬编码占位：covered 由 layers_covered 决定，
 * 未在 layers_covered 中的层才显示为「即将上线」灰色占位（向防御性回退）。
 *
 * 返回的 VM 结构（GachaView 向导消费）::
 *
 *   {
 *     layers: [{ id, name, desc, covered, params: [{key, label, options:[{value,
 *                label, hint, chain}], ...}], ...}, ...],   // 10 层
 *     layerIds: ['L0',...,'L9'],
 *     presets: [{key, name, vibe, summary}],                // 10 骨架
 *     paramMap: {<param_key>: <所属 layer VM>},             // 反查：违例时定位层
 *     paramMeta: {<param_key>: {layerId, label}},           // 轻量反查
 *     paramCount, layersCovered,
 *   }
 *
 * option_label 不可得（前端无映射表）→ 改由后端已带 label/options 直接使用。
 */
export function toWorldviewSchemaVM(raw) {
  if (!raw) return null
  const srcLayers = raw.layers ?? []
  const covered = new Set(raw.layers_covered ?? srcLayers.map(l => l.id))
  const presets = (raw.presets ?? []).map(p => ({
    key: p.key ?? '',
    name: p.name ?? '',
    vibe: p.vibe ?? '',
    /* 后端 summary 形如 "physics_deviation=none;metaphysics=materialist;..."
       前端展示用做副标；键值中文映射留待视图按 paramMap 解析 */
    summary: p.summary ?? '',
  }))
  /* 拍平每层参数：透传 options 数组，确保 hint/chain 字段在；
     covered 由后端 layers_covered 决定（不在集合中的层视为即将上线占位） */
  const layers = srcLayers.map(layer => ({
    id: layer.id ?? '',
    name: layer.name ?? '',
    desc: layer.desc ?? '',
    covered: covered.has(layer.id),
    params: (layer.params ?? []).map(p => ({
      key: p.key ?? '',
      label: p.label ?? p.key ?? '',
      options: (p.options ?? []).map(o => ({
        value: o.value ?? '',
        label: o.label ?? o.value ?? '',
        hint: o.hint ?? '',
        chain: o.chain ?? '',
      })),
    })),
  }))
  /* 反查表：param_key → layer VM */
  const paramMap = {}
  const paramMeta = {}
  for (const layer of layers) {
    for (const p of (layer.params ?? [])) {
      paramMap[p.key] = layer
      paramMeta[p.key] = { layerId: layer.id, label: p.label }
    }
  }
  return {
    layers,
    layerIds: layers.map(l => l.id),
    presets,
    paramMap,
    paramMeta,
    paramCount: raw.param_count ?? 0,
    layersCovered: Array.from(covered),
  }
}

/* ===== 世界观 evaluate（POST /api/worldview/evaluate 返回 → VM） =====
 * 源：worldview/predicates.py evaluate() → {allowed: {key: [vals]},
 *     violations: [{param, value, message}]}。
 * 这里只做字段重整：violations 按 param 索引成 map 便于视图 chip 标红，
 * 并派生 violationSet（param 集合，用于进度轨标记）。 */
export function toEvaluateVM(raw) {
  if (!raw) return { allowed: {}, violations: [], byParam: {}, hasViolations: false }
  const violations = (raw.violations ?? []).map(v => ({
    param: v.param ?? '',
    value: v.value ?? '',
    message: v.message ?? '',
  }))
  const byParam = {}
  for (const v of violations) {
    if (!byParam[v.param]) byParam[v.param] = []
    byParam[v.param].push(v)
  }
  return {
    allowed: raw.allowed ?? {},
    violations,
    byParam,
    violationSet: new Set(violations.map(v => v.param)),
    hasViolations: violations.length > 0,
  }
}

export function toProjectVM(snap) {
  if (!snap) return null
  const meta = snap.meta ?? {}
  return {
    meta: {
      name: meta.project ?? '',
      genre: meta.genre ?? '',
      culture: meta.culture ?? '',
      language: meta.language ?? 'zh',
      llmMode: meta.llm_mode ?? '',
      llmModel: meta.llm_model ?? '',
      headTick: meta.head_tick ?? 0,
      chapterCount: meta.chapter_count ?? 0,
    },
    chapters: (snap.chapters ?? []).map(toChapterVM),
    world: toWorldVM(snap.world_state),
    pendingPlan: toCardVM(snap.pending_plan),  // P6.2 待批准决策卡（无 → null）
    events: snap.events ?? [],
    snapshots: snap.snapshots ?? [],
    callLog: snap.call_log ?? [],
  }
}

/* ===== P6.9 四视图派生 VM（基于 toProjectVM 输出二次聚合，不重复 IO） ===== */

/* 时间线 VM：轨道（最新决策卡 trackNames）+ 事件流（按 chapter 聚合）+ 伏笔弧。
 * - 事件 agent→track 映射：后端事件无 track 字段，按决策卡 beats 反查（agent+chapter → track）。
 *   查不到时归到「主线 A」或轨道 '?-其他'，不丢事件（保证信息完整）。
 * - 伏笔弧：plantedChapter → paidAtChapter（paidOff），未回收则 → 当前 chapterCount + 1（开放）。 */
export function toTimelineVM(project) {
  if (!project) return { tracks: [], events: [], arcs: [], chapterCount: 0, empty: true }
  const chapters = (project.chapters ?? []).filter(c => !c.rolledBack).sort((a, b) => a.no - b.no)
  const chapterCount = project.meta.chapterCount ?? chapters.at(-1)?.no ?? 0
  /* 取所有 trackNames 的并集（按首次出现顺序），优先最新章 */
  const trackOrder = []
  const trackLabels = {}
  for (let i = chapters.length - 1; i >= 0; i--) {
    const tn = chapters[i].card?.trackNames ?? {}
    for (const [id, name] of Object.entries(tn)) {
      if (!(id in trackLabels)) trackLabels[id] = name || id
    }
  }
  /* 轨道顺序：A,B,C,D,E... 默认字母序（若无则空） */
  Object.keys(trackLabels).sort().forEach(id => {
    if (!trackOrder.includes(id)) trackOrder.push(id)
  })
  /* 事件聚合：events 全量，分章 */
  const evByChapter = new Map()
  for (const e of (project.events ?? [])) {
    const ch = e.payload?.chapter ?? e.payload?.episode ?? 0
    if (!evByChapter.has(ch)) evByChapter.set(ch, [])
    evByChapter.get(ch).push(e)
  }
  /* 每章按决策卡 advance/beats 决定事件在轨道上的散布：
   * - 一个 chapter 有 advance[] 时：本章事件按 agent 哈希分散到 advance 中（确定性，避免抖动）
   * - 无 advance 时：全部归到 advance[0] 或 'A' */
  function pickTrack(chapter, agent, idx) {
    const c = chapters.find(x => x.no === chapter)
    const advance = c?.card?.advance ?? []
    const beats = c?.card?.beats ?? []
    const trackIds = advance.length ? advance
      : beats.map(b => b.track).filter(Boolean)
    if (!trackIds.length) return 'A'
    const key = agent || `ev${idx}`
    let h = 0
    for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0
    return trackIds[h % trackIds.length]
  }
  const events = []
  for (const [ch, evs] of [...evByChapter.entries()].sort((a, b) => a[0] - b[0])) {
    evs.forEach((e, i) => {
      const p = e.payload ?? {}
      events.push({
        eventId: e.event_id ?? '',
        eventType: e.event_type ?? '',
        chapter: ch,
        agent: p.agent ?? '',
        action: p.action ?? p.summary ?? '',
        summary: p.summary ?? '',
        track: pickTrack(ch, p.agent, i),
        foreshadowTag: p.foreshadow_tag ?? null,
        tick: e.world_tick ?? 0,
      })
    })
  }
  /* 伏笔弧：world.foreshadows */
  const arcs = (project.world?.foreshadows ?? []).map(fs => ({
    id: fs.id,
    content: fs.content,
    from: fs.plantedChapter ?? 0,
    to: fs.paidOff ? (fs.paidAtChapter ?? fs.plantedChapter ?? chapterCount)
      : chapterCount + 1,   /* 开放弧指向「未来」一列 */
    paidOff: !!fs.paidOff,
  }))
  return {
    tracks: trackOrder.map(id => ({ id, name: trackLabels[id] })),
    events,
    arcs,
    chapterCount,
    empty: events.length === 0 && arcs.length === 0,
  }
}

/* 伏笔账 VM：三列 CFPG（已种下未到期 / 到期回收中 / 已回收）。
 * 数据源：project.world.foreshadows（CFPG 池真值）+ 最新决策卡 activePayoffs（到期）
 * - 已回收：paidOff === true
 * - 到期回收中：!paidOff && 在最新 card.activePayoffs 列表中（按 id 匹配）
 * - 已种下未到期：!paidOff && 不在 activePayoffs 中
 * 空态：foreshadows 为空且无 newForeshadows 时三列都空（视图提示） */
export function toThreadsVM(project) {
  const empty = { open: [], due: [], done: [], hasAny: false }
  if (!project) return empty
  const foreshadows = project.world?.foreshadows ?? []
  if (!foreshadows.length) {
    /* 无池：但可能本章种下了新伏笔（pending/newForeshadows），也算 open */
    const latestCard = (project.chapters ?? []).filter(c => c.card).at(-1)?.card
    const newFs = (latestCard?.newForeshadows ?? []).map((f, i) => ({
      id: `新${i + 1}`,
      content: f.content,
      trigger: f.trigger ?? '',
      payoff: f.payoff ?? '',
      plantedChapter: project.meta.chapterCount ?? 0,
      status: 'open',
    }))
    return { open: newFs, due: [], done: [], hasAny: newFs.length > 0 }
  }
  const latestCard = (project.chapters ?? []).filter(c => c.card).at(-1)?.card
  const dueIds = new Set((latestCard?.activePayoffs ?? []).map(p => p.id))
  const open = [], due = [], done = []
  for (const fs of foreshadows) {
    const item = {
      id: fs.id,
      content: fs.content,
      trigger: fs.triggerCondition ?? '',
      payoff: fs.payoff ?? '',
      plantedChapter: fs.plantedChapter ?? 0,
      paidAtChapter: fs.paidAtChapter ?? null,
      overdue: false,
    }
    if (fs.paidOff) {
      done.push({ ...item, status: 'done' })
    } else if (dueIds.has(fs.id)) {
      const ap = (latestCard?.activePayoffs ?? []).find(p => p.id === fs.id)
      due.push({ ...item, overdue: !!ap?.overdue, status: 'due' })
    } else {
      open.push({ ...item, status: 'open' })
    }
  }
  return { open, due, done, hasAny: true }
}

/* 世界观 VM：规则卡 + 简化条目。
 * - world_rules：后端 /api/config 未暴露（P6.9 读代码确认），按 genre 静态回退
 *   （brief 明示「静态读或省略」）。worldRulesByGenre 为前端常量，对齐
 *   story_engine/plugins/genres/*.yaml 中 world_rules 字段。
 * - 条目：physical（场景/物品）+ minds（人物统计）+ relationships（势力雏形）
 *   从 world 快照聚合，不编造。 */
const WORLD_RULES_BY_GENRE = {
  mystery: [
    { id: 'sanderson_1', kind: 'bool', desc: 'Sanderson 第一律：鬼神介入不解决剧情（冤魂托梦只许渲染氛围）', expr: 'not(has_supernatural and is_resolution)' },
    { id: 'fair_play', kind: 'bool', desc: 'Fair Play：叙述者不可为凶手', expr: 'not(narrator_is_killer)' },
    { id: 'case_aging', kind: 'arith', desc: '案件时效：结案不超过 365 天', expr: 'case_age_days <= 365' },
  ],
  romance: [
    { id: 'consent', kind: 'bool', desc: '情感推进需双方自愿，禁强迫/胁迫桥段', expr: 'not(coerced_affirmation)' },
    { id: 'slow_burn', kind: 'arith', desc: '情感进展不跳级（亲密度渐进）', expr: 'intimacy_delta_per_chapter <= 0.25' },
  ],
  wuxia: [
    { id: 'jianghu_consistency', kind: 'bool', desc: '江湖规矩一致性：门派/武功不矛盾', expr: 'sector_consistency' },
    { id: 'karma', kind: 'bool', desc: '善恶有报：反派必有报应', expr: 'villain_deserves_fate' },
  ],
}

export function toWorldViewVM(project, config) {
  const genre = project?.meta?.genre ?? config?.axes?.genre ?? ''
  const world = project?.world
  const rules = WORLD_RULES_BY_GENRE[genre] ?? []
  /* 简化条目：物理事实聚合（场景/物品候选）+ 关系对（势力雏形） */
  const physical = (world?.physical ?? []).map(name => ({
    name, kind: '场景/物品', desc: '已确立的物理事实（事件流聚合）',
  }))
  /* 人物→role 聚合（来自 minds VM，已有 role 字段） */
  const minds = world?.minds ?? []
  const characterEntries = minds.map(m => ({
    name: m.id,
    kind: '人物',
    desc: m.role || '—',
    scenes: [],
  }))
  /* 关系对：当成势力/集团雏形 */
  const factions = (world?.relationships ?? []).map(r => ({
    name: r.pair,
    kind: '关系',
    desc: `${r.type}（强度 ${r.intensity?.toFixed(2) ?? '0'}）`,
  }))
  return {
    genre,
    rules,
    entries: [...physical, ...factions, ...characterEntries],
    hasAny: rules.length > 0 || physical.length > 0 || minds.length > 0 || factions.length > 0,
  }
}
