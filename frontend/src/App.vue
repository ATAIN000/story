<script setup>
// StoryOS App 骨架 —— nav（9 项）+ topbar + 状态机视图切换（不引 vue-router）。
// 布局/样式迁移自 story.html :41-73 / :432-464；视图占位 stub 由 P6.6-P6.10 填充。
import { ref, computed, onMounted } from 'vue'
import { api } from './api/api'
import { toProjectVM, toConfigVM, displayName } from './api/adapters'
import { useTheme } from './composables/useTheme'
import { useToast } from './composables/useToast'
import { useGeneration } from './composables/useGeneration'
import { useFontSize } from './composables/useFontSize'
import AppIcon from './components/AppIcon.vue'
import { NAV_ICONS } from './components/icons'
import MacroView from './views/MacroView.vue'
import ToastHost from './components/ToastHost.vue'
import ProjectsView from './views/ProjectsView.vue'
import WriteView from './views/WriteView.vue'
import GachaView from './views/GachaView.vue'
import DecisionCardView from './views/DecisionCardView.vue'
import CharsView from './views/CharsView.vue'
import WorldView from './views/WorldView.vue'
import TimelineView from './views/TimelineView.vue'
import ThreadsView from './views/ThreadsView.vue'
import PluginsView from './views/PluginsView.vue'
import SettingsView from './views/SettingsView.vue'

const { theme, toggleTheme } = useTheme()
const { toast, toastError } = useToast()
const { generating, stage } = useGeneration()
const { fsSize, incFont, decFont } = useFontSize()

// A−/A＋（story.html :459-461）：只接手稿 .para 字号，提示当前档
function bumpFont(dir) {
  dir > 0 ? incFont() : decFont()
  toast(`正文字号 ${fsSize.value}px`)
}

const VIEWS = { projects: ProjectsView, write: WriteView, gacha: GachaView, macro: MacroView, card: DecisionCardView, chars: CharsView, world: WorldView, timeline: TimelineView, threads: ThreadsView, plugins: PluginsView, settings: SettingsView }
const NAV = [
  // P10.4 多项目：项目页置于最顶部独立段（含开局入口）
  { sec: '项目', items: [{ id: 'projects', name: '项目' }] },
  // 创作段：写作台 / 规划图（宏观计划随时查阅）/ 决策卡
  { sec: '创作', items: [
    { id: 'write', name: '写作台' },
    { id: 'macro', name: '规划图' },
    { id: 'card', name: '决策卡' },
  ] },
  { sec: '故事资产', items: [
    { id: 'chars', name: '人物' },
    { id: 'world', name: '世界观' },
    { id: 'timeline', name: '时间线' },
    { id: 'threads', name: '伏笔账' },
  ] },
  { sec: '系统', items: [
    { id: 'plugins', name: '插件' },
    { id: 'settings', name: '设置' },
  ] },
]

const view = ref('write')
const project = ref(null)   // toProjectVM 后的视图模型
const config = ref(null)    // toConfigVM 后的视图模型
const pluginCount = computed(() => config.value?.pluginCount ?? 0)

const activeView = computed(() => VIEWS[view.value] || WriteView)
const meta = computed(() => project.value?.meta || {})

/* P9.1：顶栏/导航脚注的题材·文化名走 displayName（中文 title，回落 id） */
const dn = (id) => displayName(config.value, id)

// nav 计数徽标：只展示后端可核实的真实计数（8.2-#7/8 不用内存态冒充）
function navCount(id) {
  if (!project.value) return ''
  if (id === 'write') return meta.value.chapterCount ? `第${meta.value.chapterCount}章` : ''
  if (id === 'card') return meta.value.chapterCount ? `×${meta.value.chapterCount}` : ''
  if (id === 'chars') return String(project.value.world?.minds.length || '')
  if (id === 'threads') return String(project.value.world?.foreshadows.length || '')
  if (id === 'plugins') return String(pluginCount.value || '')
  return ''
}

