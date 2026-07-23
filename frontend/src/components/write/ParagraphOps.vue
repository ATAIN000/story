<script setup>
// 段落四操作（P6.7 核心）：贴附段落右上角的 fab 浮动条（评审 8.2-#1）
// + 四个二级面板：改字 / 这不对… / 重写这段 / 记一笔。
//
// 挂载位置：由父组件（ManuscriptPanel）在段落被选中时，把本组件渲染进 .para 内。
// 本组件产出三块 DOM：
//   1. fab（绝对定位 .para 右上角；panel === null 时显示）
//   2. 行内编辑器（panel === 'edit'，取代段文本本体；其它 panel 时段文本仍由父显示）
//   3. diag 面板（panel ∈ {note, rewrite, wrong}，display:block 放在 fab 之下、
//      段文本之后；父组件 .para 是普通 block，子元素流式排列即可）
//
// 数据流（照 brief）：所有写操作走 POST /api/intervene；重写走 POST /api/paragraph/rewrite
// 再用 textual 介入回写采用稿。介入成功 → emit intervened（父刷新项目快照，rail 同步）。
//
// 全局生成锁（useGeneration）：锁中 fab 禁用并提示「正在生成中」。
// session 内 fixed 标记：父组件持有 Set，本组件 emit('fixed', i) 让父加入。
import { ref, computed, nextTick } from 'vue'
import { api } from '../../api/api'
import { useToast } from '../../composables/useToast'
import { useGeneration } from '../../composables/useGeneration'
import AppIcon from '../AppIcon.vue'

const props = defineProps({
  chapter: { type: Object, required: true },     // chapter VM（含 no/paras/evaluation）
  paraIndex: { type: Number, required: true },
  text: { type: String, required: true },        // 该段原文（chapter.paras[i]）
  fixedSet: { type: Object, required: true },    // Set<number>，已改定段集（父持有，session 内）
})
const emit = defineEmits([
  'closed',        // 面板整体关闭（取消/Esc/采用后） → 父清 opPara
  'intervened',    // 任意介入成功 → 父刷新项目快照（rail 同步）
  'text-updated',  // textual 回写成功 → 父刷新本章正文（chapter.timestamp 变）
  'fixed',         // 段落标记已改定 → 父把 paraIndex 加入 fixedSet
])

const { toast, toastError } = useToast()
const { generating } = useGeneration()

/* ---- fab 四动作单选（同时只展开一个面板） ---- */
const panel = ref(null)   // null | 'edit' | 'wrong' | 'rewrite' | 'note'

function close() { panel.value = null; emit('closed') }

function pickPanel(p) {
  if (generating.value) { toast('正在生成中，段落操作稍候'); return }
  panel.value = p
}

/* ============================================================
 * 1. 改字：行内编辑 → POST /api/intervene type=textual → 回写正文
 *    payload: {chapter, before, after}；后端 message 区分
 *    「正文已更新」vs「原文未命中仅留痕」→ 前端 toast 区分口径。
 * ============================================================ */
const editDraft = ref('')
const editing = computed(() => panel.value === 'edit')

function startEdit() {
  editDraft.value = props.text
  pickPanel('edit')
  nextTick(() => {
    const ta = document.querySelector('.ie-ta.active-edit')
    if (ta) {
      ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'
      ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length)
    }
  })
}
function fitTa(e) {
  const ta = e.target
  ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'
}
const editUnchanged = computed(() => editDraft.value.trim() === props.text.trim())

async function confirmEdit() {
  const after = editDraft.value.trim()
  if (!after || editUnchanged.value) { close(); return }   // 无改动静默退出（spec）
  try {
    const r = await api.intervene('textual', {
      chapter: props.chapter.no,
      before: props.text,
      after,
    })
    if (r.ok !== false) {
      emit('fixed', props.paraIndex)
      emit('text-updated')
      emit('intervened')
    }
    /* 区分口径：后端 InterventionResult.message 区分回写是否命中。
       后端（hitl/intervention.py _route_textual）目前对 status 取值给出：
         updated      → "第{N}章正文已更新"               ← 真正改定
         miss         → "第{N}章原文未命中，仅留痕"          ← 仅留痕
         not_found    → "第{N}章不存在，仅留痕"             ← 仅留痕
         write_failed → "第{N}章正文写回失败（详见日志），仅留痕"
         unwired      → "第{N}章文本编辑已记录（可回放），不重生成"
       后端未在响应里单独暴露 status 字段，故此处以「正文已更新」为信号；
       改后端 message 文案时请同步此处（grep 「正文已更新」可定位本依赖）。 */
    if (/正文已更新/.test(r.message || '')) {
      toast('已改定 — 文风偏好已记录')
    } else {
      toast(`未真正改定（${r.message || '原文未命中，仅留痕'}）`)
    }
    close()
  } catch (e) {
    /* 错误路径：toast + 不丢用户输入（editDraft 不动，可重试） */
    toastError(`改字失败：${e.message}`)
  }
}
function editKeydown(e) {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); confirmEdit() }
  if (e.key === 'Escape') { e.preventDefault(); close() }
}

