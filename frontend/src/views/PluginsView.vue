<script setup>
// 插件视图（P6.10）：只读展示 + 技能结晶列表 + 题材实验室（简化版）。
// 数据源：
//   - 扩展点分组：GET /api/config 的 plugins（{挂载点: [名称...] }）
//   - 技能结晶：GET /api/training/stats 的 recent_skills
//   - 题材实验室：POST /api/meta/config（UserIntent 输入 → StoryConfig 预览）
// 启停开关只读（评审意见 8：在线改 yaml 不支持，点击 toast 提示）。
// 题材实验室不做混合合成（评审意见 9）：只展示生成的配置，不写入引擎。
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/api'
import { toTrainingStatsVM, toMetaConfigVM, displayName } from '../api/adapters'
import { useToast } from '../composables/useToast'
import EmptyState from '../components/EmptyState.vue'

const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})

const { toast, toastError } = useToast()

/* P9.1：显示名中文化——标题列显示 title，id 降为小字副标 */
const dn = (id) => displayName(props.config, id)

const stats = ref(null)
const statsLoading = ref(false)
const statsError = ref('')

// 扩展点分组（从 config prop 派生，App 已拉过 /api/config）
const EXTENSION_ORDER = [
  'story.genre', 'story.culture', 'story.language',
  'story.skill', 'story.evaluator', 'story.world.rule',
]
const groups = computed(() => {
  const plugins = props.config?.plugins ?? {}
  const all = Array.from(new Set([...EXTENSION_ORDER, ...Object.keys(plugins)]))
  return all.map(point => ({
    point,
    items: plugins[point] ?? [],
  }))
})

/* P23：扩展点分桶标题中文化——config.extension_labels 形如
   "题材包：节奏/情感弧/原型/冲突/评估权重"，主标取「：」前中文名，
   全句放 title 悬停，id 保留为小字副标 */
const extLabels = computed(() => props.config?.extensionLabels ?? {})
function extLabelFull(point) { return extLabels.value[point] ?? '' }
function extLabel(point) {
  const full = extLabelFull(point)
  if (!full) return point
  return String(full).split(/[：:]/)[0].trim() || full
}

const trainingVm = computed(() => toTrainingStatsVM(stats.value))

async function loadStats() {
  statsLoading.value = true
  statsError.value = ''
  try {
    stats.value = await api.trainingStats()
  } catch (e) {
    statsError.value = e.message
  } finally {
    statsLoading.value = false
  }
}
onMounted(loadStats)

function onToggleClick(point, name) {
  toast(`插件启停需改 yaml（${point} / ${name}），不可在线切换`)
}

// ---- 题材实验室（简化版） ----
const intent = ref('一个发生在江南小镇的家族悬疑')
const cultureHint = ref('')
const language = ref('zh')
const targetLength = ref(12)
const genBusy = ref(false)
const metaResult = ref(null)  // toMetaConfigVM 输出

async function genConfig() {
  const theme = intent.value.trim()
  if (!theme) { toast('请输入主题描述'); return }
  genBusy.value = true
  metaResult.value = null
  try {
    const raw = await api.metaConfig({
      theme,
      culture_hint: cultureHint.value.trim(),
      language: language.value,
      target_length: targetLength.value,
      platform: 'novel',
    })
    metaResult.value = toMetaConfigVM(raw)
    toast(`配置已生成 · ${dn(metaResult.value.genre)} × ${dn(metaResult.value.culture)}`)
  } catch (e) {
    toastError(`配置生成失败：${e.message}`)
  } finally {
    genBusy.value = false
  }
}

</script>

