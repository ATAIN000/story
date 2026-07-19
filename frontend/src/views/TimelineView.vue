<script setup>
// 事件时间线 + 伏笔池：事件溯源可视化（append-only 日志 / snapshot / rollback）
import { computed } from 'vue'

const props = defineProps({
  events: { type: Array, default: () => [] },
  foreshadows: { type: Array, default: () => [] },
  snapshots: { type: Array, default: () => [] },
  headTick: { type: Number, default: 0 },
})
const emit = defineEmits(['rollback'])

const typeMeta = {
  character_action: { label: '角色行动', color: 'bg-sky-400', text: 'text-sky-300' },
  world_change:     { label: '世界变化', color: 'bg-zinc-400', text: 'text-zinc-300' },
  narrative_beat:   { label: '叙事节拍', color: 'bg-amber-400', text: 'text-amber-300' },
  dialogue:         { label: '对话',     color: 'bg-emerald-400', text: 'text-emerald-300' },
  scene_transition: { label: '场景转换', color: 'bg-teal-400', text: 'text-teal-300' },
  author_intervention: { label: '作者介入', color: 'bg-pink-400', text: 'text-pink-300' },
  branch_fork:      { label: '分支',     color: 'bg-violet-400', text: 'text-violet-300' },
}

const sorted = computed(() =>
  [...props.events].sort((a, b) => a.world_tick - b.world_tick || (a.timeline || 0) - (b.timeline || 0)))
const snapByTick = computed(() => {
  const m = {}
  for (const s of props.snapshots) m[s.world_tick] = s.snapshot_id
  return m
})
const inactiveCount = computed(() => props.events.filter(e => !e.active).length)

function eventSummary(e) {
  const p = e.payload || {}
  if (p.summary) return p.summary
  if (e.event_type === 'world_change') return `${p.field} → ${p.new_value}`
  if (e.event_type === 'narrative_beat') return p.scene ? `节拍：${p.scene}` : `节拍（第${p.chapter || '?'}章）`
  return e.event_type
}

function payloadDigest(e) {
  const p = e.payload || {}
  const bits = []
  if (p.agent) bits.push(p.agent)
  if (p.action) bits.push(p.action)
  if (p.story_time) bits.push(p.story_time)
  if (p.requires_knowing?.length) bits.push(`需知: ${p.requires_knowing.join(',')}`)
  if (p.tension != null) bits.push(`tension ${p.tension}`)
  return bits.join(' · ')
}
</script>

