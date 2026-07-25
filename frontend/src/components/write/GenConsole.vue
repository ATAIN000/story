<script setup>
// 生成控制台（写作台中栏顶部，story.html :475 + :211-239 样式 + :1187-1279 交互的真实版）
// 两阶段流：看方案（plan 决策卡预览）→ 批准生成（confirm + 全局锁 + 步骤骨架）
// → 步骤回放（真实返回体字段）→ 审读 → 归档 / 回滚；失败保留方案可重试。
// 只消费 adapter VM（plan=toCardVM，report=toGenReportVM）；完整决策卡视图是 P6.8 领土。
import { computed } from 'vue'

const props = defineProps({
  flow: { type: String, required: true },        // idle | planned | generating | review
  nextNo: { type: Number, default: 1 },          // 下一章章号（idle 提示用）
  plan: { type: Object, default: null },         // 待批准决策卡 VM
  report: { type: Object, default: null },       // 生成回放 VM（切视图丢失 → null 时紧凑条）
  error: { type: String, default: '' },          // 生成失败信息（planned 态内横幅）
  busy: { type: Boolean, default: false },       // plan/discard 短操作自锁
  generating: { type: Boolean, default: false }, // 全局生成锁（useGeneration）
  confirmingRollback: { type: Boolean, default: false },
  reviewNo: { type: Number, default: null },     // 审读中的章号
  rollbackTick: { type: Number, default: null }, // 回滚目标 tick（WriteView 已算好）
  genStage: { type: String, default: '' },       // P1-1: 后端进度 stage（actor_tick/realizing/verifying...）
  genLogs: { type: Array, default: () => [] },    // P1-1: WS 推送的进度日志数组
})
const emit = defineEmits(['plan', 'discard', 'confirm', 'archive', 'gotoReview',
  'rollbackRequest', 'rollbackCancel', 'rollbackConfirm'])

const MODE_LABEL = { scripted: '剧本通道', llm: 'LLM 成稿', actor: 'Actor 群像' }

// P1-1: 后端 stage → 中文进度标签
const STAGE_LABELS = {
  'started': '准备中…',
  'generating': '系统执笔中…',
  'actor_tick': '角色决策中（SOAR 循环）',
  'realizing': '正文生成中（LLM 创作）',
  'verifying': '验证事件一致性',
  'correcting': '修正违规中',
  'done': '完成',
  'error': '生成失败',
  'cancelled': '已取消',
}

// 步骤顺序（用于判断当前进行到哪步）
const STEP_ORDER = ['actor_tick', 'realizing', 'verifying', 'correcting']
const STAGE_SHORT = {
  'started': '准备', 'generating': '执笔', 'actor_tick': '决策',
  'realizing': '正文', 'verifying': '验证', 'correcting': '修正',
  'done': '完成', 'error': '失败',
}

const stageLabel = computed(() => {
  if (!props.genStage) return '系统执笔中…'
  if (props.genStage.startsWith('actor_tick')) return STAGE_LABELS['actor_tick']
  return STAGE_LABELS[props.genStage] || props.genStage
})

// 最新一条日志（不堆积历史，只显示当前进行的事）
const latestLog = computed(() => {
  if (!props.genLogs || !props.genLogs.length) return null
  return props.genLogs[props.genLogs.length - 1]
})

// 当前步骤序号
const currentStepIndex = computed(() => {
  const s = props.genStage || ''
  for (let i = 0; i < STEP_ORDER.length; i++) {
    if (s.startsWith(STEP_ORDER[i])) return i
  }
  return -1
})

function stepStatus(step) {
  const idx = STEP_ORDER.indexOf(step)
  if (currentStepIndex.value > idx) return 'done'
  if (currentStepIndex.value === idx) return 'run'
  return 'todo'
}
function stepIcon(step) {
  const st = stepStatus(step)
  if (st === 'done') return '✓'
  if (st === 'run') return '●'
  return '○'
}
function stepDetail(step) {
  const st = stepStatus(step)
  if (st === 'run' && latestLog.value) return latestLog.value.detail || ''
  if (st === 'done') {
    // 找该步骤的最后一条日志
    const logs = (props.genLogs || []).filter(l => l.stage && l.stage.startsWith(step))
    return logs.length ? logs[logs.length - 1].detail : '完成'
  }
  return ''
}

