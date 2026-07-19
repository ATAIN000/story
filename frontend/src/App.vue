<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from './api'
import CoreLoopView from './views/CoreLoopView.vue'
import WorldStateView from './views/WorldStateView.vue'
import TimelineView from './views/TimelineView.vue'
import DecisionCardView from './views/DecisionCardView.vue'

const project = ref(null)
const config = ref(null)
const tab = ref('core')
const loading = ref(false)
const error = ref('')

const tabs = [
  { id: 'core', name: '核心循环', desc: '生成→检查→修正' },
  { id: 'world', name: '世界状态', desc: '四层结构 + 角色心智' },
  { id: 'timeline', name: '事件时间线', desc: '事件溯源 + 伏笔池' },
  { id: 'card', name: '决策卡', desc: 'Showrunner 10步产物' },
]

async function refresh() {
  project.value = await api.project()
}

async function generate() {
  loading.value = true
  error.value = ''
  try {
    await api.generate()
    await refresh()
    tab.value = 'core'
  } catch (e) {
    error.value = e.message
    await refresh()
  } finally {
    loading.value = false
  }
}

async function reset() {
  if (!confirm('重置项目？所有章节与事件将清空。')) return
  loading.value = true
  error.value = ''
  try { await api.reset(); await refresh() } finally { loading.value = false }
}

async function onRollback(tick) {
  loading.value = true
  error.value = ''
  try { await api.rollback(tick); await refresh() }
  catch (e) { error.value = e.message }
  finally { loading.value = false }
}

const meta = computed(() => project.value?.meta || {})
const chapters = computed(() => project.value?.chapters || [])

onMounted(async () => {
  config.value = await api.config()
  await refresh()
})
</script>

<template>
  <div class="min-h-screen flex flex-col">
    <!-- 顶栏 -->
    <header class="border-b border-zinc-800 bg-zinc-900/60 backdrop-blur sticky top-0 z-10">
      <div class="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3 flex-wrap">
        <div class="flex items-baseline gap-2">
          <h1 class="text-lg font-bold text-amber-400 tracking-wide">故事引擎</h1>
          <span class="text-xs text-zinc-500 font-mono">STORY OS v0.1</span>
        </div>
        <span class="text-sm text-zinc-400">《{{ meta.project || '加载中' }}》</span>

        <div class="flex items-center gap-1.5 text-[11px] font-mono">
          <span class="px-2 py-0.5 rounded bg-zinc-800 text-sky-300">{{ meta.genre }}</span>
          <span class="text-zinc-600">×</span>
          <span class="px-2 py-0.5 rounded bg-zinc-800 text-violet-300">{{ meta.culture }}</span>
          <span class="text-zinc-600">×</span>
          <span class="px-2 py-0.5 rounded bg-zinc-800 text-emerald-300">{{ meta.language }}</span>
        </div>

        <span class="text-[11px] px-2 py-0.5 rounded font-mono"
              :class="meta.llm_mode === 'mock' ? 'bg-amber-950 text-amber-300 border border-amber-800' : 'bg-emerald-950 text-emerald-300 border border-emerald-800'">
          {{ meta.llm_mode === 'mock' ? 'MOCK LLM' : 'OPENAI ' + meta.llm_model }}
        </span>

        <div class="ml-auto flex items-center gap-3">
          <span class="text-xs text-zinc-500 font-mono">tick {{ meta.head_tick }} · 第 {{ meta.chapter_count }} 章</span>
          <button @click="generate" :disabled="loading"
                  class="px-4 py-1.5 rounded bg-amber-500 hover:bg-amber-400 text-zinc-950 text-sm font-semibold disabled:opacity-40 transition">
            {{ loading ? '运转中…' : '生成下一章' }}
          </button>
          <button @click="reset" :disabled="loading"
                  class="px-3 py-1.5 rounded border border-zinc-700 hover:border-red-500 hover:text-red-400 text-sm text-zinc-400 disabled:opacity-40 transition">
            重置
          </button>
        </div>
      </div>

      <!-- 标签导航 -->
      <nav class="max-w-7xl mx-auto px-4 flex gap-1">
        <button v-for="t in tabs" :key="t.id" @click="tab = t.id"
                class="px-4 py-2 text-sm rounded-t-lg transition border-b-2 -mb-px"
                :class="tab === t.id
                  ? 'text-amber-300 border-amber-400 bg-zinc-900'
                  : 'text-zinc-500 border-transparent hover:text-zinc-300'">
          {{ t.name }}<span class="ml-1.5 text-[10px] text-zinc-600">{{ t.desc }}</span>
        </button>
      </nav>
    </header>

    <!-- 错误提示 -->
    <div v-if="error" class="max-w-7xl mx-auto px-4 mt-3 w-full">
      <div class="px-4 py-2.5 rounded-lg bg-amber-950/50 border border-amber-800 text-amber-200 text-sm">
        {{ error }}
      </div>
    </div>

    <!-- 主视图 -->
    <main class="flex-1 max-w-7xl mx-auto px-4 py-5 w-full" v-if="project">
      <CoreLoopView v-if="tab === 'core'" :chapters="chapters" />
      <WorldStateView v-else-if="tab === 'world'" :world="project.world_state" />
      <TimelineView v-else-if="tab === 'timeline'"
                    :events="project.events" :foreshadows="project.world_state.foreshadows"
                    :snapshots="project.snapshots" :head-tick="meta.head_tick"
                    @rollback="onRollback" />
      <DecisionCardView v-else :chapters="chapters" />
    </main>

    <footer class="border-t border-zinc-900 py-3 text-center text-[11px] text-zinc-600">
      核心循环已经 20 章实测验证（7/7 伏笔守住） · 硬约束：Z3 SMT + Epistemic EC + Event Calculus ·
      修正回路 = 100% 价值来源（深度验证报告）
    </footer>
  </div>
</template>
