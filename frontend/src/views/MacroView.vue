<script setup>
/* 规划图视图：随时查阅当前项目的宏观叙事计划（六大组件）
   使用 MacroDashboard 组件展示蓝图/幕结构/分集/弧光/伏笔/节奏
   P23.6: 导出故事圣经按钮——调 LLM 把全部设定融合成结构化提示词 */
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/api'
import { useToast } from '../composables/useToast'
import MacroDashboard from '../components/MacroDashboard.vue'

const props = defineProps({ project: { type: Object, default: null }, config: { type: Object, default: null } })
const emit = defineEmits(['refresh', 'navigate'])

const { toast, toastError } = useToast()
const plan = ref(null)
const loading = ref(false)
const exporting = ref(false)
const bibleText = ref('')
const showBible = ref(false)

/* 当前集数（用于高亮）—— 从 project.chapters 推断 */
const currentEpisode = computed(() => {
  const chs = props.project?.chapters
  if (!chs || !Array.isArray(chs) || !chs.length) return null
  const valid = chs.filter(c => !c.rolled_back)
  if (valid.length) return valid[valid.length - 1].number
  return chs[chs.length - 1].number
})

async function loadPlan() {
  loading.value = true
  try {
    plan.value = await api.macroPlanGet()
  } catch (e) {
    if (e.message && e.message.includes('404')) {
      plan.value = null
    } else {
      toast('加载宏观计划失败：' + (e.message || e))
    }
  }
  loading.value = false
}

async function exportBible() {
  exporting.value = true
  bibleText.value = ''
  showBible.value = true
  try {
    const res = await api.exportBible()
    bibleText.value = res.bible || '(空)'
    toast('故事圣经已生成')
  } catch (e) {
    toastError('导出失败：' + (e.message || e))
    showBible.value = false
  }
  exporting.value = false
}

function copyBible() {
  navigator.clipboard.writeText(bibleText.value).then(
    () => toast('已复制到剪贴板'),
    () => toast('复制失败，请手动选择文本复制')
  )
}

onMounted(loadPlan)
</script>

<template>
  <div class="macro-view">
    <!-- 标题栏 + 导出按钮 -->
    <div v-if="plan && !loading" class="macro-toolbar">
      <h2 class="macro-title">规划图</h2>
      <button class="btn-line" :disabled="exporting" data-testid="macro-export-bible"
              @click="exportBible">
        {{ exporting ? '生成中…' : '导出故事圣经' }}
      </button>
    </div>

    <div v-if="loading" class="macro-loading">加载中…</div>

    <div v-else-if="!plan" class="macro-empty">
      <p>当前项目还没有宏观计划。</p>
      <button class="btn-main" data-testid="macro-empty-gacha" @click="emit('navigate', 'gacha')">前往开局向导生成</button>
    </div>

    <MacroDashboard v-else :plan="plan" :current-episode="currentEpisode" />

    <!-- 故事圣经弹窗 -->
    <div v-if="showBible" class="bible-overlay" @click.self="showBible = false">
      <div class="bible-modal">
        <div class="bible-head">
          <span class="bible-title">故事圣经</span>
          <div class="bible-actions">
            <button v-if="bibleText" class="btn-line" @click="copyBible">复制</button>
            <button class="btn-line" @click="showBible = false">关闭</button>
          </div>
        </div>
        <div class="bible-body">
          <div v-if="exporting" class="bible-loading">LLM 生成中，请稍候…</div>
          <pre v-else class="bible-text">{{ bibleText }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.macro-view { max-width: 1000px; margin: 0 auto; padding: 20px 24px 60px; }
.macro-loading, .macro-empty { text-align: center; padding: 60px 20px; color: var(--faint, #888); }
.macro-empty p { margin-bottom: 16px; }
.macro-toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.macro-title { font: 700 18px var(--serif); color: var(--ink); margin: 0; }

.bible-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 200;
  display: flex; align-items: center; justify-content: center; }
.bible-modal { background: var(--s1); border-radius: 10px; max-width: 800px; width: 90vw;
  max-height: 80vh; display: flex; flex-direction: column; }
.bible-head { display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-bottom: 1px solid var(--line); }
.bible-title { font: 700 15px var(--serif); color: var(--ink); }
.bible-actions { display: flex; gap: 8px; }
.bible-body { flex: 1; overflow-y: auto; padding: 16px; }
.bible-loading { text-align: center; color: var(--faint); padding: 40px; }
.bible-text { white-space: pre-wrap; word-wrap: break-word; font-size: 13px;
  line-height: 1.8; color: var(--ink); margin: 0; font-family: var(--serif); }
</style>