/* ============================================================
 * 2. 记一笔：类型 chips（伏笔/提醒/设定）+ 文本 → POST /api/intervene
 *    type=intent。文案按评审意见 6：「进作者意图，下章决策卡生效」。
 *    payload: 伏笔/设定 → constraint；提醒 → goal_update（brief 口径）。
 * ============================================================ */
const NOTE_TYPES = [
  { id: '伏笔', field: 'constraint' },
  { id: '提醒', field: 'goal_update' },
  { id: '设定', field: 'constraint' },
]
const noteType = ref('伏笔')
const noteText = ref('')

function chooseNoteType(t) { noteType.value = t }

async function confirmNote() {
  const v = noteText.value.trim()
  if (!v) return
  const field = NOTE_TYPES.find(t => t.id === noteType.value)?.field || 'constraint'
  const payload = { [field]: v, note_type: noteType.value }
  try {
    const r = await api.intervene('intent', payload, `记一笔 [${noteType.value}]`)
    if (r.ok !== false) {
      emit('intervened')
      /* 意见 6：不写「进 CFPG 池」——写「下章决策卡生效」 */
      toast(`已记入${noteType.value} — 下章决策卡生效`)
      noteText.value = ''
      close()
    } else {
      toastError(`记一笔失败：${r.message || ''}`)
    }
  } catch (e) {
    toastError(`记一笔失败：${e.message}`)
  }
}

/* ============================================================
 * 3. 重写这段：方向 + 预设 chips → POST /api/paragraph/rewrite → diff
 *    预览 → 采用（走 textual 回写）/ 换方向 / 放弃。
 *    loading 态（评审 8.2-#3）；rewritten 空 → 兜底提示（不崩）。
 *    重写次数提示（评审 8.1-#3）：sessionStorage 记录每段次数，≥2 显示。
 * ============================================================ */
const RW_PRESETS = ['压迫感更强', '对话更冷', '节奏更快', '加感官细节', '留白多一点']
const RW_KEY = `storyos.rwcount.ch${props.chapter.no}@${props.chapter.timestamp || props.chapter.tickRange.join('-')}`
const rwDirection = ref('')
const rwLoading = ref(false)
const rwOriginal = ref('')
const rwRewritten = ref('')
const rwNote = ref('')

function loadRwCount() {
  try { return JSON.parse(sessionStorage.getItem(RW_KEY) || '{}') }
  catch { return {} }
}
function saveRwCount(o) {
  try { sessionStorage.setItem(RW_KEY, JSON.stringify(o)) } catch { /* 写失败忽略 */ }
}
const rwCountMap = ref(loadRwCount())
const rwCount = computed(() => rwCountMap.value[props.paraIndex] ?? 0)
function bumpRwCount() {
  const o = { ...rwCountMap.value, [props.paraIndex]: rwCount.value + 1 }
  rwCountMap.value = o
  saveRwCount(o)
}

function chooseRwPreset(c) {
  rwDirection.value = rwDirection.value === c ? '' : c
}

async function generateRewrite() {
  const dir = rwDirection.value.trim() || RW_PRESETS[0]
  rwLoading.value = true
  try {
    const r = await api.paragraphRewrite(props.chapter.no, props.paraIndex, dir)
    rwOriginal.value = r.original ?? props.text
    rwRewritten.value = r.rewritten ?? ''
    rwNote.value = r.note ?? ''
    bumpRwCount()
  } catch (e) {
    toastError(`重写失败：${e.message}`)
    /* 失败保留方向输入，可重试（错误路径不丢用户输入） */
  } finally {
    rwLoading.value = false
  }
}
const rwEmpty = computed(() => panel.value === 'rewrite' && rwOriginal.value && !rwRewritten.value)

async function adoptRewrite() {
  /* 采用 → 走改字的 textual 回写通道（brief：before=original after=rewritten） */
  const after = rwRewritten.value.trim()
  if (!after) { toast('重写稿为空，无法采用'); return }
  try {
    const r = await api.intervene('textual', {
      chapter: props.chapter.no,
      before: rwOriginal.value,
      after,
      reason: `重写方向：${rwDirection.value || '默认'}`,
    })
    if (r.ok !== false) {
      emit('fixed', props.paraIndex)
      emit('text-updated')
      emit('intervened')
    }
    /* 信号同改字通道：后端 message 含「正文已更新」才算真正回写（详见 confirmEdit 注释） */
    if (/正文已更新/.test(r.message || '')) toast('已采用重写稿 — 文风偏好已记录')
    else toast(`采用未真正回写（${r.message || '原文未命中，仅留痕'}）`)
    rwDirection.value = ''; rwOriginal.value = ''; rwRewritten.value = ''
    close()
  } catch (e) {
    toastError(`采用失败：${e.message}`)
  }
}
function varyRewrite() {
  rwOriginal.value = ''; rwRewritten.value = ''; rwNote.value = ''
  rwDirection.value = ''
}

