<script setup>
// Showrunner 决策卡视图：10 步 control loop 的产物
import { computed, ref } from 'vue'

const props = defineProps({ chapters: { type: Array, default: () => [] } })

const trackNames = { A: '主线·玉佩案侦破', B: '刘伯弧·管家秘密', C: '展昭弧·侠与法', D: '单元剧·案中案', E: '主题·律法与情' }
const sternbergNames = { suspense: '悬念', curiosity: '好奇', surprise: '惊奇' }
const phaseNames = {
  equilibrium: '平衡', disruption: '扰动', recognition: '识别',
  repair: '修复', new_equilibrium: '新平衡',
}
const hookStyles = { 明扣: 'bg-amber-950 text-amber-300 border-amber-800', 暗扣: 'bg-indigo-950 text-indigo-300 border-indigo-800', 留扣: 'bg-sky-950 text-sky-300 border-sky-800', 拴马扣: 'bg-red-950 text-red-300 border-red-800' }

const cards = computed(() =>
  props.chapters.filter(c => !c.rolled_back)
    .map(c => ({ chapter: c.chapter, title: c.title, ...c.decision_card }))
    .sort((a, b) => b.chapter - a.chapter))

const selected = ref(0)
const card = computed(() => cards.value[selected.value] || null)

const trackColor = (t, card) => {
  if (card.advance.includes(t)) return 'bg-emerald-500'
  if (card.seed.includes(t)) return 'bg-sky-500'
  if (card.mid_touch.includes(t)) return 'bg-amber-500'
  return 'bg-zinc-700'
}
const trackAction = (t, card) => {
  if (card.advance.includes(t)) return '推进'
  if (card.seed.includes(t)) return '种子'
  if (card.mid_touch.includes(t)) return '触碰'
  return '休眠'
}
</script>

