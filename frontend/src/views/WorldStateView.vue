<script setup>
// 世界状态视图：物理层 / 关系层 / 心智层 / 叙事层（四层结构）
import { computed } from 'vue'

const props = defineProps({
  world: { type: Object, required: true },
  // App.vue 传入 chapters：轨道名取最新有效章节决策卡的 track_names（最短真实路径，
  // 后端不把 genre 轨道名放进 world_state）；旧数据无该字段时退回 beats 的 track_name
  chapters: { type: Array, default: () => [] },
})

const physicalGroups = computed(() => {
  const groups = { at: [], alive: [], other: [] }
  for (const f of props.world.physical) {
    if (f.startsWith('at(')) groups.at.push(f)
    else if (f.startsWith('alive(')) groups.alive.push(f)
    else groups.other.push(f)
  }
  return groups
})

const affectColor = (v) => v >= 0.7 ? 'bg-red-400' : v >= 0.4 ? 'bg-amber-400' : 'bg-sky-400'
// 兼容 fallback：P3.10 前持久化的章节决策卡无 track_names，且早期数据 beats 也未必带
// track_name —— 此时退回旧硬编码 map（仅对齐 mystery 演示项目，新数据不会走到）
const FALLBACK_TRACK_NAMES = { A: '主线', B: '刘伯弧', C: '展昭弧', D: '单元剧', E: '主题' }
const trackNames = computed(() => {
  const cards = props.chapters.filter(c => !c.rolled_back && c.decision_card)
  for (let i = cards.length - 1; i >= 0; i--) {
    const dc = cards[i].decision_card
    if (dc.track_names && Object.keys(dc.track_names).length) return dc.track_names
  }
  for (let i = cards.length - 1; i >= 0; i--) {
    const beats = cards[i].decision_card.beats || []
    const names = {}
    for (const b of beats) if (b.track && b.track_name) names[b.track] = b.track_name
    if (Object.keys(names).length) return names
  }
  return FALLBACK_TRACK_NAMES
})
</script>

