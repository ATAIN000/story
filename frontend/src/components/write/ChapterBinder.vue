<script setup>
// 章节 binder（写作台左栏，story.html :468-472 + :630-638 + saga :1170-1184）
// 只消费 adapter VM：chapters = toChapterVM[]；saga 由 WriteView 从 project VM 组装。
// 章态口径：已归档（正常章）/ 审读中（前端本地 reviewing 集）/ 已回滚（后端 rolled_back，灰显）。
import { computed } from 'vue'

const props = defineProps({
  chapters: { type: Array, default: () => [] },
  activeNo: { type: Number, default: null },
  reviewing: { type: Set, default: () => new Set() },
  saga: { type: Object, default: () => ({ count: 0, tensions: null, tracks: [] }) },
})
defineEmits(['select'])

/* 高亮口径同 WriteView.resolveChapter：同号多记录（回滚后重生成）只高亮解析出的那条 */
const activeCh = computed(() => {
  if (props.activeNo == null) return null
  const alive = props.chapters.filter(c => c.no === props.activeNo && !c.rolledBack)
  return alive.at(-1) ?? props.chapters.find(c => c.no === props.activeNo) ?? null
})

function stateOf(c) {
  if (c.rolledBack) return { cls: '', text: '已回滚' }
  if (props.reviewing.has(c.no)) return { cls: 'ing', text: '审读中' }
  return { cls: 'ok', text: '已归档' }
}

// 张力 sparkline：最新章决策卡 beats tension（无则隐藏整个 svg，brief 口径）
const spark = computed(() => {
  const ts = props.saga.tensions
  if (!ts || !ts.length) return null
  const W = 160, H = 36, pad = 8
  const step = ts.length > 1 ? (W - pad * 2) / (ts.length - 1) : 0
  const pts = ts.map((t, i) => {
    const x = pad + i * step
    const y = 32 - Math.min(1, Math.max(0, t)) * 26
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  return { points: pts.join(' '), lastX: (pad + (ts.length - 1) * step).toFixed(1) }
})
</script>

<template>
  <aside class="binder">
    <div class="b-t">章节</div>
    <div v-if="!chapters.length" class="b-empty">还没有章节。<br>批准方案后，第一章会出现在这里。</div>
    <div v-for="(c, i) in chapters" :key="c.no + '@' + (c.timestamp || i)" class="ch-item"
         :class="{ active: c === activeCh, rb: c.rolledBack }"
         :data-testid="`chapter-item-${c.no}`"
         tabindex="0" role="button" :aria-pressed="c === activeCh"
         @click="$emit('select', c.no)"
         @keydown.enter.prevent="$emit('select', c.no)" @keydown.space.prevent="$emit('select', c.no)">
      <div class="c-no">第 {{ c.no }} 章</div>
      <div class="c-t">{{ c.title }}</div>
      <span class="c-st" :class="stateOf(c).cls">{{ stateOf(c).text }}</span>
    </div>

    <!-- 全书进度 saga（章数为真值；target_length 后端没有 → 只显示章数不写死） -->
    <div class="saga">
      <div class="saga-t">全书进度</div>
      <div class="saga-no">第 {{ saga.count }} <span>章</span></div>
      <svg v-if="spark" class="saga-spark" viewBox="0 0 160 36" preserveAspectRatio="none" aria-hidden="true">
        <polyline :points="spark.points" fill="none" stroke="var(--primary)" stroke-width="1.5" />
        <line :x1="spark.lastX" y1="4" :x2="spark.lastX" y2="32"
              stroke="var(--primary)" stroke-dasharray="2 3" opacity=".6" />
      </svg>
      <div v-if="spark" class="saga-tracks">张力曲线 · 最新章节拍 · 竖线=当前</div>
      <div v-if="saga.tracks.length" class="saga-tracks">
        {{ saga.tracks.map(t => `${t.name} ${t.pct}%`).join(' · ') }}
      </div>
    </div>
  </aside>
</template>
