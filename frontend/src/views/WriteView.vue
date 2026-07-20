<script setup>
// 写作台（P6.6）：章节 binder + 手稿 + 两阶段生成流（看方案 → 批准生成 →
// 步骤回放 → 审读 → 归档/回滚）+ 零章冷启动空态 + 生成失败路径 + 全局生成锁。
// 三栏布局照 story.html :466-483；只消费 adapter VM（project=toProjectVM，
// plan=toCardVM，report=toGenReportVM），API 原始字段不进模板。
import { ref, computed, watch, nextTick } from 'vue'
import { api } from '../api/api'
import { toCardVM, toGenReportVM } from '../api/adapters'
import { useToast } from '../composables/useToast'
import { useGeneration, GEN_REJECTED } from '../composables/useGeneration'
import { useFontSize } from '../composables/useFontSize'
import EmptyState from '../components/EmptyState.vue'
import ChapterBinder from '../components/write/ChapterBinder.vue'
import ManuscriptPanel from '../components/write/ManuscriptPanel.vue'
import GenConsole from '../components/write/GenConsole.vue'

const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})
const emit = defineEmits(['refresh'])

const { toast, toastError } = useToast()
const { generating, runGeneration } = useGeneration()
const { fsSize } = useFontSize()

/* ---- 流程状态机：idle → planned → generating → review →（归档/回滚）→ idle ---- */
const flow = ref('idle')
const planPreview = ref(null)   // 待批准决策卡 VM（本地持有，失败重试不丢）
const genReport = ref(null)     // 生成回放 VM（仅本会话；切视图后丢失，review 退紧凑条）
const genError = ref('')
const activeNo = ref(null)      // 手稿当前章
const confirmingRollback = ref(false)
const busy = ref(false)         // plan/discard 短操作自锁

/* 「审读中」章号集：前端本地状态（brief 口径），sessionStorage 记忆防切视图丢失 */
const REVIEW_KEY = 'storyos.reviewing'
function loadReviewing() {
  try {
    const a = JSON.parse(sessionStorage.getItem(REVIEW_KEY) || '[]')
    return new Set(Array.isArray(a) ? a : [])
  } catch { return new Set() }
}
const reviewing = ref(loadReviewing())
function setReviewing(s) {
  reviewing.value = s
  try { sessionStorage.setItem(REVIEW_KEY, JSON.stringify([...s])) } catch { /* 写失败忽略 */ }
}

/* ---- 派生 ---- */
const chapters = computed(() =>
  (props.project?.chapters ?? []).slice().sort((a, b) => a.no - b.no))
const hasChapters = computed(() => chapters.value.length > 0)
const activeChapter = computed(() => chapters.value.find(c => c.no === activeNo.value) ?? null)
const nextNo = computed(() => (props.project?.meta.chapterCount ?? chapters.value.length) + 1)

const reviewNo = computed(() =>
  genReport.value?.chapterNo ?? ([...reviewing.value].sort((a, b) => b - a)[0] ?? null))
const reviewChapter = computed(() => chapters.value.find(c => c.no === reviewNo.value) ?? null)
const rollbackTick = computed(() => {
  const tr = reviewChapter.value?.tickRange
  return tr ? Math.max(0, tr[0] - 1) : null   // 回到本章首事件之前（tick 0 合法，tests 口径）
})

/* 全书进度 saga：章数真值；张力=最新未回滚章决策卡 beats tension（无 → null 隐藏） */
const saga = computed(() => {
  const count = props.project?.meta.chapterCount ?? chapters.value.length
  const latest = [...chapters.value].reverse()
    .find(c => !c.rolledBack && c.card?.beats?.some(b => typeof b.tension === 'number'))
  const tensions = latest?.card?.beats?.map(b => b.tension).filter(t => typeof t === 'number') ?? null
  const tp = props.project?.world?.narrative.trackProgress ?? {}
  const names = latest?.card?.trackNames ?? planPreview.value?.trackNames ?? {}
  const tracks = Object.entries(tp).map(([id, v]) => {
    const num = Number(v) || 0
    return { name: names[id] || id, pct: num <= 1 ? Math.round(num * 100) : Math.round(num) }
  })
  return { count, tensions: tensions?.length ? tensions : null, tracks }
})

/* 顶栏流程条（story.html :615-618 四步口径） */
const dpSteps = computed(() => {
  const f = flow.value
  return [
    { n: '看方案', st: f === 'generating' || f === 'review' ? 'done' : 'now' },
    { n: '等生成', st: f === 'generating' ? 'now' : f === 'review' ? 'done' : '' },
    { n: '审读', st: f === 'review' ? 'now' : '' },
    { n: '提交归档', st: '' },
  ]
})