<template>
  <div class="space-y-5">
    <!-- 状态条 -->
    <div class="rounded-xl bg-zinc-900 border border-zinc-800 px-5 py-4 flex flex-wrap items-center gap-x-8 gap-y-2">
      <div><span class="text-xs text-zinc-500">世界 tick</span><div class="text-xl font-bold font-mono text-amber-400">{{ world.tick }}</div></div>
      <div><span class="text-xs text-zinc-500">故事时间</span><div class="text-sm text-zinc-200 mt-1">{{ world.narrative.last_story_time || '—' }}</div></div>
      <div><span class="text-xs text-zinc-500">当前场景</span><div class="text-sm text-zinc-200 mt-1">{{ world.narrative.current_scene || '—' }}</div></div>
      <div>
        <span class="text-xs text-zinc-500">张力</span>
        <div class="flex items-center gap-2 mt-1.5">
          <div class="w-32 h-2 rounded-full bg-zinc-800 overflow-hidden">
            <div class="h-full bg-gradient-to-r from-amber-500 to-red-500" :style="{ width: (world.narrative.tension * 100) + '%' }"></div>
          </div>
          <span class="text-sm font-mono text-zinc-300">{{ world.narrative.tension.toFixed(2) }}</span>
        </div>
      </div>
      <div><span class="text-xs text-zinc-500">幕 / 章</span><div class="text-sm text-zinc-200 mt-1">第 {{ world.narrative.act }} 幕 · 第 {{ world.narrative.chapter }} 章</div></div>
    </div>

    <div class="grid lg:grid-cols-2 gap-5">
      <!-- 物理层 -->
      <section class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
        <h3 class="text-sm font-semibold text-sky-300 mb-1">物理层 <span class="text-[10px] text-zinc-600 font-normal">Event Calculus fluents</span></h3>
        <p class="text-[11px] text-zinc-600 mb-3">后继状态公理自动维护：事件 fold 后位置/生死/持有物即时更新</p>
        <div class="space-y-3">
          <div>
            <div class="text-[11px] text-zinc-500 mb-1.5">位置 at()</div>
            <div class="flex flex-wrap gap-1.5">
              <span v-for="f in physicalGroups.at" :key="f" class="text-xs px-2 py-1 rounded bg-sky-950/60 text-sky-200 border border-sky-900/50 font-mono">{{ f }}</span>
            </div>
          </div>
          <div>
            <div class="text-[11px] text-zinc-500 mb-1.5">存活 alive()</div>
            <div class="flex flex-wrap gap-1.5">
              <span v-for="f in physicalGroups.alive" :key="f" class="text-xs px-2 py-1 rounded bg-zinc-800 text-zinc-300 font-mono">{{ f }}</span>
            </div>
          </div>
          <div v-if="physicalGroups.other.length">
            <div class="text-[11px] text-zinc-500 mb-1.5">其他</div>
            <div class="flex flex-wrap gap-1.5">
              <span v-for="f in physicalGroups.other" :key="f" class="text-xs px-2 py-1 rounded bg-zinc-800 text-zinc-400 font-mono">{{ f }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 关系层 -->
      <section class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
        <h3 class="text-sm font-semibold text-violet-300 mb-1">关系层 <span class="text-[10px] text-zinc-600 font-normal">CiF 数值化</span></h3>
        <p class="text-[11px] text-zinc-600 mb-3">角色间关系的类型与强度（Prom Week 式）</p>
        <div class="space-y-3">
          <div v-for="r in world.relationships" :key="r.pair" class="flex items-center gap-3">
            <span class="text-sm text-zinc-300 w-28 shrink-0">{{ r.pair.replace('|', ' ↔ ') }}</span>
            <span class="text-[11px] px-1.5 py-0.5 rounded bg-violet-950 text-violet-300 shrink-0">{{ r.type }}</span>
            <div class="flex-1 h-1.5 rounded-full bg-zinc-800 overflow-hidden">
              <div class="h-full bg-violet-400" :style="{ width: (r.intensity * 100) + '%' }"></div>
            </div>
            <span class="text-xs font-mono text-zinc-500 w-8">{{ r.intensity.toFixed(2) }}</span>
          </div>
          <p v-if="!world.relationships.length" class="text-sm text-zinc-600">暂无关系数据</p>
        </div>
      </section>
    </div>

    <!-- 心智层 -->
    <section class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
      <h3 class="text-sm font-semibold text-amber-300 mb-1">心智层 <span class="text-[10px] text-zinc-600 font-normal">Epistemic EC + IPOCL</span></h3>
      <p class="text-[11px] text-zinc-600 mb-4">每个角色知道什么 / 不知道什么 / 想要什么 — 认知硬约束的判定基准</p>
      <div class="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        <div v-for="(m, cid) in world.minds" :key="cid"
             class="rounded-lg border border-zinc-800 bg-zinc-950 p-4 space-y-3">
          <div class="flex items-baseline gap-2">
            <span class="text-base font-bold text-zinc-100">{{ cid }}</span>
            <span class="text-[11px] text-zinc-500">{{ m.role }}</span>
          </div>
          <div v-if="m.knows.length">
            <div class="text-[10px] text-emerald-400 mb-1">知道 knows()</div>
            <div class="flex flex-wrap gap-1">
              <span v-for="f in m.knows" :key="f" class="text-[11px] px-1.5 py-0.5 rounded bg-emerald-950/70 text-emerald-200">{{ f }}</span>
            </div>
          </div>
          <div v-if="m.doesnt_know.length">
            <div class="text-[10px] text-red-400 mb-1">不知道（认知约束保护区）</div>
            <div class="flex flex-wrap gap-1">
              <span v-for="f in m.doesnt_know" :key="f" class="text-[11px] px-1.5 py-0.5 rounded bg-red-950/60 text-red-300/90">{{ f }}</span>
            </div>
          </div>
          <div v-if="m.secrets.length">
            <div class="text-[10px] text-violet-400 mb-1">持有秘密</div>
            <div class="flex flex-wrap gap-1">
              <span v-for="f in m.secrets" :key="f" class="text-[11px] px-1.5 py-0.5 rounded bg-violet-950/70 text-violet-200">{{ f }}</span>
            </div>
          </div>
          <div>
            <div class="text-[10px] text-sky-400 mb-1">活跃目标（IPOCL 承诺框架）</div>
            <div class="flex flex-wrap gap-1">
              <span v-for="g in m.goals" :key="g" class="text-[11px] px-1.5 py-0.5 rounded bg-sky-950/70 text-sky-200">{{ g }}</span>
            </div>
          </div>
          <div v-if="Object.keys(m.affect).length" class="space-y-1">
            <div class="text-[10px] text-zinc-500">情感</div>
            <div v-for="(v, k) in m.affect" :key="k" class="flex items-center gap-2">
              <span class="text-[11px] text-zinc-400 w-10">{{ k }}</span>
              <div class="flex-1 h-1 rounded-full bg-zinc-800 overflow-hidden">
                <div class="h-full" :class="affectColor(v)" :style="{ width: (v * 100) + '%' }"></div>
              </div>
              <span class="text-[10px] font-mono text-zinc-600">{{ v }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 叙事层 -->
    <section class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
      <h3 class="text-sm font-semibold text-emerald-300 mb-1">叙事层 <span class="text-[10px] text-zinc-600 font-normal">多轨道 + 因果 DAG</span></h3>
      <div class="grid lg:grid-cols-2 gap-5 mt-3">
        <div>
          <div class="text-[11px] text-zinc-500 mb-2">轨道进度（状态外部化 — 不靠 LLM 注意力记伏笔）</div>
          <div class="space-y-2">
            <div v-for="(p, t) in world.narrative.track_progress" :key="t" class="flex items-center gap-2">
              <span class="text-xs font-mono text-amber-400 w-4">{{ t }}</span>
              <span class="text-xs text-zinc-400 w-16">{{ trackNames[t] || t }}</span>
              <div class="flex-1 h-2 rounded-full bg-zinc-800 overflow-hidden">
                <div class="h-full bg-emerald-500" :style="{ width: (p * 100) + '%' }"></div>
              </div>
              <span class="text-xs font-mono text-zinc-500 w-10">{{ (p * 100).toFixed(0) }}%</span>
            </div>
          </div>
        </div>
        <div>
          <div class="text-[11px] text-zinc-500 mb-2">因果链（Pearl DAG — 动机可追溯）</div>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="(l, i) in world.narrative.causal_links" :key="i"
                  class="text-[11px] px-2 py-1 rounded bg-zinc-800 text-zinc-300 font-mono">{{ l }}</span>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