<template>
  <div v-if="!card" class="text-center py-20 text-zinc-500">
    <p>还没有决策卡。生成第一章后，Showrunner 会产出每章的 10 步决策卡。</p>
  </div>

  <div v-else class="space-y-5">
    <!-- 章节切换 -->
    <div class="flex gap-2 flex-wrap">
      <button v-for="(c, i) in cards" :key="c.chapter" @click="selected = i"
              class="px-3 py-1.5 rounded-lg text-sm border transition"
              :class="i === selected ? 'border-amber-500 text-amber-300 bg-amber-950/30' : 'border-zinc-800 text-zinc-400 hover:border-zinc-600'">
        第{{ c.chapter }}章《{{ c.title }}》
      </button>
    </div>

    <div class="grid lg:grid-cols-2 gap-5">
      <!-- 轨道调度 -->
      <section class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
        <h3 class="text-sm font-semibold text-zinc-200 mb-1">五轨道调度 <span class="text-[10px] text-zinc-600 font-normal">Step 1-2</span></h3>
        <p class="text-[11px] text-zinc-600 mb-4">推进 / 种子 / 触碰 / 休眠 — 多线叙事的状态外部化</p>
        <div class="space-y-2.5">
          <div v-for="(name, t) in trackNames" :key="t" class="flex items-center gap-3">
            <span class="w-6 h-6 rounded flex items-center justify-center text-xs font-bold text-zinc-950" :class="trackColor(t, card)">{{ t }}</span>
            <span class="text-sm text-zinc-300 flex-1">{{ name }}</span>
            <span class="text-[11px] text-zinc-500">{{ trackAction(t, card) }}</span>
            <span v-if="card.sternberg_distribution[t]" class="text-[10px] px-1.5 py-0.5 rounded bg-violet-950 text-violet-300">
              {{ sternbergNames[card.sternberg_distribution[t]] }}
            </span>
          </div>
        </div>
        <div class="mt-4 pt-3 border-t border-zinc-800 text-[11px] text-zinc-500">
          Sternberg 三主因错峰（Step 3）：同集不同模式，逐集轮换
        </div>
      </section>

      <!-- 集末钩子 + 情感弧 -->
      <section class="space-y-5">
        <div class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
          <h3 class="text-sm font-semibold text-zinc-200 mb-3">集末钩子 <span class="text-[10px] text-zinc-600 font-normal">Step 9 · 评书扣子</span></h3>
          <div class="flex items-center gap-3">
            <span class="text-lg px-3 py-1 rounded-lg border font-bold" :class="hookStyles[card.ending_hook.style] || 'bg-zinc-800 text-zinc-200 border-zinc-700'">
              {{ card.ending_hook.style }}
            </span>
            <div class="text-xs text-zinc-500">
              <div>{{ card.ending_hook.desc }}</div>
              <div class="mt-0.5">周期约束：{{ card.ending_hook.periodic }}</div>
            </div>
          </div>
        </div>
        <div class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
          <h3 class="text-sm font-semibold text-zinc-200 mb-2">情感弧目标 <span class="text-[10px] text-zinc-600 font-normal">Step 5 · Reagan 6弧</span></h3>
          <span class="text-base text-emerald-300 font-mono">{{ card.target_arc }}</span>
          <div class="mt-2 text-[11px] text-zinc-500">主题 touch（Step 10）：{{ card.theme_touch ? '✓ 已触碰北极星轨道' : '✗ 未触碰' }}</div>
        </div>
      </section>
    </div>

    <!-- beat 规划 -->
    <section class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
      <h3 class="text-sm font-semibold text-zinc-200 mb-1">Beat 规划 <span class="text-[10px] text-zinc-600 font-normal">Step 4 · Todorov 5态 × Genre</span></h3>
      <div class="mt-3 grid md:grid-cols-4 gap-3">
        <div v-for="b in card.beats" :key="b.beat_id" class="rounded-lg bg-zinc-950 border border-zinc-800 p-3">
          <div class="flex items-center justify-between">
            <span class="text-[10px] font-mono text-zinc-600">{{ b.beat_id }}</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">{{ phaseNames[b.phase] }}</span>
          </div>
          <div class="mt-2 text-xs text-zinc-300">{{ b.track }} · {{ b.track_name }}</div>
          <div class="mt-2 flex items-center gap-1.5">
            <div class="flex-1 h-1 rounded-full bg-zinc-800 overflow-hidden">
              <div class="h-full bg-gradient-to-r from-amber-500 to-red-500" :style="{ width: (b.tension * 100) + '%' }"></div>
            </div>
            <span class="text-[10px] font-mono text-zinc-600">{{ b.tension }}</span>
          </div>
        </div>
      </div>
    </section>

    <div class="grid lg:grid-cols-2 gap-5">
      <!-- Snyder 覆盖 -->
      <section class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
        <h3 class="text-sm font-semibold text-zinc-200 mb-1">Snyder 15拍覆盖 <span class="text-[10px] text-zinc-600 font-normal">Step 6</span></h3>
        <div class="mt-3 grid grid-cols-3 gap-1.5">
          <span v-for="(ok, name) in card.snyder_coverage" :key="name"
                class="text-[11px] px-2 py-1 rounded text-center"
                :class="ok ? 'bg-emerald-950/60 text-emerald-300' : 'bg-zinc-800/60 text-zinc-500'">
            {{ ok ? '✓' : '·' }} {{ name }}
          </span>
        </div>
      </section>

      <!-- 伏笔到期 + McKee gap -->
      <section class="space-y-5">
        <div class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
          <h3 class="text-sm font-semibold text-zinc-200 mb-2">到期伏笔 <span class="text-[10px] text-zinc-600 font-normal">Step 2 · CFPG 查询</span></h3>
          <div v-if="card.active_payoffs.length" class="space-y-1.5">
            <div v-for="p in card.active_payoffs" :key="p.foreshadow_id" class="text-xs text-zinc-300">
              <span class="font-mono text-violet-300">{{ p.foreshadow_id }}</span> {{ p.content }} → <span class="text-zinc-500">{{ p.payoff }}</span>
            </div>
          </div>
          <p v-else class="text-xs text-zinc-600">本章无到期伏笔</p>
        </div>
        <div class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
          <h3 class="text-sm font-semibold text-zinc-200 mb-2">McKee Gap <span class="text-[10px] text-zinc-600 font-normal">Step 7 · 预期违反</span></h3>
          <div class="space-y-1.5">
            <div v-for="(g, i) in card.gaps" :key="i" class="text-xs text-zinc-400">◇ {{ g }}</div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
