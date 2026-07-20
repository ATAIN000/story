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
    activePayoffs: card.active_payoffs ?? [],
    beats: card.beats ?? [],               // [{scene, primitives, ...}]
    snyder: card.snyder_coverage ?? {},
    targetArc: card.target_arc ?? '',
    gaps: card.gaps ?? [],
    endingHook: card.ending_hook ?? null,
    themeTouch: card.theme_touch ?? false,
    newForeshadows: card.new_foreshadows ?? [],
    planGoals: card.plan_goals ?? [],
    poolStats: card.pool_stats ?? {},
    pacing: card.pacing ?? null,
    trackNames: card.track_names ?? {},    // {轨道id: 展示名}（P3.10）
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

/* ===== 运行配置（GET /api/config → VM，P6.6 传导修复） =====
 * 源：backend/main.py config()。plugins 为 {挂载点: [名称...]} 原样透传
 * （P6.10 插件视图消费），pluginCount 为各挂载点插件数之和（App 徽标）。 */
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

/* ===== 项目快照（GET /api/project → VM） ===== */
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
