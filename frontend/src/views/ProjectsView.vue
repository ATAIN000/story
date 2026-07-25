<script setup>
// 项目页（P10.4，多项目管理）：项目卡片网格 —— 名称 / 题材（displayName title +
// id 小字副标）/ 文化 / 章数·tick / 最后打开 + current 徽标；卡片操作：
// 「继续」（open → 整页刷新，SPA 重拉 config/project 落写作台）/「导出」（浏览器
// 直接下载 zip，不走 JSON 通道）；顶部「导入 zip」（P10.6：multipart 上传外部
// 项目包）/「开新项目」→ 开局页。
// 铁律执行：列表只消费 toProjectsVM。
import { ref, onMounted } from 'vue'
import { api } from '../api/api'
import { toProjectsVM, displayName } from '../api/adapters'
import { useToast } from '../composables/useToast'
import { useGeneration } from '../composables/useGeneration'
import AppIcon from '../components/AppIcon.vue'
import EmptyState from '../components/EmptyState.vue'

const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})
const emit = defineEmits(['refresh', 'navigate'])

const { toast, toastError } = useToast()
const { generating } = useGeneration()   // P23.3：生成中禁止切项目（后端持锁，前端禁用入口）
const dn = (id) => displayName(props.config, id)

const projects = ref([])
const loading = ref(true)
const opening = ref('')          // 正在切换的项目名（防重入；按钮提示）
const fileInput = ref(null)      // 隐藏的 zip 选择框（P10.6 导入）
const importing = ref(false)     // 导入进行中（防重入；按钮提示）

onMounted(load)

async function load() {
  loading.value = true
  try {
    projects.value = toProjectsVM(await api.projects())
  } catch (e) {
    toastError(`加载项目列表失败：${e.message}`)
  } finally {
    loading.value = false
  }
}

/* 导入（P10.6）：选 zip → POST /api/projects/import → toast → 刷新列表。
   项目名由后端定（zip 内 project.json.name → zip 文件名）；409 重名提示改名后重导 */
function pickImport() {
  if (importing.value) return
  fileInput.value?.click()
}

async function onImportFile(e) {
  const file = e.target.files?.[0]
  e.target.value = ''            // 重置选择框，允许重选同一文件
  if (!file || importing.value) return
  importing.value = true
  try {
    const res = await api.importProject(file)
    toast(`项目《${res.name}》已导入，点「继续」开工`)
    await load()
  } catch (err) {
    if (err.status === 409) {
      toastError(`导入失败：${err.message}——请改名后重试（zip 文件名或包内 project.json 的 name）`)
    } else {
      toastError(`导入失败：${err.message}`)
    }
  } finally {
    importing.value = false
  }
}

/* 继续：open 切栈 → 整页刷新（P11.2：SPA 重拉 config + project，恢复项目自身题材，
   刷新后落在默认写作台视图）；失败停留本页（列表不变，可重试） */
async function openProject(p) {
  if (p.current || opening.value) return
  if (generating.value) { toast('生成进行中，请等待完成后切换项目'); return }
  opening.value = p.name
  try {
    await api.openProject(p.name)
    toast(`已切换到《${p.name}》`)
    window.location.reload()
  } catch (e) {
    toastError(`切换项目失败：${e.message}`)
  } finally {
    opening.value = ''
  }
}
</script>

<template>
  <div class="projects">
    <header class="projects-head">
      <h2>项目</h2>
      <span class="projects-sub">每个项目独立成书：章节、世界状态与题材配置互不干扰。</span>
      <button class="btn-line" :disabled="importing" aria-label="导入项目 zip 包"
              data-testid="import-zip" @click="pickImport">{{ importing ? '导入中…' : '导入 zip' }}</button>
      <button class="btn-main" aria-label="开新项目，去抽一组开局配置"
              data-testid="new-project" @click="emit('navigate', 'gacha')">开新项目</button>
      <input ref="fileInput" type="file" accept=".zip" hidden tabindex="-1"
             aria-hidden="true" @change="onImportFile">
    </header>

    <div v-if="loading" class="projects-loading" role="status">
      <span class="gc-spin" aria-hidden="true"></span>加载项目列表…
    </div>

    <div v-else-if="projects.length" class="proj-grid" role="region" aria-label="项目卡片区">
      <article v-for="p in projects" :key="p.name" class="proj-card" :class="{ current: p.current }"
               :data-testid="`project-card-${p.name}`">
        <div class="proj-top">
          <div class="proj-name">{{ p.name }}</div>
          <span v-if="p.current" class="proj-badge">当前</span>
        </div>
        <div class="proj-genre">
          {{ dn(p.genre) || '—' }}<span v-if="p.genre && dn(p.genre) !== p.genre" class="proj-id"> {{ p.genre }}</span>
        </div>
        <div class="proj-meta">{{ dn(p.culture) || '—' }} · 第 {{ p.chapterCount }} 章 · tick {{ p.headTick }}</div>
        <div class="proj-time">最后打开 {{ p.lastOpened || '—' }}</div>
        <div class="proj-act">
          <button class="btn-main" :disabled="p.current || !!opening || generating"
                  data-testid="project-continue"
                  :title="generating ? '生成进行中，暂不可切换' : ''"
                  :aria-label="p.current ? `项目 ${p.name} 正在进行中` : `继续项目 ${p.name}，切换并跳到写作台`"
                  @click="openProject(p)">
            {{ opening === p.name ? '切换中…' : (p.current ? '进行中' : '继续') }}
          </button>
          <a class="btn-line proj-export" :href="api.exportProjectUrl(p.name)" :download="`${p.name}-story.zip`"
             data-testid="project-export"
             :aria-label="`导出项目 ${p.name} 为 zip 下载`">
            <AppIcon name="download" :size="12" /> 导出
          </a>
        </div>
      </article>
    </div>

    <EmptyState v-else icon="book" title="还没有项目"
                desc="项目是一本书的全部：章节、世界状态、伏笔账与训练信号。从抽一组开局配置开始。">
      <button class="btn-main" aria-label="开新项目，去抽一组开局配置"
              data-testid="new-project-empty" @click="emit('navigate', 'gacha')">开新项目</button>
    </EmptyState>
  </div>
</template>
