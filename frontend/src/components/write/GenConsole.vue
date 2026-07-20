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
})
const emit = defineEmits(['plan', 'discard', 'confirm', 'archive', 'gotoReview',
  'rollbackRequest', 'rollbackCancel', 'rollbackConfirm'])

const MODE_LABEL = { scripted: '剧本通道', llm: 'LLM 成稿', actor: 'Actor 群像' }

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
        <button class="btn-main" :disabled="busy || generating" @click="emit('plan')">生成下一章</button>
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
        <button class="btn-main" :disabled="generating" @click="emit('confirm')">批准生成</button>
        <button class="btn-line" :disabled="busy || generating" @click="emit('discard')">作废</button>
        <span class="gc-note">批准后系统按方案成稿并过硬约束自检</span>
      </div>
    </template>

    <!-- ===== 生成中：全局锁 + 步骤骨架 ===== -->
    <template v-else-if="flow === 'generating'">
      <div class="gc-head">
        <span class="gc-title">第 {{ plan?.episode ?? nextNo }} 章 · 生成中</span>
        <span class="gc-time">已批准 · 系统执笔</span>
      </div>
      <div class="gc-bar"><i class="ind"></i></div>
      <div class="gc-steps">
        <div class="gc-step done">
          <span class="st">✓</span><span class="nm">决策卡</span>
          <span class="dt">方案已批准（推进 ×{{ plan?.advance?.length ?? 0 }} · 节拍 ×{{ plan?.beats?.length ?? 0 }}）</span>
        </div>
        <div class="gc-step run">
          <span class="st"><span class="gc-spin"></span></span><span class="nm">初稿生成</span>
          <span class="dt">系统执笔中…</span>
        </div>
        <div v-for="s in ['硬约束验证', '修正回路', '提交事件库', '快照']" :key="s" class="gc-step todo">
          <span class="st">○</span><span class="nm">{{ s }}</span><span class="dt"></span>
        </div>
      </div>
      <div class="gc-done-row">
        <button class="btn-main" disabled>生成中…</button>
        <span class="gc-note">已锁定全部生成操作，完成后自动进入步骤回放</span>
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
        <button class="btn-line" @click="emit('gotoReview')">进入审读 →</button>
        <button class="btn-main" @click="emit('archive')">归档本章</button>
        <button v-if="!confirmingRollback" class="btn-line danger" :disabled="generating"
                @click="emit('rollbackRequest')">回滚本章</button>
      </div>
      <div v-if="confirmingRollback" class="gc-confirm" role="alertdialog">
        回滚将撤回第 {{ report?.chapterNo ?? reviewNo }} 章的全部事件，世界状态回到 tick {{ rollbackTick }}（本章保留为灰色「已回滚」记录）。
        <div class="cf-act">
          <button class="btn-line danger" :disabled="generating" @click="emit('rollbackConfirm')">确认回滚</button>
          <button class="btn-line" @click="emit('rollbackCancel')">取消</button>
        </div>
      </div>
    </template>
  </div>
</template>