<template>
  <div class="plugins">
    <div class="pv-scroll">
      <!-- 扩展点分组 -->
      <section class="card">
        <header class="card-h">
          <span class="card-t">扩展点</span>
          <span class="card-tag">只读 · 改 yaml</span>
        </header>
        <div class="card-body">
          <div v-for="g in groups" :key="g.point" class="ext-group" :data-testid="`plugin-group-${g.point}`">
            <div class="ext-point" :title="extLabelFull(g.point) || g.point">
              {{ extLabel(g.point) }}<span class="ext-id">{{ g.point }}</span>
            </div>
            <div v-if="g.items.length" class="ext-items">
              <div v-for="name in g.items" :key="name" class="ext-item">
                <span class="ext-name">{{ dn(name) }}<span v-if="dn(name) !== name" class="ext-id">{{ name }}</span></span>
                <label class="ro-switch" @click.prevent="onToggleClick(g.point, name)" title="只读，点击查看说明">
                  <input type="checkbox" checked disabled :aria-label="`启停：${name}`" />
                  <span class="slider"></span>
                </label>
              </div>
            </div>
            <div v-else class="muted">— 无注册插件</div>
          </div>
        </div>
      </section>

      <!-- 技能结晶 -->
      <section class="card">
        <header class="card-h">
          <span class="card-t">技能结晶</span>
          <span class="card-tag">训练信号</span>
        </header>
        <div class="card-body">
          <div v-if="statsError" class="muted">/api/training/stats 加载失败：{{ statsError }}</div>
          <div v-else-if="statsLoading" class="muted">加载中…</div>
          <template v-else-if="trainingVm">
            <div class="stat-row">
              <div class="stat">
                <div class="stat-n">{{ trainingVm.skills }}</div>
                <div class="stat-k">已注册技能</div>
              </div>
              <div class="stat">
                <div class="stat-n">{{ trainingVm.preferences }}</div>
                <div class="stat-k">偏好样本</div>
              </div>
              <div class="stat">
                <div class="stat-n">{{ trainingVm.style }}</div>
                <div class="stat-k">风格样本</div>
              </div>
            </div>

            <div v-if="trainingVm.recent.length" class="skills">
              <div class="sec-t">最近结晶（≤5）</div>
              <div v-for="(s, i) in trainingVm.recent" :key="i" class="skill-item">
                <div class="skill-name">{{ s.name }}</div>
                <div class="skill-meta">
                  <span v-if="s.source" class="mono">{{ s.source }}</span>
                  <span v-if="s.createdAt" class="mono">{{ s.createdAt }}</span>
                </div>
              </div>
            </div>
            <div v-else class="muted">尚无技能结晶（介入流的「沉淀为技能」产物会在此展示）</div>
          </template>
        </div>
      </section>

      <!-- 题材实验室（简化版） -->
      <section class="card">
        <header class="card-h">
          <span class="card-t">题材实验室</span>
          <span class="card-tag">Meta · 预览</span>
        </header>
        <div class="card-body">
          <div class="gl-sub">UserIntent → StoryConfig 预览（不写入引擎，不做混合合成）</div>
          <textarea class="gl-ta" rows="2" v-model="intent"
                    placeholder="例：一个发生在江南小镇的家族悬疑"
                    aria-label="主题描述"></textarea>
          <div class="gl-row">
            <input class="gl-input" v-model="cultureHint" placeholder="文化提示（可空）" aria-label="文化提示" />
            <select class="sel" v-model="language" aria-label="语言">
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
            <label class="gl-num">
              <span>目标章数</span>
              <input type="number" min="1" max="50" v-model.number="targetLength" aria-label="目标章数" />
            </label>
            <button class="btn primary" :disabled="genBusy" data-testid="genre-lab-generate" @click="genConfig">
              {{ genBusy ? '生成中…' : '生成配置' }}
            </button>
          </div>

          <div v-if="metaResult" class="gl-result">
            <div class="gl-result-h">StoryConfig 预览</div>
            <div class="kv"><span class="k">题材</span><span class="v">{{ dn(metaResult.genre) || '—' }}<span v-if="metaResult.genre" class="ext-id">{{ metaResult.genre }}</span></span></div>
            <div class="kv"><span class="k">文化</span><span class="v">{{ dn(metaResult.culture) || '—' }}<span v-if="metaResult.culture" class="ext-id">{{ metaResult.culture }}</span></span></div>
            <div class="kv"><span class="k">语言</span><span class="v mono">{{ metaResult.language || '—' }}</span></div>
            <div class="kv"><span class="k">target_length</span><span class="v mono">{{ metaResult.targetLength }} 章</span></div>
            <div v-if="metaResult.theme" class="kv"><span class="k">theme</span><span class="v">{{ metaResult.theme }}</span></div>
            <div class="gl-note">校验已在后端 generate_config 内完成（不兼容组合会 400）；此预览不持久化、不写入当前项目。</div>
          </div>
        </div>
      </section>

      <!-- 空态兜底 -->
      <div v-if="!groups.length && !trainingVm?.recent?.length" class="pv-empty">
        <EmptyState icon="puzzle" title="尚无插件与技能数据"
          desc="扩展点分组与技能结晶在 /api/config 与 /api/training/stats 就绪后展示。" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.plugins { height: 100%; overflow: hidden; background: var(--bg); transition: background .25s; }
