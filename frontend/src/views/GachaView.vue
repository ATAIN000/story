<script setup>
/* 抽卡开局页（P20 临时工作区 session 模式）
 *   段 1 题材选择 → POST /api/gacha/begin 获取 session_id
 *   → 段 2-4 世界观/人物/冲突检测全部走 session 端点
 *   → 段 5 宏观规划用 WebSocket 流式生成
 *   → 确认开工 POST /api/gacha/{sid}/confirm
 *   → 离开时 POST /api/gacha/{sid}/cancel 清理
 *
 * a11y：层/卡 aria-label、chips role="group"、键盘可达、对话框焦点圈保留。
 */
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { api } from '../api/api'
import { toGachaCardVM, toGenreListVM, displayName, toWorldviewSchemaVM, toEvaluateVM } from '../api/adapters'
import { presetToLayers } from '../api/worldviewPresets'
import { useToast } from '../composables/useToast'
import AppIcon from '../components/AppIcon.vue'
import MacroDashboard from '../components/MacroDashboard.vue'

const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})
defineEmits(['refresh', 'navigate'])

const { toast, toastError } = useToast()
const dn = (id) => displayName(props.config, id)

/* ===== 段 1：题材选择（P20 session 模式） ===== */
const genreList = ref(null)                // toGenreListVM 输出
const genres = computed(() => genreList.value?.genres ?? [])
const listLoading = ref(false)
const selectedGenre = ref(null)            // 选中题材 name
const synthLoading = ref(false)
const synthElapsed = ref(0)
let synthTimer = null
const startOpen = ref(false)
const startMode = ref('new')  // P18: 抽卡开局始终创建新项目（一项目一目录设计）
const projectName = ref('')
const confirmBusy = ref(false)
/* synth 模式产出的精简卡（source=synth 时存 genre yaml） */
const synthCard = ref(null)

/* P20: gacha session_id（进入题材后创建，离开时清理） */
const sessionId = ref(null)

const startBtn = ref(null)
const dialogEl = ref(null)
const cancelBtn = ref(null)

const chapterCount = computed(() => (props.project?.chapters ?? []).length)
const busy = computed(() => listLoading.value || confirmBusy.value)

const NAME_RE = /^[\p{L}\p{N} _-]+$/u
const RESERVED_RE = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i
const selectedGenreVM = computed(() => genres.value.find(g => g.name === selectedGenre.value) ?? null)
const currentGenreName = computed(() => selectedGenre.value || synthCard.value?.genre?.name || null)
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
const stage = ref('theme')    // 'theme' | 'skeleton' | 'wizard' | 'cast' | 'macro'
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
  /* P20: 离开时清理未完成的 gacha session */
  if (sessionId.value) {
    api.gachaCancel(sessionId.value).catch(() => {})
    sessionId.value = null
  }
})

