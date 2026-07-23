<script setup>
/* 规划图视图：随时查阅当前项目的宏观叙事计划（六大组件）
   使用 MacroDashboard 组件展示蓝图/幕结构/分集/弧光/伏笔/节奏 */
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/api'
import { useToast } from '../composables/useToast'
import MacroDashboard from '../components/MacroDashboard.vue'

const props = defineProps({ project: { type: Object, default: null }, config: { type: Object, default: null } })
const emit = defineEmits(['refresh', 'navigate'])

const { toast } = useToast()
const plan = ref(null)
const loading = ref(false)

/* 当前集数（用于高亮）—— 从 project.chapters 推断 */
const currentEpisode = computed(() => {
  const chs = props.project?.chapters
  if (!chs || !Array.isArray(chs) || !chs.length) return null
  /* 取最新的非回滚章号 */
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

onMounted(loadPlan)
</script>

<template>
  <div class="macro-view">
    <div v-if="loading" class="macro-loading">加载中…</div>

    <div v-else-if="!plan" class="macro-empty">
      <p>当前项目还没有宏观计划。</p>
      <button class="btn-main" data-testid="macro-empty-gacha" @click="emit('navigate', 'gacha')">前往开局向导生成</button>
    </div>

    <MacroDashboard v-else :plan="plan" :current-episode="currentEpisode" />
  </div>
</template>

<style scoped>
.macro-view { max-width: 1000px; margin: 0 auto; padding: 20px 24px 60px; }
.macro-loading, .macro-empty { text-align: center; padding: 60px 20px; color: var(--faint, #888); }
.macro-empty p { margin-bottom: 16px; }
</style>
