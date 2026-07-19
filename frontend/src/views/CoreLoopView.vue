<script setup>
// 核心循环视图：生成 → 7步硬约束检查 → 修正，逐章前后对比
import { computed, ref } from 'vue'
import MarkedText from '../components/MarkedText.vue'

const props = defineProps({ chapters: { type: Array, default: () => [] } })
const expanded = ref({})

const sorted = computed(() => [...props.chapters].sort((a, b) => b.chapter - a.chapter))
const active = computed(() => sorted.value.filter(c => !c.rolled_back))

const stats = computed(() => {
  const chs = active.value
  const totalViolations = chs.reduce((s, c) => s + c.draft.violation_count, 0)
  const fixed = chs.filter(c => c.correction?.recheck_passed).length
  const byType = {}
  for (const c of chs)
    for (const v of c.draft.violations)
      byType[v.check] = (byType[v.check] || 0) + 1
  return { chapters: chs.length, totalViolations, fixed, byType }
})

function toggle(ch) {
  expanded.value[ch] = !expanded.value[ch]
}
function failedChecks(ev) {
  return ev.checks.filter(c => !c.passed)
}
</script>

<template>
  <div class="space-y-5">
    <!-- 统计条 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <div class="rounded-xl bg-zinc-900 border border-zinc-800 p-4">
        <div class="text-2xl font-bold text-zinc-100">{{ stats.chapters }}</div>
        <div class="text-xs text-zinc-500 mt-1">已生成章节</div>
      </div>
      <div class="rounded-xl bg-zinc-900 border border-zinc-800 p-4">
        <div class="text-2xl font-bold text-red-400">{{ stats.totalViolations }}</div>
        <div class="text-xs text-zinc-500 mt-1">硬约束抓到的违规</div>
      </div>
      <div class="rounded-xl bg-zinc-900 border border-zinc-800 p-4">
        <div class="text-2xl font-bold text-emerald-400">{{ stats.fixed }}</div>
        <div class="text-xs text-zinc-500 mt-1">修正后复验通过</div>
      </div>
      <div class="rounded-xl bg-zinc-900 border border-zinc-800 p-4">
        <div class="flex flex-wrap gap-1.5 pt-1">
          <span v-for="(n, t) in stats.byType" :key="t"
                class="text-[10px] px-2 py-1 rounded bg-zinc-800 text-zinc-300">{{ t }} ×{{ n }}</span>
          <span v-if="!Object.keys(stats.byType).length" class="text-xs text-zinc-600">暂无违规</span>
        </div>
        <div class="text-xs text-zinc-500 mt-1.5">违规类型分布</div>
      </div>
    </div>

    <div v-if="!sorted.length" class="text-center py-20 text-zinc-500">
      <p class="text-lg mb-2">还没有章节</p>
      <p class="text-sm">点击右上角「生成下一章」，观看核心循环运转：LLM 生成初稿 → 7步硬约束检查 → 修正回路 → 提交事件</p>
    </div>

    <!-- 章节卡片 -->
    <div v-for="ch in sorted" :key="ch.chapter + ch.timestamp"
         class="rounded-xl border overflow-hidden"
         :class="ch.rolled_back ? 'border-zinc-800 opacity-45' : 'border-zinc-800 bg-zinc-900/50'">
      <!-- 卡片头 -->
      <button @click="toggle(ch.chapter)" class="w-full px-5 py-3.5 flex items-center gap-3 text-left hover:bg-zinc-900/80 transition">
        <span class="text-amber-400 font-bold">第{{ ch.chapter }}章</span>
        <span class="text-zinc-200 font-medium">{{ ch.title }}</span>
        <span v-if="ch.rolled_back" class="text-[10px] px-2 py-0.5 rounded bg-zinc-800 text-zinc-500">已回滚</span>
        <span v-if="ch.llm_mode === 'mock'" class="text-[10px] px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-900">剧本演示</span>
        <span v-else class="text-[10px] px-2 py-0.5 rounded bg-teal-950 text-teal-300 border border-teal-900">真实生成</span>
        <span v-if="ch.draft.violation_count" class="text-[10px] px-2 py-0.5 rounded bg-red-950 text-red-300 border border-red-900">
          {{ ch.draft.violation_count }} 处违规 → 已修正
        </span>
        <span v-else class="text-[10px] px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-900">一次通过</span>
        <span class="ml-auto text-xs text-zinc-600 font-mono">{{ ch.duration_ms }}ms · tick {{ ch.tick_range[0] }}-{{ ch.tick_range[1] }}</span>
        <span class="text-zinc-600 text-xs">{{ expanded[ch.chapter] ? '收起 ▲' : '展开 ▼' }}</span>
      </button>

      <div v-if="expanded[ch.chapter]" class="px-5 pb-5 space-y-4">
        <!-- 违规诊断 -->
        <div v-for="(v, i) in ch.draft.violations" :key="i"
             class="rounded-lg bg-red-950/30 border border-red-900/60 px-4 py-3">
          <div class="text-sm text-red-300 font-medium">⚠ {{ v.check }}</div>
          <div class="text-xs text-red-200/80 mt-1">{{ v.event }} — {{ v.reason }}</div>
        </div>

        <div class="grid lg:grid-cols-2 gap-4">
          <!-- 初稿 -->
          <div class="rounded-lg border border-zinc-800 bg-zinc-950 p-4">
            <div class="flex items-center gap-2 mb-3">
              <span class="text-xs font-semibold text-red-400 tracking-wide">初稿（LLM 生成）</span>
              <span class="text-[10px] text-zinc-600">生成通道 · 不含 WorldState 秘密</span>
            </div>
            <p class="story-text text-zinc-300 whitespace-pre-wrap"><MarkedText :text="ch.draft.text" /></p>
          </div>

          <!-- 修正稿 -->
          <div v-if="ch.correction" class="rounded-lg border border-emerald-900/50 bg-zinc-950 p-4">
            <div class="flex items-center gap-2 mb-3">
              <span class="text-xs font-semibold text-emerald-400 tracking-wide">修正稿</span>
              <span class="text-[10px] text-zinc-600">修正通道 · WorldState + 违规报告为基准</span>
              <span v-if="ch.correction.recheck_passed" class="ml-auto text-[10px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-300">复验 ✓</span>
            </div>
            <p class="story-text text-zinc-300 whitespace-pre-wrap"><MarkedText :text="ch.correction.text" /></p>
            <div class="mt-3 pt-3 border-t border-zinc-800 text-xs text-emerald-200/70">
              修正说明：{{ ch.correction.note }}
            </div>
          </div>

          <!-- 无违规时：最终稿即初稿 -->
          <div v-else class="rounded-lg border border-emerald-900/50 bg-zinc-950 p-4 flex flex-col">
            <div class="text-xs font-semibold text-emerald-400 tracking-wide mb-3">最终稿</div>
            <p class="text-sm text-zinc-500">7 步硬约束全部通过，无需修正，初稿直接提交事件库。</p>
          </div>
        </div>

        <!-- 7步验证明细 -->
        <div class="rounded-lg border border-zinc-800 overflow-hidden">
          <div class="px-4 py-2 bg-zinc-900 text-xs font-semibold text-zinc-400 tracking-wide">
            7 步硬约束验证（{{ ch.draft.events.length }} 个候选事件 × 7 步）
          </div>
          <div class="divide-y divide-zinc-800/60">
            <div v-for="(ev, i) in ch.draft.events" :key="i" class="px-4 py-2.5">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-[10px] font-mono text-zinc-600 w-14">{{ ev.event_type }}</span>
                <span class="text-sm text-zinc-300">{{ ev.event_summary }}</span>
                <span class="ml-auto"></span>
                <template v-for="c in ev.checks" :key="c.name">
                  <span v-if="c.passed" class="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800/80 text-zinc-500" :title="c.label">
                    {{ c.name }} ✓
                  </span>
                  <span v-else class="text-[10px] px-1.5 py-0.5 rounded bg-red-950 text-red-300 border border-red-800" :title="c.reason">
                    {{ c.name }} ✗
                  </span>
                </template>
              </div>
              <div v-for="c in failedChecks(ev)" :key="c.name" class="mt-1.5 text-xs text-red-300/90 pl-16">
                └ {{ c.label }}：{{ c.reason }}
              </div>
            </div>
          </div>
        </div>

        <!-- 伏笔更新 -->
        <div v-if="ch.foreshadow_updates.planted.length || ch.foreshadow_updates.payed_off.length"
             class="flex gap-2 flex-wrap text-xs">
          <span v-for="f in ch.foreshadow_updates.planted" :key="f.foreshadow_id"
                class="px-2 py-1 rounded bg-sky-950 text-sky-300 border border-sky-900">
            种下 {{ f.foreshadow_id }}：{{ f.content }}
          </span>
          <span v-for="f in ch.foreshadow_updates.payed_off" :key="f.foreshadow_id"
                class="px-2 py-1 rounded bg-violet-950 text-violet-300 border border-violet-900">
            回收 {{ f.foreshadow_id }}：{{ f.payoff }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