/* ---- 段 1 题材列表 ---- */
async function loadGenres() {
  if (listLoading.value) return
  listLoading.value = true
  try {
    const d = await api.gachaGenres()
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
    const d = await api.gachaSynth()
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

/* ---- 段 1 → 段 2（选中题材后创建 session） ---- */
async function goSkeleton() {
  if (!hasSelection.value || busy.value) return
  /* P20: 创建临时工作区 session */
  if (!sessionId.value) {
    const genreName = synthCard.value?.genre?.name || selectedGenre.value
    if (!genreName) return
    try {
      const res = await api.gachaBegin(genreName)
      sessionId.value = res.session_id
    } catch (e) {
      toastError(`创建开局会话失败：${e.message}`)
      return
    }
  }
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
function backToWizard() { stage.value = 'wizard' }

/* ---- 段 3 → 段 4（人物原型） ---- */
function goCast() {
  stage.value = 'cast'
  /* 自动调一次 derive_cast 预填主角 */
  if (castCards.value.length === 0) autoDeriveCast()
}

/* ===== 段 4.5：跨层冲突检测（③.5 Patch A） ===== */
const crossCheckLoading = ref(false)
const crossCheckWarnings = ref([])
const conflictAccepted = ref(false)

/* 段 4 → 段 4.5（跨层冲突检测）→ 段 5（宏观规划） */
function goCrossCheck() {
  stage.value = 'crosscheck'
  runCrossCheck()
}

function backToCastFromCross() { stage.value = 'cast' }

async function runCrossCheck() {
  crossCheckLoading.value = true
  crossCheckWarnings.value = []
  try {
    const wvPayload = Object.keys(wvProfile.value).length > 0
      ? { layers: wvProfile.value } : null
    const castPayload = buildCastPayload()
    const res = await api.gachaSessionCrossCheck(sessionId.value, wvPayload, castPayload)
    crossCheckWarnings.value = res.warnings ?? []
  } catch (e) {
    /* 跨层检测失败不阻塞流程 */
    toastError(`跨层检测失败：${e.message}`)
  } finally {
    crossCheckLoading.value = false
  }
}

function acceptConflicts() {
  /* 接受冲突，冲突标记传给宏观规划 */
  conflictAccepted.value = true
  goMacro()
}

function backToWizardFromCross() { stage.value = 'wizard' }

/* ---- 段 4.5 → 段 5（宏观规划） ---- */
function goMacro() {
  stage.value = 'macro'
  if (macroTemplates.value.length === 0) loadMacroTemplates()
}

function backToCast() { stage.value = 'cast' }

/* ===== 段 5：宏观规划函数 ===== */
async function loadMacroTemplates() {
  if (macroTemplateLoading.value) return
  macroTemplateLoading.value = true
  try {
    const res = await api.macroTemplates()
    macroTemplates.value = res.templates ?? []
  } catch (e) {
    toastError(`幕结构模板加载失败：${e.message}`)
  } finally {
    macroTemplateLoading.value = false
  }
}

const macroElapsed = ref(0)
let macroTimer = null
const macroStreamText = ref('')   // P20: WebSocket 流式文本累积

async function generateMacro() {
  if (macroGenerating.value) return
  if (!sessionId.value) {
    toastError('会话已过期，请重新选择题材')
    return
  }
  macroGenerating.value = true
  macroElapsed.value = 0
  macroStreamText.value = ''
  macroTimer = setInterval(() => { macroElapsed.value += 1 }, 1000)
  try {
    const wvPayload = Object.keys(wvProfile.value).length > 0
      ? { layers: wvProfile.value } : null
    const castPayload = buildCastPayload()
    const body = {
      template_name: selectedTemplate.value || 'save_the_cat_15',
    }
    if (wvPayload) body.worldview = wvPayload
    if (castPayload) body.cast = castPayload
    /* P18.2: 冲突标记注入 */
    if (conflictAccepted.value && crossCheckWarnings.value.length > 0) {
      body.conflict_warnings = crossCheckWarnings.value
    }
    /* P20: WebSocket 流式生成（Vite 需 ws:true 代理；关闭/超时必须 settle Promise） */
    macroPlan.value = await new Promise((resolve, reject) => {
      let settled = false
      const finish = (fn, arg) => {
        if (settled) return
        settled = true
        clearTimeout(connectTimer)
        try { ws.close() } catch { /* ignore */ }
        fn(arg)
      }
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${proto}//${location.host}/api/gacha/${sessionId.value}/macro/stream`
      const ws = new WebSocket(wsUrl)
      const connectTimer = setTimeout(() => {
        finish(reject, new Error('WebSocket 连接超时（检查 Vite 是否代理 ws）'))
      }, 15000)
      ws.onopen = () => {
        clearTimeout(connectTimer)
        ws.send(JSON.stringify(body))
      }
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data)
          if (msg.type === 'delta') {
            macroStreamText.value += msg.text
          } else if (msg.type === 'complete') {
            macroStreamText.value = ''
            finish(resolve, msg.plan)
          } else if (msg.type === 'error') {
            /* 错误但可能有 mock 兜底（complete 会跟随） */
            toastError(msg.msg || '宏观生成出错')
          }
        } catch { /* ignore parse errors */ }
      }
      ws.onerror = () => finish(reject, new Error('WebSocket 连接失败'))
      ws.onclose = () => {
        if (!settled) {
          finish(reject, new Error(
            macroStreamText.value ? '流式生成未完成' : 'WebSocket 已断开'))
        }
      }
    })
    expandedMacroSection.value = 'blueprint'
    toast('宏观计划已生成')
  } catch (e) {
    toastError(`宏观计划生成失败：${e.message}`)
  } finally {
    clearInterval(macroTimer)
    macroTimer = null
    macroGenerating.value = false
  }
}

