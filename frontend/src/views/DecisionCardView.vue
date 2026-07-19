<script setup>
// Showrunner 决策卡视图：10 步 control loop 的产物
// Step 顺序以 story_engine/showrunner/decision.py 头注为准（P3.3 后蓝图顺序）：
// 0 节奏量化 / 1 HTN 分解 / 2 轨道调度 / 3 CFPG 查询 / 4 Sternberg 错峰 /
// 5 分形 beat / 6 CONCOCT / 7 McKee gap / 8 Snyder 覆盖 / 9 池更新 / 10 主题 touch
import { computed, ref } from 'vue'

const props = defineProps({ chapters: { type: Array, default: () => [] } })

// 旧持久化章节（P3.10 前生成）decision_card 无 track_names 字段时的兼容 fallback；
// 新数据一律走 card.track_names（后端随 genre 插件填充）
const FALLBACK_TRACK_NAMES = { A: '主线·玉佩案侦破', B: '刘伯弧·管家秘密', C: '展昭弧·侠与法', D: '单元剧·案中案', E: '主题·律法与情' }
const sternbergNames = { suspense: '悬念', curiosity: '好奇', surprise: '惊奇' }
const phaseNames = {
  equilibrium: '平衡', disruption: '扰动', recognition: '识别',
  repair: '修复', new_equilibrium: '新平衡',
}
const hookStyles = { 明扣: 'bg-amber-950 text-amber-300 border-amber-800', 暗扣: 'bg-indigo-950 text-indigo-300 border-indigo-800', 留扣: 'bg-sky-950 text-sky-300 border-sky-800', 拴马扣: 'bg-red-950 text-red-300 border-red-800' }
const pacingLabels = {
  reversal_density: '反转密度', avg_reversal_magnitude: '平均反转幅度',
  pacing_consistency: '节奏一致性', cliffhanger_strength: '钩子强度',
}

const cards = computed(() =>
  props.chapters.filter(c => !c.rolled_back)
    .map(c => ({ chapter: c.chapter, title: c.title, ...c.decision_card }))
    .sort((a, b) => b.chapter - a.chapter))

const selected = ref(0)
const card = computed(() => cards.value[selected.value] || null)