.pv-scroll { max-width: 720px; margin: 0 auto; padding: 22px 18px 40px; overflow-y: auto; height: 100%; }
.pv-empty { padding-top: 30px; }

.card { background: var(--s1); border: 1px solid var(--line); border-radius: 8px;
  margin-bottom: 16px; transition: background .25s, border-color .25s; }
.card-h { display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--line); }
.card-t { font: 700 14px var(--serif); color: var(--ink); }
.card-tag { font-size: 11px; color: var(--faint); padding: 2px 8px;
  border-radius: 10px; background: var(--s3); }
.card-body { padding: 14px 16px; }

.ext-group { padding: 8px 0; border-bottom: 1px dashed var(--line); }
.ext-group:last-child { border-bottom: none; }
.ext-point { font: 600 12.5px var(--sans); color: var(--ink); margin-bottom: 6px; }
.ext-items { display: flex; flex-direction: column; gap: 4px; }
.ext-item { display: flex; align-items: center; justify-content: space-between;
  padding: 4px 0; font-size: 12.5px; }
.ext-name { color: var(--ink2); }
.ext-id { font-family: Menlo, Consolas, monospace; font-size: 10.5px; color: var(--faint); margin-left: 8px; }

/* 只读开关（disabled，仅展示，点击 toast） */
.ro-switch { position: relative; display: inline-block; width: 32px; height: 18px; cursor: pointer; }
.ro-switch input { opacity: 0; width: 0; height: 0; }
.ro-switch .slider { position: absolute; inset: 0; background: var(--primary);
  border-radius: 9px; transition: .2s; opacity: .65; }
.ro-switch .slider::before { content: ''; position: absolute; height: 12px; width: 12px;
  left: 3px; top: 3px; background: var(--bg); border-radius: 50%; transform: translateX(14px); }

.stat-row { display: flex; gap: 18px; padding: 8px 0 14px; border-bottom: 1px dashed var(--line); }
.stat { flex: 1; text-align: center; }
.stat-n { font: 700 22px var(--serif); color: var(--ink); }
.stat-k { font-size: 11px; color: var(--faint); margin-top: 2px; }

.sec-t { font-size: 11px; color: var(--faint); letter-spacing: 1.2px; margin: 14px 0 8px; }
.skills { display: flex; flex-direction: column; gap: 6px; }
.skill-item { padding: 8px 10px; background: var(--s2); border-radius: 5px;
  border-left: 2px solid var(--primary); }
.skill-name { font-size: 13px; color: var(--ink); font-weight: 600; }
.skill-meta { display: flex; gap: 12px; margin-top: 3px; font-size: 10.5px; color: var(--faint); }
.mono { font-family: Menlo, Consolas, monospace; }
.muted { color: var(--faint); font-size: 11.5px; padding: 8px 0; }

/* 题材实验室 */
.gl-sub { font-size: 11.5px; color: var(--faint); margin-bottom: 8px; line-height: 1.6; }
.gl-ta { width: 100%; padding: 8px 10px; border: 1px solid var(--line2); border-radius: 6px;
  background: var(--bg); color: var(--ink); font: 13px/1.6 var(--serif); resize: vertical;
  min-height: 48px; box-sizing: border-box; }
.gl-ta:focus { outline: none; border-color: var(--primary); }
.gl-row { display: flex; align-items: center; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.gl-input { flex: 1; min-width: 160px; padding: 5px 10px; border: 1px solid var(--line2);
  border-radius: 5px; background: var(--bg); color: var(--ink); font-size: 12px; }
.gl-input:focus { outline: none; border-color: var(--primary); }
.gl-num { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--faint); }
.gl-num input { width: 56px; padding: 4px 8px; border: 1px solid var(--line2);
  border-radius: 5px; background: var(--bg); color: var(--ink); font: 12px Menlo, monospace; text-align: center; }
.gl-result { margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--line); }
.gl-result-h { font: 600 12px var(--serif); color: var(--ink); margin-bottom: 8px; }
.gl-result .kv { padding: 3px 0; }
.gl-result .k { min-width: 110px; }
.gl-note { margin-top: 10px; font-size: 11px; color: var(--faint); line-height: 1.6; }

.kv { display: flex; padding: 3px 0; font-size: 12px; align-items: baseline; gap: 10px; }
.kv .k { color: var(--faint); min-width: 90px; flex-shrink: 0; font-size: 11px; }
.kv .v { color: var(--ink2); word-break: break-all; }
.mono { font-family: Menlo, Consolas, monospace; font-size: 11.5px; }
</style>
