<script setup>
/* 抽卡开局页（P13 简化：题材 + 世界观两段式）
 *   段 1 题材选择（单栏卡片网格，全量 registry 题材列表）→ 段 2 骨架选择
 *   （10 卡+随机+空白）→ 段 3 十层向导 → 确认开工
 *
 * P13 变更：删除四栏（题材×文化×原型×规则），文化从题材 allowed_cultures
 * 自带（后端 confirm 推导），世界规则由世界观向导产出取代随机抽包栏。
 * synth 模式（让 AI 自由发挥）保留不变。
 *
 * a11y：层/卡 aria-label、chips role="group"、键盘可达、对话框焦点圈保留。
 */
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { api } from '../api/api'
import { toGachaCardVM, toGenreListVM, displayName, toWorldviewSchemaVM, toEvaluateVM } from '../api/adapters'
import { presetToLayers } from '../api/worldviewPresets'
import { useToast } from '../composables/useToast'
import AppIcon from '../components/AppIcon.vue'

const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})
defineEmits(['refresh', 'navigate'])

const { toast, toastError } = useToast()
const dn = (id) => displayName(props.config, id)

/* ===== 段 1：题材选择（P13 简化） ===== */
const genreList = ref(null)                // toGenreListVM 输出
const genres = computed(() => genreList.value?.genres ?? [])
const listLoading = ref(false)
const selectedGenre = ref(null)            // 选中题材 name
const synthLoading = ref(false)
const synthElapsed = ref(0)
let synthTimer = null
const startOpen = ref(false)
const startMode = ref('current')
const projectName = ref('')
const confirmBusy = ref(false)
/* synth 模式产出的精简卡（source=synth 时存 genre yaml） */
const synthCard = ref(null)

const startBtn = ref(null)
const dialogEl = ref(null)
const cancelBtn = ref(null)

const chapterCount = computed(() => (props.project?.chapters ?? []).length)
const busy = computed(() => listLoading.value || confirmBusy.value)

