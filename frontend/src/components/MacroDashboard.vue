<script setup>
/* 宏观叙事仪表盘 —— MacroView 与 GachaView 共用的富展示组件
   六大组件：蓝图 / 节奏曲线 / 分集梗概 / 角色弧光 / 伏笔 / 幕结构
   compact 模式用于 GachaView（小字、紧凑）；showRegen 显示单组件重摇按钮 */
import { computed } from 'vue'

const props = defineProps({
  plan: { type: Object, required: true },
  compact: { type: Boolean, default: false },
  currentEpisode: { type: Number, default: null },
  showRegen: { type: Boolean, default: false },
  regenerating: { type: String, default: '' },
})
const emit = defineEmits(['regenerate'])

/* ===== 枚举中文映射 ===== */
const BEAT_CN = {
  opening_image: '开场意象', setup: '建置', theme_stated: '点题', inciting_incident: '触发事件',
  debate: '犹豫辩论', break_into_two: '进入第二幕', b_story: '副线开启', fun_and_games: '施展才华',
  midpoint: '中点转折', bad_guys_close_in: '危机逼近', all_is_lost: '全线溃败',
  dark_night: '灵魂黑夜', break_into_three: '进入第三幕', finale: '终局对决', final_image: '终场意象',
  gathering_team: '集结队伍', executing_plan: '执行计划', high_tower_surprise: '高塔惊变',
  dig_down_deep: '深层挖掘', selection_of_natural_law: '天道选择', prologue: '序章',
  first_meeting: '初遇', misunderstanding: '误会', sweet_moments: '甜蜜日常',
  jealousy: '吃醋', reconciliation: '和解', confession: '告白', crisis: '危机',
  choice: '抉择', epilogue: '尾声',
}
const ARC_TYPE_CN = {
  positive_change: '正向成长弧', flat_positive: '平坦正面弧', negative_fall: '堕落弧',
  two_steps_forward: '两步前进弧', growth_arc: '成长弧', flat: '平坦弧',
}
const FS_STATUS_COL = { planned: '待埋', planted: '已埋·待回收', harvested: '已回收' }
const beatCn = n => BEAT_CN[n] || n
const arcTypeCn = t => ARC_TYPE_CN[t] || t || ''

/* ===== 各组件数据 ===== */
const bp = computed(() => props.plan?.blueprint || {})
const actStruct = computed(() => props.plan?.act_structure || {})
const acts = computed(() => actStruct.value.acts || [])
const episodes = computed(() => props.plan?.episode_outlines || [])
const characters = computed(() => props.plan?.arc_schedule?.characters || [])
const threads = computed(() => props.plan?.foreshadow_blueprint?.threads || [])
const tensionPts = computed(() => props.plan?.pacing_curve?.key_tension_points || [])
const totalEps = computed(() => bp.value.total_episodes || episodes.value.length || 0)

const hasBlueprint = computed(() => !!(bp.value.logline || bp.value.thematic_argument || bp.value.central_conflict))
const hasActs = computed(() => acts.value.length > 0)
const hasEpisodes = computed(() => episodes.value.length > 0)
const hasArcs = computed(() => characters.value.length > 0)
const hasForeshadow = computed(() => threads.value.length > 0)
const hasPacing = computed(() => tensionPts.value.length > 0)

/* ===== 分集按幕分组 ===== */
const episodesByAct = computed(() => {
  if (!acts.value.length) return []
  return acts.value.map(act => {
    const [s, e] = Array.isArray(act.episode_range) ? act.episode_range : [0, 0]
    const eps = episodes.value.filter(ep => ep.episode >= s && ep.episode <= e)
    return { act, episodes: eps }
  })
})
/* 不属于任何幕的集 */
const ungroupedEps = computed(() => {
  if (!acts.value.length) return episodes.value
  const inRange = ep => acts.value.some(a => {
    const [s, e] = Array.isArray(a.episode_range) ? a.episode_range : [0, 0]
    return ep.episode >= s && ep.episode <= e
  })
  return episodes.value.filter(ep => !inRange(ep))
})

/* ===== 伏笔看板分列 ===== */
const foreshadowCols = computed(() => {
  const cols = { planned: [], planted: [], harvested: [] }
  for (const f of threads.value) {
    const st = (f.status || '').toLowerCase()
    if (st.includes('回收') || st.includes('harvest')) cols.harvested.push(f)
    else if (st.includes('埋') || st.includes('plant')) cols.planted.push(f)
    else cols.planned.push(f)
  }
  return cols
})