// 轨道名：新数据用 card.track_names（键集即轨道集，romance 4 条 / mystery 5 条）；
// 缺失（旧数据）时退回硬编码 map，行为与旧版一致
const cardTrackNames = computed(() => {
  const tn = card.value?.track_names
  return (tn && Object.keys(tn).length) ? tn : FALLBACK_TRACK_NAMES
})

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
      <!-- 轨道调度（Step 2）+ Sternberg 错峰（Step 4） -->
      <section class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
        <h3 class="text-sm font-semibold text-zinc-200 mb-1">轨道调度 <span class="text-[10px] text-zinc-600 font-normal">Step 2</span></h3>
        <p class="text-[11px] text-zinc-600 mb-4">推进 / 种子 / 触碰 / 休眠 — 多线叙事的状态外部化</p>
        <div class="space-y-2.5">
          <div v-for="(name, t) in cardTrackNames" :key="t" class="flex items-center gap-3">
            <span class="w-6 h-6 rounded flex items-center justify-center text-xs font-bold text-zinc-950" :class="trackColor(t, card)">{{ t }}</span>
            <span class="text-sm text-zinc-300 flex-1">{{ name }}</span>
            <span class="text-[11px] text-zinc-500">{{ trackAction(t, card) }}</span>
            <span v-if="card.sternberg_distribution[t]" class="text-[10px] px-1.5 py-0.5 rounded bg-violet-950 text-violet-300">
              {{ sternbergNames[card.sternberg_distribution[t]] }}
            </span>
          </div>
        </div>
        <div class="mt-4 pt-3 border-t border-zinc-800 text-[11px] text-zinc-500">
          Sternberg 三主因错峰（Step 4）：同集不同模式，同轨道连续两集不同
        </div>
      </section>

      <!-- 集末钩子 + 情感弧（既有补充步骤，不在决策3的 10 步表内） -->
      <section class="space-y-5">
        <div class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
          <h3 class="text-sm font-semibold text-zinc-200 mb-3">集末钩子 <span class="text-[10px] text-zinc-600 font-normal">补充步骤 · 评书扣子</span></h3>
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
          <h3 class="text-sm font-semibold text-zinc-200 mb-2">情感弧目标 <span class="text-[10px] text-zinc-600 font-normal">补充步骤 · Reagan 6弧</span></h3>
          <span class="text-base text-emerald-300 font-mono">{{ card.target_arc }}</span>
          <div class="mt-2 text-[11px] text-zinc-500">主题 touch（Step 10）：{{ card.theme_touch ? '✓ 已触碰北极星轨道' : '✗ 未触碰' }}</div>
        </div>
      </section>
    </div>

    <!-- beat 规划（Step 5 分形 beat；primitives 为 Step 1 HTN 产物；具体度为 Step 6 CONCOCT） -->
    <section class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
      <h3 class="text-sm font-semibold text-zinc-200 mb-1">Beat 规划 <span class="text-[10px] text-zinc-600 font-normal">Step 5 · 分形 beat（幕级 × 章级）</span></h3>
      <div class="mt-3 grid md:grid-cols-4 gap-3">
        <div v-for="(b, i) in card.beats" :key="b.beat_id" class="rounded-lg bg-zinc-950 border border-zinc-800 p-3">
          <div class="flex items-center justify-between">
            <span class="text-[10px] font-mono text-zinc-600">{{ b.beat_id }}</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">{{ phaseNames[b.phase] || b.phase }}</span>
          </div>
          <div class="mt-2 text-xs text-zinc-300">{{ b.track }} · {{ b.track_name }}</div>
          <div v-if="b.macro_phase" class="mt-1 text-[10px] text-zinc-600">幕级：{{ phaseNames[b.macro_phase] || b.macro_phase }}</div>
          <div class="mt-2 flex items-center gap-1.5">
            <div class="flex-1 h-1 rounded-full bg-zinc-800 overflow-hidden">
              <div class="h-full bg-gradient-to-r from-amber-500 to-red-500" :style="{ width: (b.tension * 100) + '%' }"></div>
            </div>
            <span class="text-[10px] font-mono text-zinc-600">{{ b.tension }}</span>
          </div>
          <!-- Step 6 CONCOCT：每 beat 一个 0-1 具体度目标（旧数据无此字段则不显示） -->
          <div v-if="card.concreteness_curve?.[i] != null" class="mt-1.5 flex items-center gap-1.5">
            <span class="text-[10px] text-zinc-600">具体度</span>
            <div class="flex-1 h-1 rounded-full bg-zinc-800 overflow-hidden">
              <div class="h-full bg-sky-500" :style="{ width: (card.concreteness_curve[i] * 100) + '%' }"></div>
            </div>
            <span class="text-[10px] font-mono text-zinc-600">{{ card.concreteness_curve[i] }}</span>
          </div>
          <!-- Step 1 HTN：planner 原语序列（按 micro_phase 对齐） -->
          <div v-if="b.primitives?.length" class="mt-2 flex flex-wrap gap-1">
            <span v-for="p in b.primitives" :key="p" class="text-[9px] px-1 py-0.5 rounded bg-zinc-800/80 text-zinc-500 font-mono">{{ p }}</span>
          </div>
        </div>
      </div>
    </section>

    <div class="grid lg:grid-cols-2 gap-5">
      <!-- Snyder 覆盖（Step 8） -->
      <section class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
        <h3 class="text-sm font-semibold text-zinc-200 mb-1">Snyder 15拍覆盖 <span class="text-[10px] text-zinc-600 font-normal">Step 8</span></h3>
        <div class="mt-3 grid grid-cols-3 gap-1.5">
          <span v-for="(ok, name) in card.snyder_coverage" :key="name"
                class="text-[11px] px-2 py-1 rounded text-center"
                :class="ok ? 'bg-emerald-950/60 text-emerald-300' : 'bg-zinc-800/60 text-zinc-500'">
            {{ ok ? '✓' : '·' }} {{ name }}
          </span>
        </div>
      </section>

      <!-- 伏笔到期（Step 3）+ 池状态（Step 9）+ McKee gap（Step 7） -->
      <section class="space-y-5">
        <div class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
          <h3 class="text-sm font-semibold text-zinc-200 mb-2">到期伏笔 <span class="text-[10px] text-zinc-600 font-normal">Step 3 · CFPG 查询</span></h3>
          <div v-if="card.active_payoffs.length" class="space-y-1.5">
            <div v-for="p in card.active_payoffs" :key="p.foreshadow_id" class="text-xs text-zinc-300">
              <span class="font-mono text-violet-300">{{ p.foreshadow_id }}</span> {{ p.content }} → <span class="text-zinc-500">{{ p.payoff }}</span>
            </div>
          </div>
          <p v-else class="text-xs text-zinc-600">本章无到期伏笔</p>
        </div>
        <div v-if="card.pool_stats && Object.keys(card.pool_stats).length" class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
          <h3 class="text-sm font-semibold text-zinc-200 mb-2">伏笔池 <span class="text-[10px] text-zinc-600 font-normal">Step 9 · CFPG 池更新</span></h3>
          <div class="flex gap-5 text-center">
            <div><div class="text-lg font-bold font-mono text-emerald-300">{{ card.pool_stats.active }}</div><div class="text-[10px] text-zinc-500">未回收</div></div>
            <div><div class="text-lg font-bold font-mono text-red-300">{{ card.pool_stats.overdue }}</div><div class="text-[10px] text-zinc-500">老化债</div></div>
            <div><div class="text-lg font-bold font-mono text-sky-300">{{ card.pool_stats.queued }}</div><div class="text-[10px] text-zinc-500">排队</div></div>
          </div>
          <div v-if="card.queued_foreshadows?.length" class="mt-3 pt-2 border-t border-zinc-800 space-y-1">
            <div class="text-[10px] text-zinc-500">满池排队（待容量释放后种下）</div>
            <div v-for="(q, i) in card.queued_foreshadows" :key="i" class="text-xs text-zinc-400">
              <span class="font-mono text-sky-300">{{ q.track }}</span> {{ q.content }} → <span class="text-zinc-600">{{ q.payoff }}</span>
            </div>
          </div>
        </div>
        <div class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
          <h3 class="text-sm font-semibold text-zinc-200 mb-2">McKee Gap <span class="text-[10px] text-zinc-600 font-normal">Step 7 · 预期违反</span></h3>
          <div class="space-y-1.5">
            <div v-for="(g, i) in card.gaps" :key="i" class="text-xs text-zinc-400">◇ {{ g }}</div>
          </div>
        </div>
      </section>
    </div>

    <!-- P3.3+ 新增字段：pacing / plan_goals / creative_seeds（旧数据无字段则整区不渲染） -->
    <div v-if="card.pacing !== undefined || card.plan_goals?.length || card.creative_seeds?.length" class="grid lg:grid-cols-2 gap-5">
      <!-- 节奏量化（Step 0 · P3.4）：第一章 / 无事件源时为 null -->
      <section v-if="card.pacing !== undefined" class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
        <h3 class="text-sm font-semibold text-zinc-200 mb-1">节奏量化 <span class="text-[10px] text-zinc-600 font-normal">Step 0 · 上章实测 → 本章修正</span></h3>
        <template v-if="card.pacing">
          <p class="text-[11px] text-zinc-600 mb-3">基于第 {{ card.pacing.measured_episode }} 章事件流实测</p>
          <div class="grid grid-cols-2 gap-3">
            <div v-for="(label, key) in pacingLabels" :key="key" class="rounded-lg bg-zinc-950 border border-zinc-800 px-3 py-2">
              <div class="text-[10px] text-zinc-500">{{ label }}</div>
              <div class="text-base font-mono text-amber-300">{{ card.pacing.score?.[key]?.toFixed(2) ?? '—' }}</div>
            </div>
          </div>
        </template>
        <p v-else class="text-xs text-zinc-600 mt-2">首章无历史：上一章节奏数据不存在，本章不做 tension 修正</p>
      </section>

      <section class="space-y-5">
        <!-- HTN 规划目标轨迹（Step 1 · P3.6） -->
        <div v-if="card.plan_goals?.length" class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
          <h3 class="text-sm font-semibold text-zinc-200 mb-2">HTN 规划目标 <span class="text-[10px] text-zinc-600 font-normal">Step 1 · NarrativePlanner</span></h3>
          <div class="space-y-1">
            <div v-for="g in card.plan_goals" :key="g.id" class="text-xs text-zinc-400">
              <span class="text-zinc-500">{{ g.holder }}</span> · {{ g.desc }}
              <span class="text-[10px] text-zinc-600 font-mono">（{{ g.status }}）</span>
            </div>
          </div>
        </div>
        <!-- 跨域融合创意种子（P3.7，env 门控默认关，非空才显示） -->
        <div v-if="card.creative_seeds?.length" class="rounded-xl bg-zinc-900 border border-zinc-800 p-5">
          <h3 class="text-sm font-semibold text-zinc-200 mb-2">可选灵感 <span class="text-[10px] text-zinc-600 font-normal">P3.7 · ConceptualBlending</span></h3>
          <div v-for="(s, i) in card.creative_seeds" :key="i" class="space-y-1.5">
            <div class="text-[11px] text-violet-300">{{ (s.domains || []).join(' × ') }}</div>
            <p class="text-xs text-zinc-300">{{ s.emergent }}</p>
            <div class="text-[10px] text-zinc-500 font-mono">新颖度 {{ s.novelty?.toFixed(2) }} · 意外度 {{ s.surprise?.toFixed(2) }}</div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