/* P18.2: 单组件重摇（P20: 改用 WebSocket 全局重生成，单组件级别后续支持） */
const regeneratingComponent = ref('')
async function regenerateComponent(component) {
  if (regeneratingComponent.value) return
  if (!macroPlan.value) return
  regeneratingComponent.value = component
  /* P20: 单组件重摇暂走全局重新生成（WebSocket 不支持单组件路径） */
  await generateMacro()
  if (macroPlan.value) toast(`「${component}」已重新生成`)
  regeneratingComponent.value = ''
}

function skipMacro() {
  macroPlan.value = null
  requestConfirm()
}

function confirmMacro() {
  requestConfirm()
}

/* ===== 段 4：人物原型向导（多角色管理） ===== */
const castCards = ref([])         // [{name, role, persona: {key: value}}]
const deriveLoading = ref(false)

/* ===== 段 5：宏观规划（P17.5） ===== */
const macroTemplates = ref([])
const macroTemplateLoading = ref(false)
const selectedTemplate = ref('save_the_cat_15')
const macroPlan = ref(null)           // 生成的 MacroPlan dict
const macroGenerating = ref(false)

/* 角色卡persona的字段分组（来自 CHARACTER_LAYERS schema） */
const charParamsByLayer = computed(() => {
  const out = []
  for (const layer of characterLayers.value) {
    out.push({
      id: layer.id,
      name: layer.name,
      params: layer.params.map(p => ({
        key: p.key,
        label: p.label,
        type: p.options.length === 1 && p.options[0].value === '__text__' ? 'text' : 'enum',
        options: p.options.filter(o => o.value !== '__text__'),
      })),
    })
  }
  return out
})

const MAX_SUPPORTING = 8

function makeBlankCard(role = '配角') {
  return { name: '', role, persona: {} }
}

function addCastCard() {
  if (castCards.value.length >= MAX_SUPPORTING + 1) return
  castCards.value.push(makeBlankCard())
}

function removeCastCard(idx) {
  castCards.value.splice(idx, 1)
  if (castCards.value.length === 0) {
    castCards.value.push(makeBlankCard('主角'))
  }
  /* 确保第一个是主角 */
  if (castCards.value.length > 0) castCards.value[0].role = '主角'
}

function setPersonaParam(card, paramKey, value) {
  card.persona[paramKey] = value
}

function clearPersonaParam(card, paramKey) {
  delete card.persona[paramKey]
}

async function autoDeriveCast() {
  if (deriveLoading.value) return
  if (!sessionId.value) {
    toastError('会话已过期，请重新选择题材')
    return
  }
  deriveLoading.value = true
  try {
    /* 从当前 wvProfile 拆分 worldview / language layers */
    const wvLayers = {}
    const langLayers = {}
    for (const [layerId, params] of Object.entries(wvProfile.value)) {
      if (layerId.startsWith('LANG')) langLayers[layerId] = params
      else if (!layerId.startsWith('CHAR')) wvLayers[layerId] = params
    }
    const res = await api.gachaSessionDeriveCast(sessionId.value, wvLayers, langLayers)
    const suggested = res.cast ?? []
    if (suggested.length > 0) {
      castCards.value = suggested.map((c, i) => ({
        name: c.name || `角色${i + 1}`,
        role: c.role || (i === 0 ? '主角' : '配角'),
        persona: { ...(c.persona || {}) },
      }))
      toast('AI 已自动分配人物原型')
    } else {
      toastError('AI 未能推导出人物原型，请手动填写')
    }
  } catch (e) {
    toastError(`人物原型推导失败：${e.message}`)
  } finally {
    deriveLoading.value = false
  }
}