// 轨道显示名：决策卡 trackNames 映射优先，退化裸 id
function makeTname(card) {
  return id => card?.trackNames?.[id] || id
}
const planTname = computed(() => makeTname(props.plan))
const reportTname = computed(() => makeTname(props.report?.card))

const hook = computed(() => props.plan?.endingHook || null)
const beats = computed(() => props.plan?.beats ?? [])

function trackRow(label, sys, ids, tname) {
  return ids?.length ? { label, sys, names: ids.map(tname) } : null
}
const planRows = computed(() => {
  const p = props.plan
  if (!p) return []
  const t = planTname.value
  return [
    trackRow('推进', 'advance', p.advance, t),
    trackRow('埋新线', 'seed', p.seed, t),
    trackRow('轻触', 'mid_touch', p.midTouch, t),
    trackRow('休眠', 'dormant', p.dormant, t),
  ].filter(Boolean)
})

const duration = computed(() => props.report ? (props.report.durationMs / 1000).toFixed(1) + 's' : '')
const modeLabel = computed(() => MODE_LABEL[props.report?.mode] || props.report?.mode || '')

// 回放步骤（真实返回体字段；evaluation / narrative_ir 有则追加）
const replaySteps = computed(() => {
  const r = props.report
  if (!r) return []
  const t = reportTname.value
  const steps = [
    { nm: '决策卡', dt: `推进 ${r.card?.advance?.map(t).join('、') || '—'} · 节拍 ×${r.card?.beats?.length ?? 0}` },
    { nm: '初稿生成', dt: `${modeLabel.value} · ${r.draftChars} 字` },
    { nm: '硬约束验证', dt: r.violationCount === 0 ? '全部通过' : `${r.violationCount} 处违规`, viol: r.violations },
    {
      nm: '修正回路',
      dt: !r.corrected ? '无违规 · 未触发'
        : r.correctionNote || '已修正',
      recheck: !r.corrected ? null : r.recheckPassed,
    },
    {
      nm: '提交事件库',
      dt: `${r.eventCount} 事件 · tick ${r.tickRange[0]}–${r.tickRange[1]}`
        + (r.foreshadow.planted || r.foreshadow.payedOff
          ? ` · 伏笔 埋${r.foreshadow.planted} 收${r.foreshadow.payedOff}` : ''),
    },
    { nm: '快照', dt: r.snapshotId, mono: true },
  ]
  if (r.evaluation) {
    steps.push({
      nm: '自评迭代',
      dt: `${r.evaluation.rounds} 轮 · ${r.evaluation.critiques} 条评语`
        + (r.evaluation.bestRound != null ? ` · 最佳第 ${r.evaluation.bestRound + 1} 轮` : ''),
    })
  }
  if (r.narrativeIr) {
    steps.push({
      nm: '叙事摘要',
      dt: `节拍 ${r.narrativeIr.beats} · 事件 ${r.narrativeIr.events} · 对白 ${r.narrativeIr.dialogue}`
        + (r.narrativeIr.pov ? ` · 视角 ${r.narrativeIr.pov}` : ''),
    })
  }
  return steps
})
</script>

