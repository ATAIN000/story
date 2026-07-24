<script setup>
// 时间线（P6.9）：轨道地铁图 · 竖向版（P23 改：章=行下延，轨道=列）。
// 数据源：project（adapter toTimelineVM）—— 轨道=最新决策卡 trackNames；
// 事件=all_events 按 chapter 聚合，agent→track 哈希分散（最小实现）；
// 伏笔弧=foreshadows 的 plantedChapter→paidAtChapter（未回收指「未来」行），右侧边沟。
// 主题切换订阅 THEME_EVENT 重绘。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { toTimelineVM } from '../api/adapters'
import { THEME_EVENT } from '../composables/useTheme'
import EmptyState from '../components/EmptyState.vue'

const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})

const vm = computed(() => toTimelineVM(props.project))

/* ---- 竖向几何：章=行（y 下延），轨道=列（x） ---- */
const PAD_L = 64         // 左侧章标签预留宽
const PAD_R = 130        // 右侧伏笔弧边沟
const PAD_T = 56         // 顶部轨道标签预留高
const PAD_B = 30
const COL_W = 190        // 每轨道列宽
const ROW_H = 96         // 每章行高
const NODE_W = COL_W - 24
const NODE_H = 24

const chapterRows = computed(() => {
  const n = Math.max((vm.value.chapterCount ?? 0) + 1, 1)   /* +1 行容纳开放弧 */
  return Array.from({ length: n }, (_, i) => ({
    chapter: i + 1,
    isFuture: i >= (vm.value.chapterCount ?? 0),
  }))
})

const width = computed(() => PAD_L + vm.value.tracks.length * COL_W + PAD_R)
const height = computed(() => PAD_T + chapterRows.value.length * ROW_H + PAD_B)

function trackX(i) { return PAD_L + i * COL_W + COL_W / 2 }
function rowY(i) { return PAD_T + i * ROW_H + ROW_H / 2 }

/* 同轨道同章事件竖向叠放 */
const placedEvents = computed(() => {
  const groups = new Map()   // `chapter|track` → events[]
  for (const e of vm.value.events) {
    const k = `${e.chapter}|${e.track}`
    if (!groups.has(k)) groups.set(k, [])
    groups.get(k).push(e)
  }
  const placed = []
  for (const [key, evs] of groups) {
    const [chRaw, tr] = key.split('|')
    const ch = Number(chRaw)
    /* chapter=0（未归章）事件归入第一行（chapter=1）并打 untagged 标，避免被静默丢弃 */
    const chForRow = ch > 0 ? ch : 1
    const ri = chapterRows.value.findIndex(c => c.chapter === chForRow)
    const ti = vm.value.tracks.findIndex(t => t.id === tr)
    if (ri < 0 || ti < 0) continue
    evs.forEach((e, i) => {
      const offset = (i - (evs.length - 1) / 2) * (NODE_H + 6)
      placed.push({
        ...e,
        x: trackX(ti),
        y: rowY(ri) + offset - NODE_H / 2,
        idx: i,
        untagged: ch <= 0,
      }
    )})
  }
  return placed
})

/* A 轨主时间线连接曲线（竖向贝塞尔：上一章节点底边 → 下一章节点顶边） */
const aTrackIdx = computed(() => vm.value.tracks.findIndex(t => t.id === 'A'))
const aLineSegments = computed(() => {
  if (aTrackIdx.value < 0) return []
  const aEvents = placedEvents.value
    .filter(e => e.track === 'A')
    .sort((a, b) => a.chapter - b.chapter)
  const segs = []
  for (let i = 1; i < aEvents.length; i++) {
    const a = aEvents[i - 1], b = aEvents[i]
    const y1 = a.y + NODE_H, y2 = b.y
    segs.push({
      d: `M ${a.x} ${y1} C ${a.x} ${y1 + 40}, ${b.x} ${y2 - 40}, ${b.x} ${y2}`,
    })
  }
  return segs
})

/* 伏笔弧：右侧边沟，plantedChapter→paidAtChapter（开放则→chapterCount+1 行） */
const arcs = computed(() => vm.value.arcs.map(f => {
  const fromRi = chapterRows.value.findIndex(c => c.chapter === f.from)
  const toRi = chapterRows.value.findIndex(c => c.chapter === f.to)
  const y1 = fromRi >= 0 ? rowY(fromRi) : 0
  const y2 = toRi >= 0 ? rowY(toRi) : y1
  const x = width.value - PAD_R + 26
  const mid = (y1 + y2) / 2
  return {
    ...f,
    d: `M ${x} ${y1} Q ${x + 34} ${mid}, ${x} ${y2}`,
    labelX: x + 42,
    labelY: mid + 4,
    color: f.paidOff ? 'var(--violet)' : 'var(--sky)',
    label: `◆${f.id}${f.paidOff ? '（已收）' : '（回收中）'}`,
  }
}))

/* 主题切换重绘订阅 */
const themeTick = ref(0)
function onTheme() { themeTick.value++ }
onMounted(() => window.addEventListener(THEME_EVENT, onTheme))
onUnmounted(() => window.removeEventListener(THEME_EVENT, onTheme))
</script>