/* ===== 节奏曲线 SVG 数据 ===== */
const pacingData = computed(() => {
  const pts = tensionPts.value
  if (!pts.length) return null
  const total = totalEps.value || Math.max(...pts.map(p => p.episode))
  const maxT = Math.max(...pts.map(p => p.tension || 0))
  const scale = maxT > 1.5 ? 100 : 1

  const W = 820, H = 200
  const padL = 56, padR = 30, padT = 28, padB = 44
  const plotW = W - padL - padR
  const plotH = H - padT - padB

  const points = pts.map(t => {
    const x = padL + ((t.episode - 1) / Math.max(total - 1, 1)) * plotW
    const tn = Math.min(1, Math.max(0, (t.tension || 0) / scale))
    const y = padT + (1 - tn) * plotH
    return { x, y, episode: t.episode, tension: tn, tensionRaw: t.tension, reason: t.reason || '', scale }
  })

  const linePath = points.map((p, i) =>
    `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)},${p.y.toFixed(1)}`
  ).join(' ')
  const baseY = padT + plotH
  const areaPath = points.length > 1
    ? `${linePath} L ${points[points.length - 1].x.toFixed(1)},${baseY} L ${points[0].x.toFixed(1)},${baseY} Z`
    : ''

  /* X 轴刻度：稀疏标注 */
  const xTicks = []
  const tickStep = total > 20 ? Math.ceil(total / 8) : total > 8 ? 2 : 1
  for (let i = 1; i <= total; i += tickStep) {
    xTicks.push({ ep: i, x: padL + ((i - 1) / Math.max(total - 1, 1)) * plotW })
  }
  if (xTicks[xTicks.length - 1]?.ep !== total) {
    xTicks.push({ ep: total, x: padL + plotW })
  }

  return { points, linePath, areaPath, W, H, padL, padR, padT, padB, plotW, plotH, baseY, total, scale, xTicks }
})

function tensionColor(tn) {
  if (tn > 0.75) return 'var(--danger)'
  if (tn > 0.45) return 'var(--primary)'
  return 'var(--accent)'
}
function tensionLabel(tn, raw) {
  const v = raw > 1.5 ? Math.round(raw) : Math.round(tn * 100)
  return v + '%'
}

/* ===== 角色配色 ===== */
const CHAR_VARS = ['--primary', '--accent', '--violet', '--sky', '--green', '--suspect']
function charVar(idx) { return `var(${CHAR_VARS[idx % CHAR_VARS.length]})` }

/* ===== 工具函数 ===== */
/** LLM 常把 plant_episodes 写成 "1,3" / 单数字 / 对象；统一成可展示文案 */
function formatPlantEps(v) {
  if (v == null || v === '') return '—'
  if (Array.isArray(v)) {
    const parts = v.map(x => (x == null || x === '' ? null : String(x))).filter(Boolean)
    return parts.length ? parts.join(', ') : '—'
  }
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  if (typeof v === 'string') {
    const s = v.trim()
    return s || '—'
  }
  if (typeof v === 'object') {
    const vals = Object.values(v).filter(x => x != null && x !== '')
    return vals.length ? vals.map(String).join(', ') : '—'
  }
  return String(v)
}
function fmtRange(r) {
  if (!r) return ''
  if (Array.isArray(r)) {
    if (r.length === 2 && r[0] === r[1]) return `第${r[0]}集`
    return `第${r[0]}–${r[1]}集`
  }
  return r
}
function fmtMsRange(r) {
  if (Array.isArray(r)) return r.join('–')
  return r || ''
}
function isCurrentEp(ep) {
  return props.currentEpisode != null && ep === props.currentEpisode
}
function regenLabel(comp) {
  return props.regenerating === comp ? '重摇中…' : '↻ 重摇'
}
function doRegen(comp) {
  if (props.regenerating) return
  emit('regenerate', comp)
}

/* 幕在时间轴上的比例宽度 */
function actFlexGrow(act) {
  const [s, e] = Array.isArray(act.episode_range) ? act.episode_range : [1, 1]
  return Math.max(1, e - s + 1)
}