<template>
  <div class="gen-console">
    <!-- ===== 待命：生成下一章入口 ===== -->
    <template v-if="flow === 'idle'">
      <div class="gc-head">
        <span class="gc-title">下一章 · 第 {{ nextNo }} 章</span>
        <span class="gc-time">先看方案 · 批准才动笔</span>
      </div>
      <div class="gc-done-row">
        <button class="btn-main" :disabled="busy || generating" data-testid="gen-plan" @click="emit('plan')">生成下一章</button>
        <span class="gc-note">系统先给本章方案（轨道调度 + 节拍 + 钩子），你批准后成稿<span style="opacity:.7">（plan → confirm）</span></span>
      </div>
    </template>

    <!-- ===== 看方案：决策卡预览（简化版） ===== -->
    <template v-else-if="flow === 'planned' && plan">
      <div class="gc-head">
        <span class="gc-title">第 {{ plan.episode }} 章方案</span>
        <span class="gc-time">决策卡 · 未动笔</span>
      </div>
      <div v-if="error" class="gc-err" role="alert">生成失败：{{ error }} —— 方案已保留，可直接重试。</div>
      <div class="plan-rows">
        <div v-for="row in planRows" :key="row.sys" class="plan-row">
          <span class="pl">{{ row.label }}</span>
          <span class="pv">
            <span v-for="n in row.names" :key="n" class="tag">{{ n }}</span>
            <span class="gc-note">{{ row.sys }}</span>
          </span>
        </div>
        <div v-if="beats.length" class="plan-row">
          <span class="pl">节拍</span>
          <span class="pv">
            <span v-for="b in beats" :key="b.beat_id" class="gc-sub">
              {{ b.track_name || planTname(b.track) }} · 张力 {{ Math.round((b.tension ?? 0) * 100) }}%
            </span>
          </span>
        </div>
        <div v-if="hook" class="plan-row">
          <span class="pl">钩子</span>
          <span class="pv">「{{ hook.style }}」· {{ hook.periodic }}<span class="gc-note">　{{ hook.desc }}（ending_hook）</span></span>
        </div>
        <div v-if="plan.targetArc" class="plan-row">
          <span class="pl">情感弧</span>
          <span class="pv">{{ plan.targetArc }}<span class="gc-note">　target_arc</span></span>
        </div>
      </div>
      <div class="gc-done-row">
        <button class="btn-main" :disabled="generating" data-testid="gen-confirm" @click="emit('confirm')">批准生成</button>
        <button class="btn-line" :disabled="busy || generating" data-testid="gen-discard" @click="emit('discard')">作废</button>
        <span class="gc-note">批准后系统按方案成稿并过硬约束自检</span>
      </div>
    </template>

    <!-- ===== 生成中：全局锁 + 步骤骨架 ===== -->
    <template v-else-if="flow === 'generating'">
      <div class="gc-head">
        <span class="gc-title">第 {{ plan?.episode ?? nextNo }} 章 · 生成中</span>
        <span class="gc-time">{{ stageLabel }}</span>
      </div>
      <div class="gc-bar"><i class="ind"></i></div>
      <div class="gc-steps">
        <div class="gc-step" :class="stepStatus('actor_tick')">
          <span class="st">{{ stepIcon('actor_tick') }}</span><span class="nm">角色决策</span>
          <span class="dt">{{ stepDetail('actor_tick') }}</span>
        </div>
        <div class="gc-step" :class="stepStatus('realizing')">
          <span class="st">{{ stepIcon('realizing') }}</span><span class="nm">正文生成</span>
          <span class="dt">{{ stepDetail('realizing') }}</span>
        </div>
        <div class="gc-step" :class="stepStatus('verifying')">
          <span class="st">{{ stepIcon('verifying') }}</span><span class="nm">硬约束验证</span>
          <span class="dt">{{ stepDetail('verifying') }}</span>
        </div>
        <div class="gc-step" :class="stepStatus('correcting')">
          <span class="st">{{ stepIcon('correcting') }}</span><span class="nm">修正回路</span>
          <span class="dt">{{ stepDetail('correcting') }}</span>
        </div>
        <div class="gc-step todo">
          <span class="st">○</span><span class="nm">提交事件库 + 快照</span>
          <span class="dt"></span>
        </div>
      </div>
      <!-- P1-1: 最新进度（只显示最新一条，不重复堆积） -->
      <div v-if="latestLog" class="gc-current">
        <span class="gc-spin-sm"></span>
        <span class="gc-current-detail">{{ latestLog.detail || latestLog.stage }}</span>
      </div>
      <div class="gc-done-row">
        <button class="btn-main" disabled>生成中…</button>
        <span class="gc-note">{{ stageLabel }}</span>
      </div>
    </template>

    <!-- ===== 审读：步骤回放（真实字段） + 归档/回滚 ===== -->
    <template v-else-if="flow === 'review'">
      <div class="gc-head">
        <span class="gc-title">第 {{ report?.chapterNo ?? reviewNo }} 章{{ report?.title ? ` · ${report.title}` : '' }} · 待审读</span>
        <span class="gc-time">{{ duration }}</span>
      </div>

      <template v-if="report">
        <div class="gc-steps">
          <div v-for="s in replaySteps" :key="s.nm" class="gc-step done">
            <span class="st">✓</span><span class="nm">{{ s.nm }}</span>
            <span class="dt">
              {{ s.dt }}
              <span v-if="s.recheck === true" class="gc-sub ok">复验通过</span>
              <span v-else-if="s.recheck === false" class="gc-sub bad">复验未过</span>
              <span v-if="s.viol && s.viol.length" class="gc-viol">
                <span v-for="(v, i) in s.viol.slice(0, 5)" :key="i" class="v">
                  <b>{{ v.check }}</b>　{{ v.event }} —— {{ v.reason }}
                </span>
                <span v-if="s.viol.length > 5" class="gc-note">…共 {{ s.viol.length }} 处</span>
              </span>
            </span>
          </div>
        </div>
        <div v-if="report.fellBack" class="gc-note" style="margin-top:8px">
          未产生叙事摘要 —— 按旧文本通道成稿（后端无回退标记，此为「非剧本通道且无 IR 摘要」的推断：IR 回退或门控关闭）。
        </div>
      </template>
      <div v-else class="gc-note" style="margin-top:10px">
        生成回放只在生成时的会话内可见；章节正文在手稿中，可直接审读后归档或回滚。
      </div>

      <div class="gc-done-row">
        <button class="btn-line" data-testid="gen-goto-review" @click="emit('gotoReview')">进入审读 →</button>
        <button class="btn-main" data-testid="gen-archive" @click="emit('archive')">归档本章</button>
        <button v-if="!confirmingRollback" class="btn-line danger" :disabled="generating"
                data-testid="gen-rollback" @click="emit('rollbackRequest')">回滚本章</button>
      </div>
      <div v-if="confirmingRollback" class="gc-confirm" role="alertdialog">
        回滚将撤回第 {{ report?.chapterNo ?? reviewNo }} 章的全部事件，世界状态回到 tick {{ rollbackTick }}（本章保留为灰色「已回滚」记录）。
        <div class="cf-act">
          <button class="btn-line danger" :disabled="generating" data-testid="gen-rollback-confirm" @click="emit('rollbackConfirm')">确认回滚</button>
          <button class="btn-line" data-testid="gen-rollback-cancel" @click="emit('rollbackCancel')">取消</button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* P1-1: 生成进度步骤 */
.gc-step.run .st { color: var(--primary); }
.gc-step.done .st { color: var(--primary); }
.gc-step.done .nm { color: var(--ink2); }
.gc-step.todo .st, .gc-step.todo .nm { color: var(--faint); }
.gc-step.run .dt { color: var(--primary); font-size: 11.5px; }

/* 当前活动指示器 */
.gc-current { display: flex; align-items: center; gap: 8px; padding: 8px 12px;
  margin-top: 6px; background: var(--s2); border-radius: 6px;
  font-size: 12px; color: var(--ink2); }
.gc-spin-sm { width: 10px; height: 10px; border: 2px solid var(--line2);
  border-top-color: var(--primary); border-radius: 50%; animation: gc-spin 0.8s linear infinite; }
.gc-current-detail { flex: 1; }
@keyframes gc-spin { to { transform: rotate(360deg); } }
</style>