<template>
  <div v-if="vm.empty" class="tl-empty">
    <EmptyState icon="clock" title="时间线暂无事件"
      desc="生成首章后，事件流会按章聚合到竖向轨道图上；伏笔弧会在右侧边沟画出 planted→payoff 的轨迹。" />
  </div>

  <div v-else class="tl-zone" :key="themeTick">
    <div class="tl-head">
      <h2>时间线</h2>
      <span>{{ vm.tracks.length }} 条轨道 · {{ vm.events.length }} 个事件 · {{ vm.arcs.length }} 条伏笔弧</span>
    </div>

    <div class="tl-scroll">
      <svg class="tl-svg" :viewBox="`0 0 ${width} ${height}`" :width="width" :height="height"
           preserveAspectRatio="xMinYMin meet" role="img" aria-label="时间线地铁图（竖向）">
        <!-- 轨道列参考线 -->
        <g class="tl-cols">
          <line v-for="(t, i) in vm.tracks" :key="`cl${t.id}`"
                :x1="PAD_L + i * COL_W" :y1="PAD_T - 6"
                :x2="PAD_L + i * COL_W" :y2="height - PAD_B"
                stroke="var(--line)" stroke-opacity="0.6" />
        </g>

        <!-- 章行底纹 + 左侧章标签 -->
        <g class="tl-rows">
          <rect v-for="(c, i) in chapterRows" :key="`bg${i}`"
                :x="PAD_L - 8" :y="PAD_T + i * ROW_H + 6"
                :width="vm.tracks.length * COL_W + 16" :height="ROW_H - 12" rx="10"
                :fill="c.isFuture ? 'var(--primary)' : 'transparent'"
                :fill-opacity="c.isFuture ? 0.05 : 0"
                :stroke="c.isFuture ? 'var(--primary)' : 'var(--line)'"
                :stroke-dasharray="c.isFuture ? '6 4' : 'none'"
                :stroke-opacity="c.isFuture ? 0.4 : 0.5" />
          <text v-for="(c, i) in chapterRows" :key="`ct${i}`"
                :x="PAD_L - 16" :y="rowY(i) + 4" text-anchor="end" font-size="13"
                :font-weight="700" :fill="c.isFuture ? 'var(--primary)' : 'var(--faint)'"
                style="font-family: var(--serif)">第{{ c.chapter }}章</text>
        </g>

        <!-- 轨道标签（顶部） -->
        <g class="tl-tracks">
          <text v-for="(t, i) in vm.tracks" :key="`tr${t.id}`"
                :x="trackX(i)" :y="PAD_T - 16" text-anchor="middle"
                font-size="12" font-weight="700" fill="var(--faint)">
            {{ t.id }} · {{ t.name.length > 12 ? t.name.slice(0, 12) + '…' : t.name }}
          </text>
        </g>

        <!-- A 轨主时间线连接 -->
        <g class="tl-a-line">
          <path v-for="(s, i) in aLineSegments" :key="`al${i}`" :d="s.d"
                fill="none" stroke="var(--sky)" stroke-width="1.2" opacity="0.5" />
        </g>

        <!-- 伏笔弧（右侧边沟） -->
        <g class="tl-arcs">
          <path v-for="(a, i) in arcs" :key="`a${i}`" :d="a.d" fill="none"
                :stroke="a.color" :stroke-width="a.paidOff ? 2 : 1.5"
                :stroke-dasharray="a.paidOff ? 'none' : '5 4'" opacity="0.85" />
          <text v-for="(a, i) in arcs" :key="`at${i}`"
                :x="a.labelX" :y="a.labelY" text-anchor="start"
                font-size="10" font-weight="700" :fill="a.color">{{ a.label }}</text>
        </g>

        <!-- 事件节点 -->
        <g class="tl-events">
          <g v-for="(e, i) in placedEvents" :key="`e${i}`" class="g-node"
             :data-testid="`timeline-event-${e.chapter}-${e.track}`">
            <rect :x="e.x - NODE_W / 2" :y="e.y" :width="NODE_W" :height="NODE_H" rx="6"
                  fill="var(--s2)" stroke="var(--line2)" />
            <text :x="e.x" :y="e.y + 16" text-anchor="middle" font-size="11" fill="var(--ink)">
              {{ e.agent || '·' }}：{{ e.action?.slice(0, 14) || e.eventType }}
            </text>
            <title>第{{ e.chapter }}章 · {{ e.agent }}：{{ e.action }}{{ e.untagged ? '（未归章）' : '' }}</title>
          </g>
        </g>
      </svg>
    </div>

    <div class="tl-legend">
      <span class="lg-item"><span class="lg-dot" style="background: var(--sky)"></span>回收中</span>
      <span class="lg-item"><span class="lg-dot" style="background: var(--violet)"></span>已收</span>
      <span class="lg-note">竖向阅读：章沿行下延 · 右侧边沟为伏笔弧 · 虚线行为「未来」</span>
    </div>
  </div>
</template>

<style scoped>
.tl-empty { height: 100%; display: flex; align-items: flex-start; justify-content: center; overflow-y: auto; padding-top: 40px; }

.tl-zone { height: 100%; overflow: auto; padding: 26px 28px 60px; }
.tl-head { display: flex; align-items: baseline; gap: 14px; margin-bottom: 16px; }
.tl-head h2 { font: 700 22px var(--serif); color: var(--ink); }
.tl-head span { font-size: 11.5px; color: var(--faint); }

.tl-scroll { padding-bottom: 8px; }
.tl-svg { display: block; }
.g-node { cursor: default; }

.tl-legend { margin-top: 16px; padding-top: 12px; border-top: 1px dashed var(--line);
  display: flex; gap: 16px; align-items: baseline; flex-wrap: wrap; }
.lg-item { font-size: 11.5px; color: var(--ink2); display: inline-flex; align-items: center; gap: 6px; }
.lg-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.lg-note { font-size: 11px; color: var(--faint); }
</style>