/* project 变化：补默认选中章；拾起后端待批准方案 / 本会话未审读章（切视图返回恢复） */
watch(() => props.project, (p) => {
  if (!p) return
  if (activeNo.value == null || !chapters.value.some(c => c.no === activeNo.value)) {
    const alive = chapters.value.filter(c => !c.rolledBack)
    activeNo.value = (alive.at(-1) ?? chapters.value.at(-1))?.no ?? null
  }
  if (flow.value === 'idle') {
    if (p.pendingPlan) {
      planPreview.value = p.pendingPlan
      flow.value = 'planned'
    } else if (reviewing.value.size) {
      flow.value = 'review'
    }
  }
}, { immediate: true })

/* ---- 1. 看方案：POST /api/project/plan → 决策卡预览 ---- */
async function startPlan() {
  if (busy.value || generating.value) { if (generating.value) toast('正在生成中，请稍候'); return }
  busy.value = true
  genError.value = ''
  try {
    planPreview.value = toCardVM(await api.plan())
    flow.value = 'planned'
  } catch (e) {
    toastError(`看方案失败：${e.message}`)
  } finally {
    busy.value = false
  }
}

/* ---- 作废：DELETE /api/project/plan ---- */
async function discardPlan() {
  if (busy.value) return
  busy.value = true
  try {
    await api.deletePlan()
    planPreview.value = null
    flow.value = 'idle'
    genError.value = ''
    toast('方案已作废')
  } catch (e) {
    toastError(`作废失败：${e.message}`)
  } finally {
    busy.value = false
  }
}

/* ---- 2/3. 批准生成：confirm + 全局锁 → 步骤回放 ---- */
async function confirmGenerate() {
  genError.value = ''
  const episode = planPreview.value?.episode ?? nextNo.value
  try {
    const r = await runGeneration(async () => {
      flow.value = 'generating'
      const rec = await api.generate('confirm')
      genReport.value = toGenReportVM(rec)
      setReviewing(new Set([rec.chapter]))
      activeNo.value = rec.chapter
      planPreview.value = null   // confirm 已消费缓存卡，预览同步收口
      flow.value = 'review'
      emit('refresh')   // 新章落盘后刷新快照（binder/手稿/世界态）
      return rec
    }, `第 ${episode} 章 · 生成中`)
    if (r === GEN_REJECTED) toast('正在生成中，请稍候')   // P6.5 传导：重入拒绝标记
  } catch (e) {
    /* 失败路径（brief）：错误 toast + 保留 plan 预览（不消失）+ 可重试。
       后端 confirm 命中缓存卡即清除（engine._resolve_decision_card），故补一张
       同集方案让预览/重试有凭据（同集重复产卡幂等，P6.2 调查结论）。 */
    flow.value = 'planned'
    genError.value = e.message
    toastError(`生成失败：${e.message}`)
    try { planPreview.value = toCardVM(await api.plan()) } catch { /* 补卡失败则保留旧预览 */ }
  }
}

/* ---- 4. 归档：本地标记 + 刷新（章节生成时已落盘，归档是审读流程的本地收口） ---- */
function archive() {
  const no = reviewNo.value
  if (no == null) return
  setReviewing(new Set([...reviewing.value].filter(n => n !== no)))
  flow.value = 'idle'
  genReport.value = null
  genError.value = ''
  emit('refresh')
  toast(`第 ${no} 章已归档`)
}

/* ---- 4b. 回滚：内联确认 → POST /api/project/rollback（走全局锁防与生成并发） ---- */
async function doRollback() {
  const ch = reviewChapter.value
  const tick = rollbackTick.value
  confirmingRollback.value = false
  if (!ch || tick == null) return
  try {
    const r = await runGeneration(async () => { await api.rollback(tick) }, `回滚到 tick ${tick}`)
    if (r === GEN_REJECTED) { toast('正在生成中，请稍候'); return }
    setReviewing(new Set([...reviewing.value].filter(n => n !== ch.no)))
    flow.value = 'idle'
    genReport.value = null
    planPreview.value = null   // 后端 rollback 同步作废待批准方案（P6.2）
    genError.value = ''
    activeNo.value = ch.no     // 留在原章看灰色「已回滚」记录
    emit('refresh')
    toast(`已回滚第 ${ch.no} 章（回到 tick ${tick}）`)
  } catch (e) {
    toastError(`回滚失败：${e.message}`)
  }
}