<template>
  <div class="grid lg:grid-cols-[1fr_340px] gap-5 items-start">
    <!-- 事件时间线 -->
    <section class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
      <div class="flex items-center gap-3 mb-1">
        <h3 class="text-sm font-semibold text-zinc-200">事件溯源日志</h3>
        <span class="text-[11px] text-zinc-500 font-mono">append-only · {{ events.length }} 事件</span>
        <span v-if="inactiveCount" class="text-[11px] px-2 py-0.5 rounded bg-zinc-800 text-zinc-400">{{ inactiveCount }} 条已回滚</span>
      </div>
      <p class="text-[11px] text-zinc-600 mb-4">
        状态 = 事件流的 fold。事件只追加、永不修改；回滚只是移动 head 指针 — 被回滚的事件保留为「另一条时间线」。
      </p>

      <div v-if="!sorted.length" class="text-sm text-zinc-600 py-10 text-center">
        还没有事件。生成第一章后，这里会出现完整的事件流。
      </div>

      <div class="relative pl-6">
        <div class="absolute left-[7px] top-1 bottom-1 w-px bg-zinc-800"></div>
        <div v-for="e in sorted" :key="e.event_id" class="relative mb-3">
          <div class="absolute -left-6 top-1.5 w-3.5 h-3.5 rounded-full border-2 border-zinc-950"
               :class="[typeMeta[e.event_type]?.color || 'bg-zinc-500', e.active ? '' : 'opacity-30']"></div>
          <div class="rounded-lg border px-3.5 py-2.5 transition"
               :class="e.active ? 'border-zinc-800 bg-zinc-950' : 'border-zinc-800/50 bg-zinc-950/40 opacity-40'">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-[10px] font-mono text-zinc-500">#{{ e.world_tick }}</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800" :class="typeMeta[e.event_type]?.text">
                {{ typeMeta[e.event_type]?.label || e.event_type }}
              </span>
              <span class="text-sm text-zinc-200" :class="{ 'line-through': !e.active }">{{ eventSummary(e) }}</span>
              <span v-if="!e.active" class="text-[10px] text-zinc-600">已回滚</span>

              <!-- snapshot 标记 + 回滚按钮 -->
              <span v-if="snapByTick[e.world_tick]"
                    class="ml-auto flex items-center gap-1.5">
                <span class="text-[10px] px-1.5 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-900 font-mono">
                  ◈ snapshot {{ snapByTick[e.world_tick] }}
                </span>
                <button v-if="e.world_tick !== headTick"
                        @click="emit('rollback', e.world_tick)"
                        class="text-[10px] px-2 py-0.5 rounded border border-zinc-700 text-zinc-400 hover:border-amber-500 hover:text-amber-300 transition">
                  回滚到此
                </button>
                <span v-else class="text-[10px] text-zinc-600">HEAD</span>
              </span>
            </div>
            <div v-if="payloadDigest(e)" class="mt-1 text-[11px] text-zinc-500 font-mono">{{ payloadDigest(e) }}</div>
          </div>
        </div>
      </div>
    </section>

    <!-- 伏笔池 -->
    <aside class="rounded-xl bg-zinc-900 border border-zinc-800 p-5 lg:sticky lg:top-24">
      <h3 class="text-sm font-semibold text-zinc-200 mb-1">伏笔池 <span class="text-[10px] text-zinc-600 font-normal">CFPG (F,T,P)</span></h3>
      <p class="text-[11px] text-zinc-600 mb-4">伏笔债显式外化：种下 → 待触发 → 回收，全程可审计</p>

      <div v-if="!foreshadows.length" class="text-sm text-zinc-600 py-6 text-center">伏笔池为空</div>

      <div class="space-y-3">
        <div v-for="fs in foreshadows" :key="fs.foreshadow_id"
             class="rounded-lg border p-3.5"
             :class="fs.payed_off ? 'border-violet-900/60 bg-violet-950/20' : 'border-sky-900/60 bg-sky-950/20'">
          <div class="flex items-center gap-2">
            <span class="text-xs font-mono font-bold" :class="fs.payed_off ? 'text-violet-300' : 'text-sky-300'">
              {{ fs.foreshadow_id }}
            </span>
            <span v-if="fs.payed_off" class="text-[10px] px-1.5 py-0.5 rounded bg-violet-950 text-violet-300">已回收 · 第{{ fs.payed_at_chapter }}章</span>
            <span v-else class="text-[10px] px-1.5 py-0.5 rounded bg-sky-950 text-sky-300">待回收</span>
            <span v-if="fs.required" class="text-[10px] px-1.5 py-0.5 rounded bg-red-950 text-red-300">必收</span>
            <span class="ml-auto text-[10px] text-zinc-600">种于第{{ fs.planted_chapter }}章</span>
          </div>
          <div class="mt-2 space-y-1 text-[12px]">
            <div><span class="text-zinc-500">F </span><span class="text-zinc-200">{{ fs.content }}</span></div>
            <div><span class="text-zinc-500">T </span><span class="text-zinc-400">{{ fs.trigger_condition }}</span></div>
            <div><span class="text-zinc-500">P </span><span :class="fs.payed_off ? 'text-violet-200' : 'text-zinc-400'">{{ fs.payoff }}</span></div>
          </div>
        </div>
      </div>
    </aside>
  </div>
</template>