/* 确认时将 castCards 组装成 cast payload（name 与 id 双写，兼容后端摘要） */
function buildCastPayload() {
  if (castCards.value.length === 0) return null
  return castCards.value
    .filter(c => c.name.trim())
    .map(c => ({
      id: c.name.trim(),
      name: c.name.trim(),
      role: c.role,
      persona: c.persona,
    }))
}

/* ---- 段 3 向导 ---- */
const layers = computed(() => schemaVM.value?.layers ?? [])
/* 世界观层（L0-L9）与语言文化层（LANG1-LANG5）分离，用于左栏分区展示 */
const worldviewLayers = computed(() => layers.value.filter(l => !l.id.startsWith('LANG') && !l.id.startsWith('CHAR')))
const languageLayers = computed(() => layers.value.filter(l => l.id.startsWith('LANG')))
const characterLayers = computed(() => layers.value.filter(l => l.id.startsWith('CHAR')))
const currentLayer = computed(() => layers.value[currentLayerIdx.value] ?? null)
const isLastLayer = computed(() => {
  /* 跳过 CHAR 层（CHAR1-CHAR5 在人物原型段处理）——找到最后一个非 CHAR 层 */
  const nonCharLayers = layers.value.filter(l => !l.id.startsWith('CHAR'))
  return currentLayerIdx.value === layers.value.indexOf(nonCharLayers[nonCharLayers.length - 1])
})

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
  /* CHAR 层不在向导中处理 */
  if (layers.value[idx]?.id?.startsWith('CHAR')) return
  currentLayerIdx.value = idx
}