/* 伏笔显著性阶梯迷你进度条 */
function ladderSteps(ladder) {
  if (!Array.isArray(ladder) || !ladder.length) return []
  const levelOrder = { vague: 0.2, subtle: 0.35, moderate: 0.55, action: 0.75, explicit: 1 }
  return ladder.map(s => ({
    ep: s?.ep,
    level: s?.level || '',
    form: s?.form || '',
    pct: levelOrder[String(s?.level || '').toLowerCase()] ?? 0.5,
  }))
}
</script>

<template>
  <div class="md" :class="{ 'md-compact': compact }">
    <!-- ====== 故事蓝图（Hero 卡） ====== -->
    <section v-if="hasBlueprint" class="md-section md-blueprint" id="md-sec-blueprint">
      <div class="md-sec-head">
        <h3 class="md-sec-title">故事蓝图</h3>
        <button v-if="showRegen" class="md-regen-btn" :disabled="!!regenerating"
                @click="doRegen('blueprint')">{{ regenLabel('blueprint') }}</button>
      </div>
      <div class="md-bp-body">
        <p v-if="bp.logline" class="md-logline">{{ bp.logline }}</p>

        <!-- 主题论证：谎言 → 真相 -->
        <div v-if="bp.thematic_argument" class="md-theme-arg">
          <div class="md-theme-box md-theme-lie">
            <span class="md-theme-tag">谎言</span>
            <p>{{ bp.thematic_argument.lie || '—' }}</p>
          </div>
          <div class="md-theme-arrow">→</div>
          <div class="md-theme-box md-theme-truth">
            <span class="md-theme-tag">真相</span>
            <p>{{ bp.thematic_argument.truth || '—' }}</p>
          </div>
        </div>

        <!-- 核心冲突 2×2 -->
        <div v-if="bp.central_conflict" class="md-conflict-grid">
          <div class="md-conf-cell md-conf-want">
            <span class="md-conf-label">主角想要</span>
            <p>{{ bp.central_conflict.protagonist_want || bp.central_conflict.want || '—' }}</p>
          </div>
          <div class="md-conf-cell md-conf-need">
            <span class="md-conf-label">主角需要</span>
            <p>{{ bp.central_conflict.protagonist_need || bp.central_conflict.need || '—' }}</p>
          </div>
          <div class="md-conf-cell md-conf-antag">
            <span class="md-conf-label">反派目标</span>
            <p>{{ bp.central_conflict.antagonist_want || '—' }}</p>
          </div>
          <div class="md-conf-cell md-conf-stakes">
            <span class="md-conf-label">赌注</span>
            <p>{{ bp.central_conflict.stakes || '—' }}</p>
          </div>
        </div>

        <!-- 元信息行 -->
        <div class="md-bp-meta">
          <span v-if="bp.story_type" class="md-chip">{{ bp.story_type }}</span>
          <span v-if="bp.target_pace" class="md-chip md-chip-pace">{{ bp.target_pace }}</span>
          <span v-if="totalEps" class="md-chip md-chip-eps">{{ totalEps }} 集</span>
          <span v-if="actStruct.template" class="md-chip md-chip-tmpl">{{ actStruct.template }}</span>
        </div>
      </div>
    </section>

    <!-- ====== 节奏曲线（全宽 SVG） ====== -->
    <section v-if="hasPacing && pacingData" class="md-section md-pacing">
      <div class="md-sec-head">
        <h3 class="md-sec-title">节奏曲线</h3>
        <span v-if="plan.pacing_curve?.curve_type" class="md-sec-sub">{{ plan.pacing_curve.curve_type }}</span>
        <button v-if="showRegen" class="md-regen-btn" :disabled="!!regenerating"
                @click="doRegen('pacing')">{{ regenLabel('pacing') }}</button>
      </div>
      <div class="md-pacing-body">
        <svg :viewBox="`0 0 ${pacingData.W} ${pacingData.H}`" class="md-pacing-svg" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient :id="'md-grad-' + (compact ? 'c' : 'f')" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="var(--danger)" stop-opacity="0.14" />
              <stop offset="45%" stop-color="var(--primary)" stop-opacity="0.07" />
              <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.02" />
            </linearGradient>
          </defs>
          <!-- 网格线 -->
          <g class="md-pacing-grid">
            <line :x1="pacingData.padL" :y1="pacingData.padT" :x2="pacingData.W - pacingData.padR" :y2="pacingData.padT" />
            <line :x1="pacingData.padL" :y1="pacingData.padT + pacingData.plotH * 0.5" :x2="pacingData.W - pacingData.padR" :y2="pacingData.padT + pacingData.plotH * 0.5" />
            <line :x1="pacingData.padL" :y1="pacingData.baseY" :x2="pacingData.W - pacingData.padR" :y2="pacingData.baseY" />
          </g>
          <!-- Y 轴标签 -->
          <text :x="pacingData.padL - 8" :y="pacingData.padT + 4" class="md-pacing-axis" text-anchor="end">高</text>
          <text :x="pacingData.padL - 8" :y="pacingData.padT + pacingData.plotH * 0.5 + 4" class="md-pacing-axis" text-anchor="end">中</text>
          <text :x="pacingData.padL - 8" :y="pacingData.baseY + 4" class="md-pacing-axis" text-anchor="end">低</text>
          <!-- 区域填充 -->
          <path v-if="pacingData.areaPath" :d="pacingData.areaPath" :fill="`url(#md-grad-${compact ? 'c' : 'f'})`" />
          <!-- 折线 -->
          <path :d="pacingData.linePath" fill="none" stroke="var(--line2)" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" />
          <!-- 数据点 -->
          <g v-for="(p, i) in pacingData.points" :key="i">
            <line :x1="p.x" :y1="p.y" :x2="p.x" :y2="pacingData.baseY" :stroke="tensionColor(p.tension)" stroke-width="1" stroke-opacity="0.25" stroke-dasharray="2,3" />
            <circle :cx="p.x" :cy="p.y" r="5" :fill="tensionColor(p.tension)" fill-opacity="0.18" />
            <circle :cx="p.x" :cy="p.y" r="3" :fill="tensionColor(p.tension)" />
            <text :x="p.x" :y="p.y - 10" class="md-pacing-val" text-anchor="middle">{{ tensionLabel(p.tension, p.tensionRaw) }}</text>
            <text :x="p.x" :y="pacingData.baseY + 16" class="md-pacing-ep" text-anchor="middle">第{{ p.episode }}集</text>
          </g>
          <!-- X 轴刻度 -->
          <g v-for="(t, i) in pacingData.xTicks" :key="'tick-' + i">
            <line :x1="t.x" :y1="pacingData.baseY" :x2="t.x" :y2="pacingData.baseY + 4" stroke="var(--line2)" stroke-width="1" />
            <text v-if="!pacingData.points.some(p => p.episode === t.ep)" :x="t.x" :y="pacingData.baseY + 16" class="md-pacing-axis" text-anchor="middle" opacity="0.5">{{ t.ep }}</text>
          </g>
        </svg>
        <!-- 关键张力点列表 -->
        <div class="md-pacing-reasons">
          <div v-for="(p, i) in pacingData.points" :key="'r-' + i" class="md-pacing-reason">
            <span class="md-pacing-reason-dot" :style="{ background: tensionColor(p.tension) }"></span>
            <span class="md-pacing-reason-ep">第{{ p.episode }}集 · {{ tensionLabel(p.tension, p.tensionRaw) }}</span>
            <span class="md-pacing-reason-txt">{{ p.reason }}</span>
          </div>
        </div>
        <p v-if="plan.pacing_curve?.genre_pace_profile" class="md-pacing-profile">{{ plan.pacing_curve.genre_pace_profile }}</p>
      </div>
    </section>

    <!-- ====== 分集梗概（按幕分组） ====== -->
    <section v-if="hasEpisodes" class="md-section md-episodes">
      <div class="md-sec-head">
        <h3 class="md-sec-title">分集梗概 <span class="md-sec-count">{{ episodes.length }}集</span></h3>
        <button v-if="showRegen" class="md-regen-btn" :disabled="!!regenerating"
                @click="doRegen('episodes')">{{ regenLabel('episodes') }}</button>
      </div>
      <div class="md-eps-body">
        <!-- 幕结构时间轴（点击跳转） -->
        <div v-if="hasActs" class="md-act-timeline">
          <button v-for="(a, i) in acts" :key="i" class="md-act-seg"
                  :style="{ flexGrow: actFlexGrow(a) }"
                  @click="$el.querySelector('#md-act-' + a.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })">
            <span class="md-act-seg-name">{{ a.name }}</span>
            <span class="md-act-seg-range">{{ fmtRange(a.episode_range) }}</span>
          </button>
        </div>

        <template v-for="group in episodesByAct" :key="group.act.id">
          <div class="md-act-group" :id="'md-act-' + group.act.id">
            <div class="md-act-group-head">
              <span class="md-act-group-name">{{ group.act.name }}</span>
              <span class="md-act-group-range">{{ fmtRange(group.act.episode_range) }}</span>
              <span v-if="group.act.function" class="md-act-group-fn">{{ group.act.function }}</span>
            </div>
            <!-- 幕内节拍 -->
            <div v-if="group.act.beats?.length" class="md-beats">
              <span v-for="(b, bi) in group.act.beats" :key="bi" class="md-beat-chip">
                <span class="md-beat-name">{{ beatCn(b.name) }}</span>
                <span class="md-beat-ep">第{{ b.ep }}集</span>
                <span v-if="b.desc" class="md-beat-desc">{{ b.desc }}</span>
              </span>
            </div>
            <!-- 幕内分集卡 -->
            <div class="md-ep-cards">
              <article v-for="e in group.episodes" :key="e.episode"
                       class="md-ep-card" :class="{ current: isCurrentEp(e.episode) }">
                <div class="md-ep-card-head">
                  <span class="md-ep-badge">第{{ e.episode }}集</span>
                  <span v-if="e.purpose" class="md-ep-purpose">{{ e.purpose }}</span>
                </div>
                <p class="md-ep-synopsis">{{ e.synopsis || '—' }}</p>
                <div v-if="e.key_events?.length" class="md-ep-events">
                  <span v-for="(ev, ei) in e.key_events" :key="ei" class="md-ep-event">{{ ev }}</span>
                </div>
                <div v-if="e.ends_with_hook" class="md-ep-hook">
                  <span class="md-ep-hook-tag">钩子</span>
                  <span>{{ e.ends_with_hook }}</span>
                </div>
              </article>
            </div>
          </div>
        </template>

        <!-- 不属于任何幕的分集 -->
        <div v-if="ungroupedEps.length" class="md-act-group">
          <div class="md-act-group-head">
            <span class="md-act-group-name">其他分集</span>
          </div>
          <div class="md-ep-cards">
            <article v-for="e in ungroupedEps" :key="e.episode"
                     class="md-ep-card" :class="{ current: isCurrentEp(e.episode) }">
              <div class="md-ep-card-head">
                <span class="md-ep-badge">第{{ e.episode }}集</span>
                <span v-if="e.purpose" class="md-ep-purpose">{{ e.purpose }}</span>
              </div>
              <p class="md-ep-synopsis">{{ e.synopsis || '—' }}</p>
              <div v-if="e.key_events?.length" class="md-ep-events">
                <span v-for="(ev, ei) in e.key_events" :key="ei" class="md-ep-event">{{ ev }}</span>
              </div>
              <div v-if="e.ends_with_hook" class="md-ep-hook">
                <span class="md-ep-hook-tag">钩子</span>
                <span>{{ e.ends_with_hook }}</span>
              </div>
            </article>
          </div>
        </div>
      </div>
    </section>

    <!-- ====== 角色弧光（竖向时间线） ====== -->
    <section v-if="hasArcs" class="md-section md-arcs">
      <div class="md-sec-head">
        <h3 class="md-sec-title">角色弧光</h3>
        <button v-if="showRegen" class="md-regen-btn" :disabled="!!regenerating"
                @click="doRegen('arcs')">{{ regenLabel('arcs') }}</button>
      </div>
      <div class="md-arcs-body">
        <div v-for="(c, ci) in characters" :key="c.name" class="md-arc-char"
             :style="{ '--char-color': charVar(ci) }">
          <div class="md-arc-char-head">
            <span class="md-arc-char-name">{{ c.name }}</span>
            <span class="md-arc-char-type">{{ arcTypeCn(c.archetype_arc) }}</span>
          </div>
          <div v-if="c.lie || c.truth" class="md-arc-lie-truth">
            <span v-if="c.lie" class="md-arc-lt"><b>谎言</b> {{ c.lie }}</span>
            <span v-if="c.truth" class="md-arc-lt"><b>真相</b> {{ c.truth }}</span>
          </div>
          <div class="md-arc-timeline">
            <div v-for="(m, mi) in (c.milestones || [])" :key="mi" class="md-arc-ms">
              <div class="md-arc-ms-dot"></div>
              <div class="md-arc-ms-body">
                <div class="md-arc-ms-top">
                  <span class="md-arc-ms-phase">{{ m.phase || '—' }}</span>
                  <span class="md-arc-ms-range">{{ fmtMsRange(m.episode_range) }}</span>
                </div>
                <p v-if="m.state" class="md-arc-ms-state">{{ m.state }}</p>
                <p v-if="m.event" class="md-arc-ms-event"><span class="md-arc-ms-label">触发</span>{{ m.event }}</p>
                <p v-if="m.behavior" class="md-arc-ms-behavior"><span class="md-arc-ms-label">表现</span>{{ m.behavior }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ====== 伏笔蓝图（看板） ====== -->
    <section v-if="hasForeshadow" class="md-section md-foreshadow">
      <div class="md-sec-head">
        <h3 class="md-sec-title">伏笔蓝图 <span class="md-sec-count">{{ threads.length }}条</span></h3>
        <button v-if="showRegen" class="md-regen-btn" :disabled="!!regenerating"
                @click="doRegen('foreshadow')">{{ regenLabel('foreshadow') }}</button>
      </div>
      <div class="md-fs-body">
        <div class="md-fs-col">
          <div class="md-fs-col-head">{{ FS_STATUS_COL.planned }}</div>
          <div v-for="f in foreshadowCols.planned" :key="f.id" class="md-fs-card">
            <div class="md-fs-card-top">
              <span class="md-fs-name">{{ f.name }}</span>
              <span v-if="f.type" class="md-fs-type">{{ f.type }}</span>
            </div>
            <div class="md-fs-flow">
              <span>埋 {{ formatPlantEps(f.plant_episodes) }}</span>
              <span class="md-fs-arrow">→</span>
              <span>收 第{{ f.harvest_episode || '?' }}集</span>
            </div>
            <div v-if="f.salience_ladder?.length" class="md-fs-ladder">
              <div v-for="(s, si) in ladderSteps(f.salience_ladder)" :key="si" class="md-fs-ladder-row">
                <span class="md-fs-ladder-ep">{{ s.ep }}</span>
                <div class="md-fs-ladder-bar"><div class="md-fs-ladder-fill" :style="{ width: s.pct * 100 + '%' }"></div></div>
                <span class="md-fs-ladder-level">{{ s.level }}</span>
              </div>
            </div>
          </div>
          <div v-if="!foreshadowCols.planned.length" class="md-fs-empty">—</div>
        </div>
        <div class="md-fs-col">
          <div class="md-fs-col-head">{{ FS_STATUS_COL.planted }}</div>
          <div v-for="f in foreshadowCols.planted" :key="f.id" class="md-fs-card">
            <div class="md-fs-card-top">
              <span class="md-fs-name">{{ f.name }}</span>
              <span v-if="f.type" class="md-fs-type">{{ f.type }}</span>
            </div>
            <div class="md-fs-flow">
              <span>埋 {{ formatPlantEps(f.plant_episodes) }}</span>
              <span class="md-fs-arrow">→</span>
              <span>收 第{{ f.harvest_episode || '?' }}集</span>
            </div>
          </div>
          <div v-if="!foreshadowCols.planted.length" class="md-fs-empty">—</div>
        </div>
        <div class="md-fs-col">
          <div class="md-fs-col-head">{{ FS_STATUS_COL.harvested }}</div>
          <div v-for="f in foreshadowCols.harvested" :key="f.id" class="md-fs-card md-fs-card-done">
            <div class="md-fs-card-top">
              <span class="md-fs-name">{{ f.name }}</span>
              <span v-if="f.type" class="md-fs-type">{{ f.type }}</span>
            </div>
            <div class="md-fs-flow">
              <span>埋 {{ formatPlantEps(f.plant_episodes) }}</span>
              <span class="md-fs-arrow">→</span>
              <span>收 第{{ f.harvest_episode || '?' }}集</span>
            </div>
          </div>
          <div v-if="!foreshadowCols.harvested.length" class="md-fs-empty">—</div>
        </div>
      </div>
    </section>
  </div>
</template>
