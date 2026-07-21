<script setup>
// 抽卡开局页（P8.6，阶段 1 简化卡面）：四栏卡（题材 × 文化 × 人物原型 × 世界规则）
// + 换一批 / 单换一栏 / 让 AI 自由发挥 / 确认开工。spec: docs/superpowers/specs/2026-07-20-gacha-init-design.md §5。
// P10.4：确认开工弹层两选 —— 作为新项目（项目名输入，默认 {genre}-{MMdd}，重名 409
// 提示并停留）/ 当前项目继续（原 reset+init 路径）；synth 等待提示带已等待秒数。
// 铁律执行：模板只消费 adapter VM（toGachaCardVM）；confirm payload 另持 draw
// 原始返回（synth 卡的 genre.yaml 须原样回传后端复核落盘，VM 按约不消费它）。
// 确认后跳写作台并触发第一章 plan：直接调 api.plan()（P6.6 最短真实路径）——
// 后端落 pending_plan，WriteView watch project 拾起即进 planned 流。
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { api } from '../api/api'
import { toGachaCardVM, displayName } from '../api/adapters'
import { useToast } from '../composables/useToast'
import AppIcon from '../components/AppIcon.vue'

const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})
const emit = defineEmits(['refresh', 'navigate'])

const { toast, toastError } = useToast()

/* P9.1：卡名显示中文 title，id 降为小字副标（synth 新题材未入库时回落 id） */
const dn = (id) => displayName(props.config, id)

const rawCard = ref(null)              // draw 原始返回（confirm payload；不进模板）
const card = computed(() => toGachaCardVM(rawCard.value))
const drawing = ref(false)             // 任意抽卡进行中（锁全部按钮防重入）
const synthLoading = ref(false)        // AI 自由发挥进行中
const synthElapsed = ref(0)            // synth 已等待秒数（P10.4 等待提示）
let synthTimer = null
const startOpen = ref(false)           // 开工方式弹层显隐（P10.4：原重置确认框扩展）
const startMode = ref('current')       // 'new' 作为新项目 | 'current' 当前项目继续
const projectName = ref('')            // 新项目名（弹层输入）
const confirmBusy = ref(false)         // confirm + plan 进行中

const startBtn = ref(null)             // 「确认开工」（对话框关闭后焦点归还）
const dialogEl = ref(null)
const cancelBtn = ref(null)

const chapterCount = computed(() => (props.project?.chapters ?? []).length)
const busy = computed(() => drawing.value || confirmBusy.value)