function layerProgressPct() {
  /* 排除 CHAR 层（人物原型在段 4 处理，不在向导进度中计算） */
  const wizardLayers = layers.value.filter(l => !l.id.startsWith('CHAR'))
  if (!wizardLayers.length) return 0
  const done = wizardLayers.filter(l => {
    if (!l.covered) return false
    const s = layerStatus(l.id)
    return s === 'done' || s === 'violation' || s === 'current'
  }).length
  return (done / wizardLayers.length) * 100
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
  /* 跳过 CHAR 层（人物原型在段 4 处理） */
  let idx = currentLayerIdx.value + 1
  while (idx < layers.value.length && layers.value[idx]?.id?.startsWith('CHAR')) idx++
  if (idx < layers.value.length) currentLayerIdx.value = idx
}
function prevLayer() {
  let idx = currentLayerIdx.value - 1
  while (idx >= 0 && layers.value[idx]?.id?.startsWith('CHAR')) idx--
  if (idx >= 0) currentLayerIdx.value = idx
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
    startMode.value = 'new'  // P18: 始终新项目
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
  if (!sessionId.value) {
    toastError('会话已过期，请重新选择题材')
    return
  }
  const name = projectName.value.trim()
  if (!nameValid.value) return
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
    const castPayload = buildCastPayload()
    const extras = {}
    if (wvPayload) extras.worldview = wvPayload
    if (castPayload) extras.cast = castPayload
    if (macroPlan.value) extras.macro_plan = macroPlan.value
    const res = await api.gachaSessionConfirm(sessionId.value, name, extras)
    sessionId.value = null   /* confirm 后 session 已被后端清理 */
    startOpen.value = false
    const finalGenre = res.project?.genre ?? ''
    const culture = res.project?.culture ?? ''
    toast(`新项目《${res.project?.name ?? name}》已开工：${dn(finalGenre)} × ${dn(culture)}`)
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
      <p class="gacha-sub">题材决定轨道/节奏/评估权重/人物阵容，世界观决定设定/规则。选题材 → 选骨架 → 世界观+语言向导 → 人物原型 → 宏观规划 → 开工。</p>
      <!-- 五段式面包屑 -->
      <ol class="gacha-stages" role="list">
        <li :class="{ active: stage === 'theme', done: stage !== 'theme' }">
          <span class="gs-idx">1</span><span class="gs-name">题材选择</span>
        </li>
        <li :class="{ active: stage === 'skeleton', done: ['wizard','cast','crosscheck','macro'].includes(stage), disabled: !hasSelection }">
          <span class="gs-idx">2</span><span class="gs-name">骨架选择</span>
        </li>
        <li :class="{ active: stage === 'wizard', done: ['cast','crosscheck','macro'].includes(stage), disabled: !hasSelection }">
          <span class="gs-idx">3</span><span class="gs-name">世界观向导</span>
        </li>
        <li :class="{ active: stage === 'cast', done: ['crosscheck','macro'].includes(stage), disabled: !hasSelection }">
          <span class="gs-idx">4</span><span class="gs-name">人物原型</span>
        </li>
        <li :class="{ active: stage === 'crosscheck', done: stage === 'macro', disabled: !hasSelection }">
          <span class="gs-idx">4.5</span><span class="gs-name">冲突检测</span>
        </li>
        <li :class="{ active: stage === 'macro', disabled: !hasSelection }">
          <span class="gs-idx">5</span><span class="gs-name">宏观规划</span>
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
                data-testid="genre-card"
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
                data-testid="synth-genre"
                aria-label="让 AI 自由发挥，现场合成新题材" @click="synthGenre">
          <AppIcon name="zap" :size="12" /> 让 AI 自由发挥
        </button>
        <button class="btn-main" :disabled="busy || !hasSelection"
                data-testid="gacha-next-skeleton"
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
                  data-testid="skeleton-card"
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
          <button class="btn-line" aria-label="返回题材选择" data-testid="skeleton-back" @click="backToTheme">← 返回题材</button>
          <button class="btn-main" :disabled="chosenPresetKey === null"
                  aria-label="下一步：进入世界观向导" data-testid="skeleton-next" @click="goWizard">
            下一步：进入向导
          </button>
        </footer>
      </section>
    </template>

    <!-- ===== 段 3：世界观 + 语言文化向导 ===== -->
    <template v-else-if="stage === 'wizard'">
      <section v-if="schemaVM" class="wv-wizard" aria-label="世界观十层向导">
        <!-- 左进度轨 -->
        <nav class="wv-rail" aria-label="世界观层进度">
          <div class="wv-rail-track">
            <div class="wv-rail-fill" :style="{ width: layerProgressPct() + '%' }"></div>
          </div>
          <ol class="wv-rail-list" role="list">
            <li v-for="(layer, idx) in worldviewLayers" :key="layer.id"
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
          <template v-if="languageLayers.length">
            <div class="wv-rail-divider" role="separator" aria-label="语言文化分区">
              <span>语言文化</span>
            </div>
            <ol class="wv-rail-list" role="list">
              <li v-for="layer in languageLayers" :key="layer.id"
                  class="wv-rail-item"
                  :class="['st-' + layerStatus(layer.id), { active: layers[currentLayerIdx]?.id === layer.id }]">
                <button class="wv-rail-btn"
                        :aria-label="`${layer.id} ${layer.name}${layer.covered ? '' : '（即将上线）'}`"
                        :disabled="!layer.covered"
                        @click="jumpLayer(layers.findIndex(l => l.id === layer.id))">
                  <span class="wv-rail-mark" aria-hidden="true">
                    <template v-if="!layer.covered">○</template>
                    <template v-else-if="layerStatus(layer.id) === 'done'">✓</template>
                    <template v-else-if="layerStatus(layer.id) === 'violation'">!</template>
                    <template v-else-if="layers[currentLayerIdx]?.id === layer.id">●</template>
                    <template v-else>○</template>
                  </span>
                  <span class="wv-rail-id">{{ layer.id }}</span>
                  <span class="wv-rail-name">{{ layer.name }}</span>
                  <span v-if="!layer.covered" class="wv-rail-soon">即将上线</span>
                </button>
              </li>
            </ol>
          </template>
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
                        data-testid="wizard-param-chip"
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
                    aria-label="返回上一层" data-testid="wizard-prev-layer" @click="prevLayer">← 上一层</button>
            <button v-if="!isLastLayer" class="btn-main"
                    :disabled="currentLayerIdx >= layers.length - 1"
                    aria-label="进入下一层" data-testid="wizard-next-layer" @click="nextLayer">下一层 →</button>
            <button v-else class="btn-main"
                    aria-label="下一步：人物原型" data-testid="wizard-go-cast" @click="goCast">
              下一步：人物原型 →
            </button>
          </footer>
        </div>
      </section>
    </template>

    <!-- ===== 段 4：人物原型向导（多角色管理） ===== -->
    <template v-else-if="stage === 'cast'">
      <section class="wv-cast-stage" aria-label="人物原型向导">
        <div class="wv-cast-head">
          <p class="wv-intro">为每个角色配置人物原型（CHAR1-CHAR5）。主角必填，配角可选。点击「AI 自动分配」从当前世界观推导合理原型。</p>
          <button class="btn-line" :disabled="deriveLoading"
                  data-testid="cast-auto-derive"
                  aria-label="从世界观+语言自动推导人物原型" @click="autoDeriveCast">
            {{ deriveLoading ? '推导中…' : '✦ AI 自动分配' }}
          </button>
        </div>

        <!-- 角色卡列表 -->
        <div class="wv-cast-cards">
          <div v-for="(card, idx) in castCards" :key="idx" class="wv-cast-card"
               :class="{ main: idx === 0 }"
               :data-testid="`cast-card-${idx}`">
            <div class="wv-cast-card-head">
              <span class="wv-cast-badge" :class="{ main: idx === 0 }">{{ idx === 0 ? '主角' : `配角 ${idx}` }}</span>
              <input v-model.trim="card.name" class="wv-cast-name-input"
                     :placeholder="idx === 0 ? '主角名（必填）' : '配角名'"
                     :aria-label="`${idx === 0 ? '主角' : '配角'}名`"
                     maxlength="20">
              <button v-if="idx > 0" class="wv-cast-del btn-line btn-line-xs"
                      :aria-label="`删除配角 ${idx}`" @click="removeCastCard(idx)">删除</button>
            </div>

            <!-- CHAR1-CHAR5 分区 -->
            <div v-for="layer in charParamsByLayer" :key="layer.id" class="wv-char-layer">
              <div class="wv-char-layer-name">{{ layer.id }} · {{ layer.name }}</div>
              <div v-for="param in layer.params" :key="param.key" class="wv-char-param">
                <span class="wv-char-param-label">{{ param.label }}</span>
                <!-- 枚举参数：chips -->
                <div v-if="param.type === 'enum'" class="wv-char-chips" role="group"
                     :aria-label="`${param.label} 选项`">
                  <button v-for="opt in param.options" :key="opt.value"
                          class="wv-char-chip"
                          :class="{ selected: card.persona[param.key] === opt.value }"
                          :aria-pressed="card.persona[param.key] === opt.value"
                          :aria-label="opt.label"
                          :title="opt.hint || opt.label"
                          @click="setPersonaParam(card, param.key, opt.value)">
                    {{ opt.label }}
                  </button>
                </div>
                <!-- 文本参数：input -->
                <div v-else class="wv-char-text-input">
                  <input v-model="card.persona[param.key]" class="wv-cast-text-field"
                         :placeholder="param.label" :aria-label="param.label"
                         @input="setPersonaParam(card, param.key, $event.target.value)">
                </div>
              </div>
            </div>
          </div>
        </div>

        <button v-if="castCards.length < MAX_SUPPORTING + 1" class="wv-cast-add btn-line"
                aria-label="添加配角" data-testid="cast-add" @click="addCastCard">+ 添加配角</button>

        <footer class="gacha-foot">
          <button class="btn-line" aria-label="返回世界观向导" data-testid="cast-back" @click="backToWizard">← 返回向导</button>
          <button class="btn-main"
                  :disabled="busy"
                  aria-label="下一步：跨层冲突检测" data-testid="cast-next-crosscheck" @click="goCrossCheck">
            下一步：冲突检测 →
          </button>
        </footer>
      </section>
    </template>

    <!-- ===== 段 4.5：跨层冲突检测（③.5 Patch A） ===== -->
    <template v-else-if="stage === 'crosscheck'">
      <section class="wv-crosscheck-stage" aria-label="跨层冲突检测">
        <div class="wv-crosscheck-head">
          <p class="wv-intro">系统自动扫描 5 类跨层冲突（题材×力量体系 / 人物×社会 / 力量多源 / 基调×节奏 / 语言×密度），发现冲突会给出修正建议。</p>
        </div>

        <div v-if="crossCheckLoading" class="gacha-loading" role="status">
          <span class="gc-spin" aria-hidden="true"></span>正在扫描跨层冲突…
        </div>

        <div v-else-if="crossCheckWarnings.length === 0" class="wv-crosscheck-ok" role="status">
          <div class="wv-crosscheck-ok-icon">✅</div>
          <p>所有层次对齐，未发现跨层冲突。可以安全进入宏观规划。</p>
        </div>

        <div v-else class="wv-crosscheck-warnings">
          <div v-for="(w, i) in crossCheckWarnings" :key="i"
               class="wv-cc-warning"
               :class="'sev-' + w.severity.toLowerCase()">
            <div class="wv-cc-sev">
              <span class="wv-cc-icon">{{ w.severity === 'HIGH' ? '🔴' : w.severity === 'MEDIUM' ? '🟡' : '🟢' }}</span>
              <span class="wv-cc-type">{{ w.type }}</span>
              <span class="wv-cc-severity">{{ w.severity }}</span>
            </div>
            <div class="wv-cc-title">{{ w.title }}</div>
            <p class="wv-cc-desc">{{ w.description }}</p>
            <p class="wv-cc-suggestion">💡 {{ w.suggestion }}</p>
          </div>
        </div>

        <footer class="gacha-foot">
          <button class="btn-line" aria-label="返回人物原型" data-testid="crosscheck-back" @click="backToCastFromCross">← 返回人物</button>
          <button class="btn-line" aria-label="返回世界观向导修改设定" data-testid="crosscheck-back-wizard" @click="backToWizardFromCross">🔧 回③修改设定</button>
          <button class="btn-main"
                  :disabled="busy"
                  data-testid="crosscheck-accept"
                  aria-label="接受并继续到宏观规划" @click="acceptConflicts">
            {{ crossCheckWarnings.length > 0 ? '✅ 接受继续' : '✅ 进入宏观规划' }} →
          </button>
        </footer>
      </section>
    </template>

    <!-- ===== 段 5：宏观规划（P17.5） ===== -->
    <template v-else-if="stage === 'macro'">
      <section class="wv-macro-stage" aria-label="宏观规划">
        <div class="wv-macro-head">
          <p class="wv-intro">选择幕结构模板，AI 生成完整的宏观计划（六大组件）。生成后可审阅、重摇或跳过（无宏观计划也可开工）。</p>
        </div>

        <!-- 模板选择 -->
        <div v-if="macroTemplateLoading" class="gacha-loading" role="status">
          <span class="gc-spin" aria-hidden="true"></span>加载幕结构模板…
        </div>
        <div v-else class="wv-macro-templates" role="group" aria-label="幕结构模板选择">
          <button v-for="t in macroTemplates" :key="t.name"
                  class="wv-macro-tmpl-card"
                  :class="{ selected: selectedTemplate === t.name }"
                  :aria-pressed="selectedTemplate === t.name"
                  :aria-label="`选择模板：${t.title || t.name}（${t.beat_count} 拍）`"
                  data-testid="macro-template-card"
                  @click="selectedTemplate = t.name">
            <div class="wv-macro-tmpl-name">{{ t.title || t.name }}</div>
            <div v-if="t.description" class="wv-macro-tmpl-desc">{{ t.description }}</div>
            <div class="wv-macro-tmpl-beats">{{ t.beat_count }} 拍</div>
          </button>
        </div>

        <!-- 生成按钮 -->
        <div class="wv-macro-gen-row">
          <button class="btn-main" :disabled="macroGenerating"
                  data-testid="macro-generate"
                  aria-label="AI 生成宏观计划" @click="generateMacro">
            {{ macroGenerating ? `生成中…（${macroElapsed}s）` : '✦ AI 生成宏观计划' }}
          </button>
          <div v-if="macroGenerating" class="wv-macro-progress">
            <span class="gc-spin" aria-hidden="true"></span>
            <span class="wv-macro-prog-text">
              已等待 {{ macroElapsed }} 秒
              <br><span class="wv-macro-prog-hint">LLM 正在生成中，下方可实时看到输出</span>
            </span>
          </div>
        </div>

        <!-- P20: 流式文本实时显示区 -->
        <div v-if="macroStreamText" class="wv-macro-stream" role="status" aria-label="LLM 流式输出">
          <pre class="wv-macro-stream-pre">{{ macroStreamText }}</pre>
        </div>

        <!-- 审阅面板：复用 MacroDashboard（compact + 重摇） -->
        <div v-if="macroPlan" class="wv-macro-review">
          <!-- 冲突约束提示 -->
          <div v-if="conflictAccepted && crossCheckWarnings.length > 0" class="wv-macro-conflict-note">
            <span class="wv-macro-conflict-badge">⚠️ 冲突约束已注入</span>
            <span class="wv-macro-conflict-count">{{ crossCheckWarnings.length }} 条</span>
          </div>

          <MacroDashboard
            :plan="macroPlan"
            compact
            show-regen
            :regenerating="regeneratingComponent"
            @regenerate="regenerateComponent"
          />
        </div>

        <footer class="gacha-foot">
          <button class="btn-line" aria-label="返回冲突检测" data-testid="macro-back" @click="stage = 'crosscheck'">← 返回冲突检测</button>
          <button v-if="macroPlan" class="btn-line" :disabled="macroGenerating"
                  data-testid="macro-regenerate"
                  aria-label="重新生成宏观计划" @click="generateMacro">
            {{ macroGenerating ? '生成中…' : '↻ 全局重摇' }}
          </button>
          <button class="btn-line" aria-label="跳过宏观计划，直接开工" data-testid="macro-skip" @click="skipMacro">跳过</button>
          <button ref="startBtn" class="btn-main"
                  :disabled="busy"
                  data-testid="confirm-start"
                  aria-label="确认开工" @click="confirmMacro">
            {{ confirmBusy ? '开工中…' : '确认开工' }}
          </button>
        </footer>
      </section>
    </template>

    <!-- 开工方式弹层（P10.4；alertdialog + 焦点管理 + Esc 取消） -->
    <div v-if="startOpen" class="gacha-overlay" @keydown="onDialogKeydown">
      <div ref="dialogEl" class="gacha-dialog" role="alertdialog" aria-modal="true"
           aria-labelledby="gacha-dlg-t" aria-describedby="gacha-dlg-d">
        <div id="gacha-dlg-t" class="gd-title">确认开工</div>
        <p id="gacha-dlg-d" class="gd-desc">将创建一个新项目，包含当前选定的题材、世界观和宏观计划。</p>

        <div class="gd-name-row">
          <label class="gd-opt"><span>项目名称</span></label>
          <input v-model.trim="projectName" class="gd-input" :disabled="confirmBusy" maxlength="40"
                 data-testid="project-name-input"
                 aria-label="新项目名，可用中文、字母、数字、空格、连字符和下划线" :placeholder="suggestedName">
          <div class="gd-hint" :class="{ bad: projectName && !nameValid }">
            可用中文/字母/数字/空格/-/_，≤40 字符，不能以空格或点开头结尾
          </div>
        </div>

        <div class="gd-act">
          <button ref="cancelBtn" class="btn-line" :disabled="confirmBusy" aria-label="取消，不开工"
                  data-testid="confirm-cancel" @click="cancelConfirm">取消</button>
          <button class="btn-main" :disabled="confirmBusy || !nameValid"
                  data-testid="confirm-ok"
                  :aria-label="`以新项目 ${projectName} 开工`"
                  @click="doConfirm">{{ confirmBusy ? '开工中…' : '确认开工' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wv-macro-stream {
  margin: 12px 0;
  max-height: 400px;
  overflow: auto;
  border: 1px solid var(--border, #ddd);
  border-radius: 8px;
  background: var(--bg-code, #f6f8fa);
  padding: 12px;
}
.wv-macro-stream-pre {
  margin: 0;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}
</style>