/* 全站刷新：config + project 一起重拉（P10.4 切换项目后题材/显示名可能变化，
   开局 confirm 新题材入库同理——单拉 project 会拿旧 displayNames 渲染） */
async function refresh() {
  try {
    config.value = toConfigVM(await api.config())
  } catch (e) {
    toastError(`后端未连接：${e.message}`)
  }
  try {
    project.value = toProjectVM(await api.project())
  } catch (e) {
    toastError(`加载项目失败：${e.message}`)
  }
}

/* 视图内跳转（P8.6：写作台空态 CTA → 开局页；开局页确认开工 → 写作台） */
function gotoView(id) {
  if (VIEWS[id]) view.value = id
}

onMounted(refresh)
</script>

<template>
  <div class="app">
    <!-- 左侧导航（story.html :432-448） -->
    <nav class="nav" aria-label="主导航">
      <div class="nav-logo">
        <div class="lg" aria-hidden="true">書</div>
        <div><div class="t1">StoryOS</div><div class="t2">故事工作台</div></div>
      </div>
      <template v-for="group in NAV" :key="group.sec">
        <div class="nav-sec">{{ group.sec }}</div>
        <button v-for="item in group.items" :key="item.id" class="nav-item"
                :class="{ active: view === item.id }"
                :aria-current="view === item.id ? 'page' : undefined"
                :aria-label="item.name"
                :data-testid="`nav-${item.id}`"
                @click="view = item.id">
          <span class="ic"><AppIcon :name="NAV_ICONS[item.id]" :size="16" /></span>
          {{ item.name }}<span class="cnt">{{ navCount(item.id) }}</span>
        </button>
      </template>
      <div class="nav-foot">
        {{ dn(meta.genre) || '—' }} × {{ dn(meta.culture) || '—' }} × {{ meta.language || 'zh' }}<br>
        editorial · 双主题
      </div>
    </nav>

    <div class="main">
      <!-- 顶栏（story.html :450-464） -->
      <header class="topbar">
        <span class="proj">《{{ meta.name || '加载中' }}》</span>
        <span class="crumb">{{ dn(meta.genre) }} × {{ dn(meta.culture) }}</span>
        <span v-if="meta.llmMode" class="tb-badge llm" :class="{ mock: meta.llmMode === 'mock' }">
          {{ meta.llmMode === 'mock' ? 'MOCK 剧本' : meta.llmModel }}
        </span>
        <div class="right">
          <span class="tb-badge">tick {{ meta.headTick ?? 0 }} · 第 {{ meta.chapterCount ?? 0 }} 章</span>
          <span v-if="generating" class="stage-pill" role="status">
            <span class="dot" aria-hidden="true"></span>{{ stage || '生成中' }}
          </span>
          <div class="theme-ctl">
            <button @click="bumpFont(-1)" title="缩小正文字号" aria-label="缩小正文字号" data-testid="font-decrease">A−</button>
            <button @click="bumpFont(1)" title="放大正文字号" aria-label="放大正文字号" data-testid="font-increase">A＋</button>
            <button @click="toggleTheme" :aria-label="theme === 'night' ? '切换到日间模式' : '切换到夜读模式'"
                    data-testid="theme-toggle"
                    :title="theme === 'night' ? '切换到日间模式' : '切换到夜读模式'">
              <AppIcon :name="theme === 'night' ? 'sun' : 'moon'" :size="13" />
              {{ theme === 'night' ? '日间' : '夜读' }}
            </button>
          </div>
        </div>
      </header>

      <!-- 视图区（状态机切换；组件只消费 adapter 视图模型；navigate = 视图内跳转而发起，如空态 CTA / 抽卡确认开工） -->
      <main class="view" role="main" :aria-label="`视图：${view}`">
        <component :is="activeView" :project="project" :config="config" @refresh="refresh" @navigate="gotoView" />
      </main>
    </div>

    <ToastHost />
  </div>
</template>