/* P10.4 新项目名：与后端 GENRE_NAME_RE 同口径（字母/数字开头，后可含 -/_，≤64）。
   建议值 {genre}-{MMdd}——genre 用卡 id 不用 displayName（中文 title 过不了白名单） */
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/
const suggestedName = computed(() => {
  const g = card.value?.genre.name || 'story'
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${g}-${mm}${dd}`
})
const nameValid = computed(() => NAME_RE.test(projectName.value))

const COLS = [
  { key: 'genre', label: '题材' },
  { key: 'culture', label: '文化' },
  { key: 'archetype', label: '人物原型' },
  { key: 'rules', label: '世界规则' },
]

onMounted(() => { draw('library') })
onBeforeUnmount(() => clearInterval(synthTimer))   // 中途跳走防 interval 泄漏

/* lock = 其余栏当前 name（被换栏缺省即重抽）；锁名已不在库内时后端宽容回退
   随机（P8.3 口径：前端可能带着上一轮卡面名单重抽） */
function buildLock(except = null) {
  const c = card.value
  if (!c) return {}
  const lock = {}
  if (except !== 'genre' && c.genre.name) lock.genre = c.genre.name
  if (except !== 'culture' && c.culture.name) lock.culture = c.culture.name
  if (except !== 'archetype' && c.archetype.name) lock.archetype = c.archetype.name
  if (except !== 'rules' && c.rulePacks.length) lock.rule_packs = c.rulePacks.map(p => p.name)
  return lock
}

async function draw(mode, lock = null) {
  if (drawing.value) return
  drawing.value = true
  synthLoading.value = mode === 'synth'
  if (synthLoading.value) {            // P10.4 等待提示：已等待秒数计时
    synthElapsed.value = 0
    synthTimer = setInterval(() => { synthElapsed.value += 1 }, 1000)
  }
  try {
    const d = await api.gachaDraw(mode, lock)
    rawCard.value = d
    if (d.note) toast(d.note)          // synth 降级 / mock 短路说明（P8.4）
  } catch (e) {
    toastError(`抽卡失败：${e.message}`)
  } finally {
    drawing.value = false
    synthLoading.value = false
    clearInterval(synthTimer)
    synthTimer = null
  }
}

const redrawAll = () => draw('library')
const redrawCol = (key) => draw('library', buildLock(key))
const synthGenre = () => draw('synth', buildLock())

/* ---- 确认开工（P10.4）：弹层两选 —— 作为新项目（输入项目名，默认 {genre}-{MMdd}）
   或当前项目继续。原「有章节先弹重置确认」（spec §3-5）并入本框：选当前项目
   且有章节时框内明示重置后果，确认即授权。 ---- */
function requestConfirm() {
  if (!card.value || busy.value) return
  startMode.value = 'current'
  projectName.value = suggestedName.value
  startOpen.value = true
  nextTick(() => { cancelBtn.value?.focus() })   // 默认焦点落在安全的「取消」
}

function cancelConfirm() {
  if (confirmBusy.value) return
  startOpen.value = false
  nextTick(() => { startBtn.value?.focus() })
}

/* 对话框键盘管理：Esc 取消；Tab 在框内控件（按钮+输入框）间循环（简易焦点圈） */
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
  if (!rawCard.value || confirmBusy.value) return
  const asNew = startMode.value === 'new'
  const name = asNew ? projectName.value.trim() : null
  if (asNew && !nameValid.value) return
  confirmBusy.value = true
  try {
    const res = await api.gachaConfirm(rawCard.value, name)
    startOpen.value = false
    /* 最终 genre 名以后端响应为准（synth 重名落盘可能带 -2 后缀，P8.5） */
    const finalGenre = res.genre ?? ''
    const culture = res.project?.culture ?? ''
    const suffix = res.persisted ? '（新题材已入库）' : ''
    toast(asNew
      ? `新项目《${res.project?.name ?? name}》已开工：${dn(finalGenre)} × ${dn(culture)}${suffix}`
      : `已开工：${dn(finalGenre)} × ${dn(culture)}${suffix}`)
    /* 第一章 plan：失败不阻塞跳转（写作台空态可重试同款 plan） */
    try {
      await api.plan()
    } catch (e) {
      toastError(`第 1 章方案生成失败：${e.message}（可到写作台重试）`)
    }
    emit('refresh')          // 项目已 reset+init（或整栈切到新项目）：重拉快照
    emit('navigate', 'write')
  } catch (e) {
    /* P10.4：409 项目重名 → 提示并停留弹层改名重试；其余错误同样停留可重试 */
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
      <h2>开局 · 抽一组开局配置</h2>
      <p class="gacha-sub">题材 × 文化 × 人物原型 × 世界规则，不喜欢就换，喜欢就开工。</p>
    </header>

    <div v-if="synthLoading" class="gacha-status" role="status">
      <span class="gc-spin" aria-hidden="true"></span>AI 正在生成题材包，通常 20-60 秒（已等待 {{ synthElapsed }} 秒）…
    </div>

    <div v-if="card" class="gacha-grid" role="region" aria-label="开局配置卡区" :aria-busy="drawing || undefined">
      <div v-for="col in COLS" :key="col.key" class="gacha-col">
        <div class="gc-col-t">{{ col.label }}</div>

        <div class="gacha-card">
          <!-- 题材：卡名 + source 徽标 + desc（P9.1：title 主显，id 小字） -->
          <template v-if="col.key === 'genre'">
            <span class="gacha-src" :class="{ synth: card.genre.source === 'synth' }">
              {{ card.genre.source === 'synth' ? 'AI 合成' : '库内' }}
            </span>
            <div class="gacha-name">{{ dn(card.genre.name) || '—' }}</div>
            <div v-if="card.genre.name && dn(card.genre.name) !== card.genre.name" class="gacha-id">{{ card.genre.name }}</div>
            <div class="gacha-desc">{{ card.genre.desc || '—' }}</div>
          </template>

          <!-- 文化 -->
          <template v-else-if="col.key === 'culture'">
            <div class="gacha-name">{{ dn(card.culture.name) || '—' }}</div>
            <div v-if="card.culture.name && dn(card.culture.name) !== card.culture.name" class="gacha-id">{{ card.culture.name }}</div>
            <div class="gacha-desc">{{ card.culture.desc || '—' }}</div>
          </template>

          <!-- 人物原型：desc + 语气提示 -->
          <template v-else-if="col.key === 'archetype'">
            <div class="gacha-name">{{ dn(card.archetype.name) || '—' }}</div>
            <div v-if="card.archetype.name && dn(card.archetype.name) !== card.archetype.name" class="gacha-id">{{ card.archetype.name }}</div>
            <div class="gacha-desc">{{ card.archetype.desc || '—' }}</div>
            <div v-if="card.archetype.voiceHint" class="gacha-voice">语气：{{ card.archetype.voiceHint }}</div>
          </template>

          <!-- 世界规则：rule_packs 列表 -->
          <template v-else>
            <template v-if="card.rulePacks.length">
              <div v-for="r in card.rulePacks" :key="r.name" class="gacha-rule">
                <b>{{ dn(r.name) }}<span v-if="dn(r.name) !== r.name" class="gacha-id"> {{ r.name }}</span></b>
                <span>{{ r.desc || '—' }}</span>
              </div>
            </template>
            <div v-else class="gacha-desc">未抽到世界规则包</div>
          </template>
        </div>

        <button class="btn-line" :disabled="busy" :aria-label="`换一张${col.label}，其余栏保持不变`"
                @click="redrawCol(col.key)">换这张</button>
        <button v-if="col.key === 'genre'" class="btn-line gacha-synth-btn" :disabled="busy"
                aria-label="让 AI 自由发挥，现场合成新题材（其余栏不变）" @click="synthGenre">
          <AppIcon name="zap" :size="12" /> 让 AI 自由发挥
        </button>
      </div>
    </div>

    <div v-else-if="drawing" class="gacha-loading" role="status">
      <span class="gc-spin" aria-hidden="true"></span>抽卡中…
    </div>
    <div v-else class="gacha-loading">
      <span>还没抽到开局卡。</span>
      <button class="btn-line" aria-label="重新抽一张开局卡" @click="redrawAll">重新抽卡</button>
    </div>

    <footer class="gacha-foot">
      <button class="btn-line" :disabled="busy || !card" aria-label="换一批，四栏全部重抽"
              @click="redrawAll">换一批</button>
      <button ref="startBtn" class="btn-main" :disabled="busy || !card"
              aria-label="确认开工，按当前配置开始创作" @click="requestConfirm">
        {{ confirmBusy ? '开工中…' : '确认开工' }}
      </button>
    </footer>

    <!-- 开工方式弹层（P10.4；alertdialog + 焦点管理 + Esc 取消）：
         作为新项目（项目名输入，默认 {genre}-{MMdd}）/ 当前项目继续（有章节时明示重置后果） -->
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
          <input v-model.trim="projectName" class="gd-input" :disabled="confirmBusy" maxlength="64"
                 aria-label="新项目名，仅限字母、数字、连字符和下划线" :placeholder="suggestedName">
          <div class="gd-hint" :class="{ bad: projectName && !nameValid }">
            将作为新项目目录名：仅限字母/数字/-/_，且以字母或数字开头
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