/* ============================================================
 * 4. 这不对…（诊断抽屉，降级版，评审 8.2-#2）
 *    四类选择 → 静态展示该章 evaluation.critiques（命中维度则展示
 *    quote+fix_directive；无则显示「本章自评未标记该维度问题」）
 *    两出口：「给方向，系统重写」/「记入判断」（evaluation 介入）
 * ============================================================ */
const WRONG_TYPES = [
  { id: 'know', label: '他这时候不该知道/不该这反应', sys: 'Epistemic 角色认知' },
  { id: 'event', label: '这事不该发生', sys: 'Fabula 事件链' },
  { id: 'voice', label: '不像他会说的/做的', sys: '角色声音档案' },
  { id: 'pace', label: '节奏不对', sys: '张力曲线' },
]
/* 维度名 → 系统对照名（critique.dimension 字段口径） */
const DIM_SYS_MAP = {
  epistemic: 'know', fabula: 'event', voice: 'voice', pacing: 'pace',
  /* 兼容后端可能的中文/简写 */
  认知: 'know', 事件: 'event', 声音: 'voice', 节奏: 'pace',
}
const wrongType = ref(null)
const critiques = computed(() => props.chapter.evaluation?.critiques ?? [])
function matchedCritiques(t) {
  return critiques.value.filter(c => {
    const dim = String(c.dimension || '').toLowerCase()
    return DIM_SYS_MAP[dim] === t || dim === t || dim.includes(t)
  })
}
function chooseWrong(t) { wrongType.value = t }
const wrongMatched = computed(() =>
  wrongType.value ? matchedCritiques(wrongType.value) : [])

async function recordWrong() {
  const t = WRONG_TYPES.find(x => x.id === wrongType.value)
  if (!t) return
  try {
    const r = await api.intervene('evaluation', {
      chapter: props.chapter.no,
      quality: 'low',
      note: `¶${props.paraIndex} [${t.label}] 作者判断：${t.sys}`,
    }, `诊断 · ${t.label}`)
    if (r.ok !== false) {
      emit('intervened')
      toast('判断已记录，转为训练信号')
      close()
    } else {
      toastError(`记录失败：${r.message || ''}`)
    }
  } catch (e) {
    toastError(`记录失败：${e.message}`)
  }
}
function jumpToRewrite() {
  /* 「给方向，系统重写」：切到重写面板（同段） */
  wrongType.value = null
  panel.value = 'rewrite'
}
</script>