function gotoReview() {
  if (reviewNo.value != null) activeNo.value = reviewNo.value
  nextTick(() => document.querySelector('.manuscript')
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

function selectChapter(no) { activeNo.value = no }

/* ---- 右栏「本章档案」（全部取 chapter VM 真值） ---- */
const MODE_LABEL = { scripted: '剧本通道', llm: 'LLM 成稿', actor: 'Actor 群像' }
const chMode = computed(() => MODE_LABEL[activeChapter.value?.generationMode] || activeChapter.value?.llmMode || '—')
const chChars = computed(() => activeChapter.value ? activeChapter.value.paras.join('').length : 0)
const chDuration = computed(() => activeChapter.value ? (activeChapter.value.durationMs / 1000).toFixed(1) + 's' : '—')
const chFs = computed(() => {
  const f = activeChapter.value?.foreshadowUpdates
  if (!f || Array.isArray(f)) return null
  const planted = (f.planted ?? []).length
  const payed = (f.payed_off ?? []).length
  return planted || payed ? { planted, payed } : null
})
</script>

<template>
  <!-- 零章冷启动（brief 空态口径）：CTA 直接触发 plan 流程 -->
  <div v-if="!hasChapters && flow === 'idle'" class="desk-empty">
    <EmptyState icon="pen" title="开始你的第一章"
      desc="新项目从第 1 章开始。系统先给本章方案（轨道调度 + 节拍 + 钩子），你批准后才真正成稿。">
      <button class="btn-main" :disabled="busy || generating" @click="startPlan">看第 1 章方案</button>
    </EmptyState>
  </div>

  <div v-else class="desk">
    <!-- 左栏：章节 binder + saga 全书进度 -->
    <ChapterBinder :chapters="chapters" :active-no="activeNo" :reviewing="reviewing"
                   :saga="saga" @select="selectChapter" />

    <!-- 中栏：流程条 + 生成控制台 + 手稿 -->
    <div class="writing">
      <div class="desk-progress">
        <div v-for="s in dpSteps" :key="s.n" class="dp-step" :class="s.st">
          {{ (s.st === 'done' ? '✓ ' : s.st === 'now' ? '● ' : '○ ') + s.n }}
        </div>
      </div>

      <GenConsole :flow="flow" :next-no="nextNo" :plan="planPreview" :report="genReport"
                  :error="genError" :busy="busy" :generating="generating"
                  :confirming-rollback="confirmingRollback"
                  :review-no="reviewNo" :rollback-tick="rollbackTick"
                  @plan="startPlan" @discard="discardPlan" @confirm="confirmGenerate"
                  @archive="archive" @goto-review="gotoReview"
                  @rollback-request="confirmingRollback = true"
                  @rollback-cancel="confirmingRollback = false"
                  @rollback-confirm="doRollback" />

      <ManuscriptPanel v-if="activeChapter" :key="activeChapter.no" :chapter="activeChapter"
                       :reviewing="reviewing.has(activeChapter.no)" :fs-size="fsSize" />
      <EmptyState v-else icon="pen" title="还没有章节"
        desc="批准方案后，第一章手稿会出现在这里。" />
    </div>

    <!-- 右栏：本章档案（chapter VM 真值） -->
    <aside class="rail">
      <div v-if="activeChapter" class="rail-sec">
        <div class="rail-t">本章档案</div>
        <div class="mini-stat"><span>篇幅</span><b>{{ activeChapter.paraCount }} 段 · {{ chChars }} 字</b></div>
        <div class="mini-stat"><span>成稿</span><b>{{ chMode }} · {{ chDuration }}</b></div>
        <div class="mini-stat"><span>事件</span><b>{{ activeChapter.committedEvents.length }} 个 · tick {{ activeChapter.tickRange[0] }}–{{ activeChapter.tickRange[1] }}</b></div>
        <div class="mini-stat"><span>硬约束</span><b>{{ activeChapter.draftViolationCount ? `${activeChapter.draftViolationCount} 处违规已修正` : '0 违规' }}</b></div>
        <div v-if="chFs" class="mini-stat"><span>伏笔</span><b>埋 {{ chFs.planted }} · 收 {{ chFs.payed }}</b></div>
        <div class="mini-stat"><span>落盘</span><b>{{ activeChapter.timestamp.slice(0, 19).replace('T', ' ') }}</b></div>
      </div>
    </aside>
  </div>
</template>