const NAME_RE = /^[\p{L}\p{N} _-]+$/u
const RESERVED_RE = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i
const selectedGenreVM = computed(() => genres.value.find(g => g.name === selectedGenre.value) ?? null)
const suggestedName = computed(() => {
  const g = selectedGenre.value || synthCard.value?.genre?.name || 'story'
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${g}-${mm}${dd}`
})
const nameValid = computed(() => {
  const n = projectName.value
  return n.length > 0 && n.length <= 40 && n === n.trim()
    && !n.startsWith('.') && !n.endsWith('.') && !n.includes('..')
    && NAME_RE.test(n) && !RESERVED_RE.test(n)
})

/* 确认开工用的 card payload（P13 精简：{mode, genre:{name, source, yaml?}}） */
const confirmPayload = computed(() => {
  if (synthCard.value) return synthCard.value
  if (!selectedGenre.value) return null
  return {
    mode: 'library',
    genre: { name: selectedGenre.value, source: 'library', desc: '' },
    note: null,
  }
})

/* ===== 段 2/3：世界观向导（P12.5 保留） ===== */
const stage = ref('theme')                // 'theme' | 'skeleton' | 'wizard'
const schemaVM = ref(null)
const schemaLoading = ref(false)
const wvProfile = ref({})
const chosenPresetKey = ref(null)
const evalVM = ref({ allowed: {}, violations: [], byParam: {}, violationSet: new Set(), hasViolations: false })
const evalPending = ref(false)
const currentLayerIdx = ref(0)
let evalTimer = null
let evalSeq = 0

onMounted(() => {
  loadGenres()
  loadSchema()
})
onBeforeUnmount(() => {
  clearInterval(synthTimer)
  clearTimeout(evalTimer)
})

/* ---- 段 1 题材列表 ---- */
async function loadGenres() {
  if (listLoading.value) return
  listLoading.value = true
  try {
    const d = await api.gachaDraw('library')
    genreList.value = toGenreListVM(d)
    if (d.note) toast(d.note)
  } catch (e) {
    toastError(`题材加载失败：${e.message}`)
  } finally {
    listLoading.value = false
  }
}

function chooseGenre(name) {
  selectedGenre.value = name
  synthCard.value = null     // 切回 library 选择时清 synth 卡
}

async function synthGenre() {
  if (synthLoading.value) return
  synthLoading.value = true
  synthElapsed.value = 0
  synthTimer = setInterval(() => { synthElapsed.value += 1 }, 1000)
  try {
    const d = await api.gachaDraw('synth')
    /* synth 返回精简卡 {mode, genre:{name,source,desc,yaml?}, note} */
    synthCard.value = d
    selectedGenre.value = null   // synth 选中态与列表互斥
    if (d.note) toast(d.note)
  } catch (e) {
    toastError(`AI 合成失败：${e.message}`)
  } finally {
    synthLoading.value = false
    clearInterval(synthTimer)
    synthTimer = null
  }
}

const hasSelection = computed(() => !!selectedGenre.value || !!synthCard.value)

/* ---- 段 1 → 段 2 ---- */
function goSkeleton() {
  if (!hasSelection.value || busy.value) return
  stage.value = 'skeleton'
}

/* ---- schema 加载 ---- */
async function loadSchema() {
  schemaLoading.value = true
  try {
    const raw = await api.worldviewSchema()
    schemaVM.value = toWorldviewSchemaVM(raw)
  } catch (e) {
    toastError(`世界观定义加载失败：${e.message}`)
  } finally {
    schemaLoading.value = false
  }
}

/* ---- 段 2 骨架选择 ---- */
const presetCards = computed(() => schemaVM.value?.presets ?? [])

function presetHighlights(preset) {
  if (!preset.summary) return []
  const meta = schemaVM.value?.paramMeta ?? {}
  return preset.summary.split(';').map(kv => {
    const [k, v] = kv.split('=')
    if (!k) return null
    return { paramKey: k, value: v, label: meta[k]?.label || k }
  }).filter(Boolean)
}

function choosePreset(key) {
  chosenPresetKey.value = key
  if (key === 'blank') {
    wvProfile.value = {}
  } else if (key === 'random') {
    const keys = presetCards.value.map(p => p.key)
    const picked = keys[Math.floor(Math.random() * keys.length)]
    wvProfile.value = presetToLayers(picked, schemaVM.value)
    chosenPresetKey.value = picked
    toast(`随机骨架：${presetCards.value.find(p => p.key === picked)?.name ?? ''}`)
  } else {
    wvProfile.value = presetToLayers(key, schemaVM.value)
  }
  currentLayerIdx.value = 0
}

function goWizard() {
  if (!schemaVM.value) return
  stage.value = 'wizard'
  currentLayerIdx.value = 0
  scheduleEvaluate()
}

function backToTheme() { stage.value = 'theme' }
function backToSkeleton() { stage.value = 'skeleton' }

/* ---- 段 3 向导 ---- */
const layers = computed(() => schemaVM.value?.layers ?? [])
const currentLayer = computed(() => layers.value[currentLayerIdx.value] ?? null)
const isLastLayer = computed(() => currentLayerIdx.value === layers.value.length - 1)

function layerStatus(layerId) {
  const layer = layers.value.find(l => l.id === layerId)
  if (!layer) return 'todo'
  if (!layer.covered) return 'pending'
  if (layers.value[currentLayerIdx.value]?.id === layerId) return 'current'
  const params = layer.params ?? []
  const hasV = params.some(p => evalVM.value.violationSet.has(p.key))
  if (hasV) return 'violation'
  const allSet = params.length > 0 && params.every(p => {
    const layerData = wvProfile.value[layerId] ?? {}
    return !!layerData[p.key]
  })
  return allSet ? 'done' : 'todo'
}

function jumpLayer(idx) {
  if (idx < 0 || idx >= layers.value.length) return
  currentLayerIdx.value = idx
}

function layerProgressPct() {
  if (!layers.value.length) return 0
  const done = layers.value.filter(l => {
    if (!l.covered) return false
    const s = layerStatus(l.id)
    return s === 'done' || s === 'violation' || s === 'current'
  }).length
  return (done / layers.value.length) * 100
}

function selectedValue(paramKey) {
  const layer = currentLayer.value
  if (!layer) return ''
  return (wvProfile.value[layer.id] ?? {})[paramKey] ?? ''
}

function optionDisabled(paramKey, value) {
  const allowed = evalVM.value.allowed[paramKey]
  if (!allowed) return false
  return !allowed.includes(value)
}

function optionDisabledReason(paramKey, value) {
  const vs = evalVM.value.byParam[paramKey] ?? []
  const hit = vs.find(v => v.value === value)
  return hit ? hit.message : '与当前其他选择冲突'
}

function optionViolated(paramKey, value) {
  const sel = selectedValue(paramKey)
  if (sel !== value) return false
  return evalVM.value.violationSet.has(paramKey)
}

function chainHint(option) {
  return option.chain || ''
}

function chooseParam(paramKey, value) {
  const layer = currentLayer.value
  if (!layer) return
  if (!wvProfile.value[layer.id]) wvProfile.value[layer.id] = {}
  wvProfile.value[layer.id][paramKey] = value
  scheduleEvaluate()
}

function clearParam(paramKey) {
  const layer = currentLayer.value
  if (!layer) return
  if (wvProfile.value[layer.id]) {
    delete wvProfile.value[layer.id][paramKey]
    if (Object.keys(wvProfile.value[layer.id]).length === 0) {
      delete wvProfile.value[layer.id]
    }
  }
  scheduleEvaluate()
}

function scheduleEvaluate() {
  clearTimeout(evalTimer)
  evalTimer = setTimeout(runEvaluate, 300)
}

async function runEvaluate() {
  if (!schemaVM.value) return
  const seq = ++evalSeq
  evalPending.value = true
  try {
    const raw = await api.worldviewEvaluate(wvProfile.value)
    if (seq !== evalSeq) return
    evalVM.value = toEvaluateVM(raw)
  } catch (e) {
    if (seq === evalSeq) toastError(`世界观校验失败：${e.message}`)
  } finally {
    if (seq === evalSeq) evalPending.value = false
  }
}

function nextLayer() {
  if (currentLayerIdx.value < layers.value.length - 1) currentLayerIdx.value++
}
function prevLayer() {
  if (currentLayerIdx.value > 0) currentLayerIdx.value--
}

function requestConfirm() {
  if (!confirmPayload.value || busy.value) return
  runEvaluate().then(() => {
    if (evalVM.value.hasViolations) {
      toastError(`世界观存在 ${evalVM.value.violations.length} 处违例，需先修正`)
      const firstV = evalVM.value.violations[0]
      const layerId = schemaVM.value?.paramMeta?.[firstV.param]?.layerId
      if (layerId) {
        const idx = layers.value.findIndex(l => l.id === layerId)
        if (idx >= 0) currentLayerIdx.value = idx
      }
      return
    }
    startMode.value = 'current'
    projectName.value = suggestedName.value
    startOpen.value = true
    nextTick(() => { cancelBtn.value?.focus() })
  })
}

function cancelConfirm() {
  if (confirmBusy.value) return
  startOpen.value = false
  nextTick(() => { startBtn.value?.focus() })
}

function onDialogKeydown(e) {
  if (e.key === 'Escape') { e.preventDefault(); cancelConfirm(); return }
  if (e.key !== 'Tab' || !dialogEl.value) return
  const items = [...dialogEl.value.querySelectorAll('button:not([disabled]), input:not([disabled])')]
  if (!items.length) return
  const first = items[0]
  const last = items[items.length - 1]
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
}

async function doConfirm() {
  if (!confirmPayload.value || confirmBusy.value) return
  const asNew = startMode.value === 'new'
  const name = asNew ? projectName.value.trim() : null
  if (asNew && !nameValid.value) return
  if (Object.keys(wvProfile.value).length > 0) {
    try {
      const raw = await api.worldviewEvaluate(wvProfile.value)
      const vm = toEvaluateVM(raw)
      if (vm.hasViolations) {
        toastError(`世界观存在 ${vm.violations.length} 处违例，已拦截`)
        return
      }
    } catch (e) {
      toastError(`世界观校验失败：${e.message}`)
      return
    }
  }
  confirmBusy.value = true
  try {
    const wvPayload = Object.keys(wvProfile.value).length > 0
      ? { layers: wvProfile.value, preset: chosenPresetKey.value === 'blank' ? null : chosenPresetKey.value }
      : null
    const payload = wvPayload ? { ...confirmPayload.value, worldview: wvPayload } : confirmPayload.value
    const res = await api.gachaConfirm(payload, name)
    startOpen.value = false
    const finalGenre = res.genre ?? ''
    const culture = res.project?.culture ?? ''
    const suffix = res.persisted ? '（新题材已入库）' : ''
    toast(asNew
      ? `新项目《${res.project?.name ?? name}》已开工：${dn(finalGenre)} × ${dn(culture)}${suffix}`
      : `已开工：${dn(finalGenre)} × ${dn(culture)}${suffix}`)
    try {
      await api.plan()
    } catch (e) {
      toastError(`第 1 章方案生成失败：${e.message}（可到写作台重试）`)
    }
    window.location.reload()
  } catch (e) {
    if (e.status === 409) {
      toastError('项目名已存在，换一个')
    } else {
      toastError(`确认开工失败：${e.message}`)
    }
  } finally {
    confirmBusy.value = false
  }
}
</script>

<template>
  <div class="gacha">
    <header class="gacha-head">
      <h2>开局 · 选一个题材</h2>
      <p class="gacha-sub">题材决定轨道/节奏/评估权重/人物阵容，世界观决定设定/规则。选题材 → 选骨架 → 世界观向导 → 开工。</p>
      <!-- 三段式面包屑 -->
      <ol class="gacha-stages" role="list">
        <li :class="{ active: stage === 'theme', done: stage !== 'theme' }">
          <span class="gs-idx">1</span><span class="gs-name">题材选择</span>
        </li>
        <li :class="{ active: stage === 'skeleton', done: stage === 'wizard', disabled: !hasSelection }">
          <span class="gs-idx">2</span><span class="gs-name">骨架选择</span>
        </li>
        <li :class="{ active: stage === 'wizard', disabled: !hasSelection }">
          <span class="gs-idx">3</span><span class="gs-name">世界观向导</span>
        </li>
      </ol>
    </header>

    <div v-if="synthLoading" class="gacha-status" role="status">
      <span class="gc-spin" aria-hidden="true"></span>AI 正在生成题材包，通常 20-60 秒（已等待 {{ synthElapsed }} 秒）…
    </div>

    <!-- ===== 段 1：题材选择（P13 单栏卡片网格） ===== -->
    <template v-if="stage === 'theme'">
      <!-- synth 选中态展示 -->
      <div v-if="synthCard" class="gacha-synth-picked" role="status">
        <span class="gacha-src synth">AI 合成</span>
        <b>{{ dn(synthCard.genre.name) || synthCard.genre.name }}</b>
        <span class="gacha-desc">{{ synthCard.genre.desc || '—' }}</span>
        <button class="btn-line btn-line-xs" aria-label="取消 AI 合成，回到题材列表" @click="synthCard = null">重新选择</button>
      </div>

      <div v-else-if="listLoading" class="gacha-loading" role="status">
        <span class="gc-spin" aria-hidden="true"></span>加载题材列表…
      </div>
      <section v-else-if="genres.length" class="gacha-genre-grid" role="group" aria-label="题材选择">
        <button v-for="g in genres" :key="g.name"
                class="gacha-genre-card"
                :class="{ selected: selectedGenre === g.name }"
                :aria-label="`选择题材：${g.title}。${g.desc}`"
                :aria-pressed="selectedGenre === g.name"
                @click="chooseGenre(g.name)">
          <div class="gacha-genre-name">{{ g.title }}</div>
          <div class="gacha-genre-desc">{{ g.desc || '—' }}</div>
          <div v-if="g.cultureTitle" class="gacha-genre-badge">
            <AppIcon name="globe" :size="11" /> {{ dn(g.cultureTitle) || g.cultureTitle }}
          </div>
          <ul v-if="g.castSummary.length" class="gacha-genre-chips" aria-hidden="true">
            <li v-for="c in g.castSummary.slice(0, 5)" :key="c">{{ c.length > 10 ? c.slice(0, 10) + '…' : c }}</li>
          </ul>
        </button>
      </section>
      <div v-else class="gacha-loading">
        <span>暂无可用题材。</span>
        <button class="btn-line" aria-label="重新加载题材列表" @click="loadGenres">重新加载</button>
      </div>

      <footer class="gacha-foot">
        <button class="btn-line gacha-synth-btn" :disabled="busy"
                aria-label="让 AI 自由发挥，现场合成新题材" @click="synthGenre">
          <AppIcon name="zap" :size="12" /> 让 AI 自由发挥
        </button>
        <button class="btn-main" :disabled="busy || !hasSelection"
                aria-label="下一步：选择世界观骨架" @click="goSkeleton">
          下一步：选择骨架
        </button>
      </footer>
    </template>

    <!-- ===== 段 2：骨架选择 ===== -->
    <template v-else-if="stage === 'skeleton'">
      <div v-if="schemaLoading" class="gacha-loading" role="status">
        <span class="gc-spin" aria-hidden="true"></span>加载世界观骨架…
      </div>
      <section v-else class="wv-skeleton" aria-label="世界观骨架选择">
        <p class="wv-intro">挑一个世界观骨架作为基底，进入向导后可逐层微调；或选「空白自定义」从零开始。</p>

        <div class="wv-skel-grid" role="group" aria-label="骨架卡列表">
          <button v-for="preset in presetCards" :key="preset.key"
                  class="wv-skel-card"
                  :class="{ selected: chosenPresetKey === preset.key }"
                  :aria-label="`选择骨架：${preset.name}。${preset.vibe}`"
                  :aria-pressed="chosenPresetKey === preset.key"
                  @click="choosePreset(preset.key)">
            <div class="wv-skel-name">{{ preset.name }}</div>
            <div class="wv-skel-vibe">{{ preset.vibe }}</div>
            <ul class="wv-skel-chips" aria-hidden="true">
              <li v-for="h in presetHighlights(preset).slice(0, 4)" :key="h.paramKey">
                <span class="wv-skel-chip-label">{{ h.label }}</span>
                <span class="wv-skel-chip-val">{{ h.value }}</span>
              </li>
            </ul>
          </button>

          <!-- 随机骨架 -->
          <button class="wv-skel-card wv-skel-special"
                  :class="{ selected: chosenPresetKey !== null && chosenPresetKey !== 'blank' && !presetCards.some(p => p.key === chosenPresetKey) }"
                  aria-label="随机抽取一个骨架"
                  @click="choosePreset('random')">
            <AppIcon name="zap" :size="18" />
            <div class="wv-skel-name">随机骨架</div>
            <div class="wv-skel-vibe">掷骰子，从 10 个骨架里随机一个</div>
          </button>

          <!-- 空白自定义 -->
          <button class="wv-skel-card wv-skel-special"
                  :class="{ selected: chosenPresetKey === 'blank' }"
                  aria-label="空白自定义，从零开始逐层配置"
                  @click="choosePreset('blank')">
            <span class="wv-skel-blank-mark" aria-hidden="true">▢</span>
            <div class="wv-skel-name">空白自定义</div>
            <div class="wv-skel-vibe">不预填，进入向导后逐层选择</div>
          </button>
        </div>

        <footer class="gacha-foot">
          <button class="btn-line" aria-label="返回题材选择" @click="backToTheme">← 返回题材</button>
          <button class="btn-main" :disabled="chosenPresetKey === null"
                  aria-label="下一步：进入世界观向导" @click="goWizard">
            下一步：进入向导
          </button>
        </footer>
      </section>
    </template>

    <!-- ===== 段 3：十层向导 ===== -->
    <template v-else>
      <section v-if="schemaVM" class="wv-wizard" aria-label="世界观十层向导">
        <!-- 左进度轨 -->
        <nav class="wv-rail" aria-label="世界观层进度">
          <div class="wv-rail-track">
            <div class="wv-rail-fill" :style="{ width: layerProgressPct() + '%' }"></div>
          </div>
          <ol class="wv-rail-list" role="list">
            <li v-for="(layer, idx) in layers" :key="layer.id"
                class="wv-rail-item"
                :class="['st-' + layerStatus(layer.id), { active: idx === currentLayerIdx }]"
                :aria-current="idx === currentLayerIdx ? 'step' : undefined">
              <button class="wv-rail-btn"
                      :aria-label="`${layer.id} ${layer.name}${layer.covered ? '' : '（即将上线）'}`"
                      :disabled="!layer.covered"
                      @click="jumpLayer(idx)">
                <span class="wv-rail-mark" aria-hidden="true">
                  <template v-if="!layer.covered">○</template>
                  <template v-else-if="layerStatus(layer.id) === 'done'">✓</template>
                  <template v-else-if="layerStatus(layer.id) === 'violation'">!</template>
                  <template v-else-if="idx === currentLayerIdx">●</template>
                  <template v-else>○</template>
                </span>
                <span class="wv-rail-id">{{ layer.id }}</span>
                <span class="wv-rail-name">{{ layer.name }}</span>
                <span v-if="!layer.covered" class="wv-rail-soon">即将上线</span>
              </button>
            </li>
          </ol>
        </nav>

        <!-- 右参数卡片 -->
        <div class="wv-panel" role="region" :aria-label="`当前层：${currentLayer?.name ?? ''}`">
          <div v-if="currentLayer" class="wv-panel-head">
            <h3>
              <span class="wv-panel-id">{{ currentLayer.id }}</span>
              {{ currentLayer.name }}
            </h3>
            <p class="wv-panel-desc">{{ currentLayer.desc }}</p>
            <div v-if="evalPending" class="wv-eval-pending" role="status">
              <span class="gc-spin gc-spin-sm" aria-hidden="true"></span>校验中…
            </div>
            <div v-else-if="evalVM.hasViolations" class="wv-eval-bad" role="alert">
              当前世界观存在 {{ evalVM.violations.length }} 处违例，将无法确认开工（违例项以红色标注）。
            </div>
            <div v-else-if="Object.keys(wvProfile).length > 0" class="wv-eval-ok">
              ✓ 暂无跨层违例
            </div>
          </div>

          <!-- 占位层（即将上线） -->
          <div v-if="currentLayer && !currentLayer.covered" class="wv-soon-card">
            <div class="wv-soon-mark" aria-hidden="true">⏳</div>
            <p>本层参数尚未数据化，即将上线。</p>
            <p class="wv-soon-hint">可继续配置其他已上线层，或直接确认开工。</p>
          </div>

          <!-- 已上线层参数卡 -->
          <div v-else-if="currentLayer" class="wv-params">
            <div v-for="param in currentLayer.params" :key="param.key"
                 class="wv-param"
                 :class="{ violated: evalVM.violationSet.has(param.key) }">
              <div class="wv-param-head">
                <span class="wv-param-label">{{ param.label }}</span>
                <button v-if="selectedValue(param.key)"
                        class="wv-param-clear btn-line btn-line-xs"
                        :aria-label="`清除 ${param.label} 的选择`"
                        @click="clearParam(param.key)">清除</button>
              </div>
              <div class="wv-chips" role="group" :aria-label="`${param.label} 的选项`">
                <button v-for="opt in param.options" :key="opt.value"
                        class="wv-chip"
                        :class="{
                          selected: selectedValue(param.key) === opt.value,
                          disabled: optionDisabled(param.key, opt.value),
                          violated: optionViolated(param.key, opt.value),
                        }"
                        :disabled="optionDisabled(param.key, opt.value)"
                        :aria-pressed="selectedValue(param.key) === opt.value"
                        :aria-label="`${param.label}：${opt.label}`"
                        :title="optionDisabled(param.key, opt.value)
                          ? optionDisabledReason(param.key, opt.value)
                          : (opt.hint || opt.label)"
                        @click="chooseParam(param.key, opt.value)">
                  <span class="wv-chip-label">{{ opt.label }}</span>
                  <span v-if="opt.hint" class="wv-chip-hint">{{ opt.hint }}</span>
                </button>
              </div>
              <p v-if="chainHint(currentLayer.params.find(p => p.key === param.key)?.options?.find(o => o.value === selectedValue(param.key)) || {})"
                 class="wv-chain">
                连锁：{{ chainHint(currentLayer.params.find(p => p.key === param.key)?.options?.find(o => o.value === selectedValue(param.key)) || {}) }}
              </p>
              <ul v-if="evalVM.byParam[param.key]" class="wv-violations" role="alert">
                <li v-for="(v, i) in evalVM.byParam[param.key]" :key="i">
                  <b>⚠ 违例：</b>{{ v.message }}（当前取值：{{ v.value }}）
                </li>
              </ul>
            </div>
          </div>

          <!-- 底部导航 -->
          <footer class="wv-nav">
            <button class="btn-line" :disabled="currentLayerIdx === 0"
                    aria-label="返回上一层" @click="prevLayer">← 上一层</button>
            <button v-if="!isLastLayer" class="btn-main"
                    :disabled="currentLayerIdx >= layers.length - 1"
                    aria-label="进入下一层" @click="nextLayer">下一层 →</button>
            <button v-else ref="startBtn" class="btn-main"
                    :disabled="busy"
                    aria-label="确认开工，按当前配置开始创作" @click="requestConfirm">
              {{ confirmBusy ? '开工中…' : '确认开工' }}
            </button>
          </footer>
        </div>
      </section>
    </template>

    <!-- 开工方式弹层（P10.4；alertdialog + 焦点管理 + Esc 取消） -->
    <div v-if="startOpen" class="gacha-overlay" @keydown="onDialogKeydown">
      <div ref="dialogEl" class="gacha-dialog" role="alertdialog" aria-modal="true"
           aria-labelledby="gacha-dlg-t" aria-describedby="gacha-dlg-d">
        <div id="gacha-dlg-t" class="gd-title">开工方式</div>
        <p id="gacha-dlg-d" class="gd-desc">另开一个新项目，或在当前项目里继续。</p>

        <label class="gd-opt">
          <input type="radio" v-model="startMode" value="new" :disabled="confirmBusy">
          <span>作为新项目开局</span>
        </label>
        <div v-if="startMode === 'new'" class="gd-name-row">
          <input v-model.trim="projectName" class="gd-input" :disabled="confirmBusy" maxlength="40"
                 aria-label="新项目名，可用中文、字母、数字、空格、连字符和下划线" :placeholder="suggestedName">
          <div class="gd-hint" :class="{ bad: projectName && !nameValid }">
            将作为新项目目录名：可用中文/字母/数字/空格/-/_，≤40 字符，不能以空格或点开头结尾
          </div>
        </div>

        <label class="gd-opt">
          <input type="radio" v-model="startMode" value="current" :disabled="confirmBusy">
          <span>当前项目继续</span>
        </label>
        <p v-if="startMode === 'current' && chapterCount > 0" class="gd-warn">
          当前项目已有 {{ chapterCount }} 章。开工后已有章节、世界状态与待批准方案都会被清空，且不可恢复。
        </p>

        <div class="gd-act">
          <button ref="cancelBtn" class="btn-line" :disabled="confirmBusy" aria-label="取消，不开工"
                  @click="cancelConfirm">取消</button>
          <button class="btn-main" :disabled="confirmBusy || (startMode === 'new' && !nameValid)"
                  :aria-label="startMode === 'new' ? `以新项目 ${projectName} 开工` : '在当前项目开工'"
                  @click="doConfirm">{{ confirmBusy ? '开工中…' : '确认开工' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