<template>
  <!-- 1. fab：贴附段落右上角（评审 8.2-#1）；panel 未展开时显示 -->
  <div v-if="!panel" class="fab" role="toolbar" aria-label="段落操作">
    <template v-if="!generating">
      <button @click="startEdit" title="改字" data-testid="fab-edit"><AppIcon name="pen" :size="12" /> 改字</button>
      <button @click="pickPanel('wrong')" title="这不对…" data-testid="fab-wrong"><AppIcon name="alert" :size="12" /> 这不对…</button>
      <button @click="pickPanel('rewrite')" title="重写这段" data-testid="fab-rewrite"><AppIcon name="refresh" :size="12" /> 重写这段</button>
      <button @click="pickPanel('note')" title="记一笔" data-testid="fab-note"><AppIcon name="pin" :size="12" /> 记一笔</button>
    </template>
    <span v-else class="fab-lock">正在生成中…</span>
  </div>

  <!-- 2. 改字：行内编辑器取代段文本本体 -->
  <div v-if="editing" class="inline-editor">
    <textarea class="ie-ta active-edit" rows="2" v-model="editDraft"
              @input="fitTa" @keydown="editKeydown"></textarea>
    <div class="ie-bar">
      <span class="ie-hint">只动措辞，不动情节 · Ctrl+Enter 确定 · Esc 取消</span>
      <button class="ie-ok" :disabled="editUnchanged" @click="confirmEdit">✓ 确定</button>
      <button class="ie-cancel" @click="close">取消</button>
    </div>
  </div>

  <!-- 3. 段文本本体：fab-only 与 note/rewrite/wrong 面板下都要显示（用户需看到上下文）。
       仅 editing（panel==='edit'）时不显示——textarea 已含原文，取代段文本本体。 -->
  <div class="para-text" v-if="!editing" :class="{ fixed: fixedSet.has(paraIndex) }">{{ text }}</div>

  <!-- 记一笔 -->
  <div v-if="panel === 'note'" class="diag">
    <div class="d-t">记一笔 · 进作者意图</div>
    <div class="rw-chips" style="margin-top:8px">
      <span v-for="t in NOTE_TYPES" :key="t.id" class="rw-chip"
            :class="{ on: noteType === t.id }" @click="chooseNoteType(t.id)">{{ t.id }}</span>
    </div>
    <textarea class="rw-ta" rows="2" v-model="noteText"
              placeholder="例：张三的「姑母」第 5 章要查证"></textarea>
    <div style="display:flex;gap:8px;margin-top:8px;align-items:center;flex-wrap:wrap">
      <button class="ie-ok" :disabled="!noteText.trim()" @click="confirmNote">记账</button>
      <button class="ie-cancel" @click="close">取消</button>
      <span class="ie-hint">进作者意图，下章决策卡生效</span>
    </div>
  </div>

  <!-- 重写这段 -->
  <div v-if="panel === 'rewrite'" class="diag">
    <div class="d-t">重写这段 · 给系统一个方向</div>
    <span v-if="rwCount >= 2" class="rw-count warn">本段已重写 {{ rwCount }} 次</span>
    <textarea class="rw-ta" rows="2" v-model="rwDirection"
              :disabled="rwLoading"
              placeholder="例：压迫感再强一点，包拯的话更短更冷"></textarea>
    <div class="rw-chips">
      <span v-for="c in RW_PRESETS" :key="c" class="rw-chip"
            :class="{ on: rwDirection === c }" @click="chooseRwPreset(c)">{{ c }}</span>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button class="ie-ok" :disabled="rwLoading" @click="generateRewrite">
        <span v-if="rwLoading" class="rw-loading"><span class="gc-spin" style="width:11px;height:11px;border-width:1.5px"></span> 生成中…</span>
        <span v-else>生成重写</span>
      </button>
      <button class="ie-cancel" :disabled="rwLoading" @click="close">放弃</button>
      <span class="ie-hint">系统只重写这一段，上下文自动衔接</span>
    </div>

    <!-- diff 预览 -->
    <div v-if="rwRewritten" class="rw-result">
      <div class="rw-diff">
        <div class="del">{{ rwOriginal }}</div>
        <div class="add">{{ rwRewritten }}</div>
      </div>
      <div v-if="rwNote" class="ie-hint" style="margin-top:6px">{{ rwNote }}</div>
      <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
        <button class="ie-ok" @click="adoptRewrite">采用这版</button>
        <button class="ie-cancel" @click="varyRewrite">换个方向</button>
        <button class="ie-cancel" @click="close">放弃</button>
      </div>
    </div>
    <!-- 空 rewrite 兜底（mock/失败） -->
    <div v-else-if="rwEmpty" class="rw-empty">
      暂未能生成重写<span v-if="rwNote">（{{ rwNote }}）</span>。可换个方向再试，或用「改字」手动调整。
    </div>
  </div>

  <!-- 这不对…（诊断抽屉） -->
  <div v-if="panel === 'wrong'" class="diag">
    <div v-if="!wrongType" class="d-t">哪里不对？</div>
    <div v-if="!wrongType" class="d-opts">
      <button v-for="t in WRONG_TYPES" :key="t.id" class="d-opt" @click="chooseWrong(t.id)">
        <b>{{ t.label }}</b><span>系统对照：{{ t.sys }}</span>
      </button>
    </div>

    <!-- 选择后：静态展示该章 evaluation.critiques（评审 8.2-#2 降级） -->
    <template v-else>
      <div class="d-t">{{ WRONG_TYPES.find(x => x.id === wrongType).label }}</div>
      <div v-if="wrongMatched.length" class="d-b">
        <div v-for="(c, i) in wrongMatched" :key="i" style="margin-bottom:8px">
          <div v-if="c.evidence && c.evidence.length" style="font-size:12px;color:var(--ink2)">
            引文：<span v-for="q in c.evidence" :key="q" style="color:var(--danger)">「{{ q }}」</span>
          </div>
          <div v-if="c.fix_directive" style="font-size:12.5px;color:var(--accent);margin-top:3px">
            修改建议：{{ c.fix_directive }}
          </div>
        </div>
      </div>
      <div v-else class="d-b" style="color:var(--ink2)">
        本章自评未标记该维度问题，你的判断已记录。
      </div>
      <div class="d-sys">本章自评轮数：{{ chapter.evaluation?.rounds ?? 0 }} · critique {{ critiques.length }} 条</div>
      <div class="d-opts">
        <button class="d-opt" @click="jumpToRewrite">
          <b>给方向，系统重写</b><span>你一句话，系统出 diff</span>
        </button>
        <button class="d-opt" @click="recordWrong">
          <b>记入判断</b><span>转为训练信号，本章不改</span>
        </button>
      </div>
    </template>
  </div>
</template>
