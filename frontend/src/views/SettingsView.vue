<script setup>
// 设置视图（P6.10）：LLM 接入卡（P23 起可编辑：provider 快捷下拉 + base_url/model/
// api_key 表单 + [测试连接] 先测后存 + [保存配置] 可选写回 .env）+
// 三个开关 EVAL_ENABLED / IR_FIRST / EVAL_MAX_ROUNDS（POST /api/settings 进程内覆盖，
// 不持久化，重启失效）+ 项目导出（P10.6：当前项目 zip 直链下载）+ 界面设置
// （主题 + 字号，复用全局 composable）。
//
// 明确不做（评审意见 8）：7 步验证开关、违规动作 mark 模式、伏笔回收窗口/钩子在线改。
// api_key 只上行不展示：已配置时输入框 placeholder 提示「输入以更换」，key 永不回前端。
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/api'
import { toSettingsVM } from '../api/adapters'
import { useToast } from '../composables/useToast'
import { useTheme } from '../composables/useTheme'
import { useFontSize } from '../composables/useFontSize'
import EmptyState from '../components/EmptyState.vue'

// App.vue 通过 <component :is> 统一传 :project :config；project 用于 P10.6
// 项目导出行（取当前项目名拼 /api/projects/{name}/export 直链）。
const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})

// P10.6 设置页导出入口：当前项目名（快照 meta.project；未加载完成时为空 → 隐藏按钮）
const currentName = computed(() => props.project?.meta?.project ?? '')

const { toast, toastError } = useToast()
const { theme, toggleTheme } = useTheme()
const { fsSize, setFont } = useFontSize()

const raw = ref(null)            // GET /api/settings 原始返回
const loading = ref(false)
const error = ref('')
const vm = computed(() => toSettingsVM(raw.value))

// 三开关本地编辑态（POST 成功后用返回值同步；失败回退）
const evalEnabled = ref(false)
const irFirst = ref(false)
const evalMaxRounds = ref(3)
const fastMode = ref(true)
const dirty = ref(false)         // 有未保存改动（理论上 POST 即时生效，无保存键）

async function load() {
  loading.value = true
  error.value = ''
  try {
    raw.value = await api.settings()
    const v = vm.value
    evalEnabled.value = v.evalEnabled
    irFirst.value = v.irFirst
    evalMaxRounds.value = v.evalMaxRounds
    fastMode.value = v.fastMode
    dirty.value = false
  } catch (e) {
    error.value = e.message
    toastError(`设置加载失败：${e.message}`)
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function saveToggle(key, val) {
  // 单键即时 POST（UX：改一个就生效，不走批量保存）
  try {
    const updated = await api.updateSettings({ [key]: val })
    raw.value = updated
    const v = vm.value
    evalEnabled.value = v.evalEnabled
    irFirst.value = v.irFirst
    evalMaxRounds.value = v.evalMaxRounds
    fastMode.value = v.fastMode
    dirty.value = false
    const label = { eval_enabled: '自评迭代', ir_first: 'IR-first 优先',
                    eval_max_rounds: '自评最大轮数', fast_mode: '快速模式' }[key] ?? key
    toast(`${label} 已更新（进程内覆盖，重启失效）`)
  } catch (e) {
    toastError(`设置写入失败：${e.message}`)
    // 回退：重新拉取
    await load()
  }
}

function onToggleEval(e) {
  const v = e.target.checked
  evalEnabled.value = v
  saveToggle('eval_enabled', v)
}
function onToggleIr(e) {
  const v = e.target.checked
  irFirst.value = v
  saveToggle('ir_first', v)
}
function onToggleFast(e) {
  const v = e.target.checked
  fastMode.value = v
  saveToggle('fast_mode', v)
}
function onMaxRounds(e) {
  let n = parseInt(e.target.value, 10)
  if (!Number.isFinite(n)) n = 3
  n = Math.max(1, Math.min(5, n))
  evalMaxRounds.value = n
  saveToggle('eval_max_rounds', n)
}

// ---- LLM 接入（P23：在线编辑 + 先测后存） ----
/* provider 快捷预设：选中自动填 base_url + 推荐 model；「自定义」不自动填 */
const PROVIDERS = [
  { key: 'moonshot', name: 'Moonshot 开放平台', baseUrl: 'https://api.moonshot.cn/v1', model: 'kimi-k2.6' },
  { key: 'kimicode', name: 'Kimi Code 套餐', baseUrl: 'https://api.kimi.com/coding/v1', model: 'kimi-for-coding' },
  { key: 'glm', name: '智谱 GLM', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash' },
  { key: 'deepseek', name: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1', model: 'deepseek-v4-flash' },
  { key: 'openai', name: 'OpenAI', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  { key: 'custom', name: '自定义', baseUrl: '', model: '' },
]
const providerKey = ref('custom')
const llmBaseUrl = ref('')
const llmModel = ref('')
const llmApiKey = ref('')          // 只上行不展示；空 = 保持不变
const persistEnv = ref(true)       // 写回 .env（重启后仍生效），默认勾
const forceSave = ref(false)       // 用户强制：未通过测试也允许保存
const testPassed = ref(false)      // 最近一次测试通过且表单未再改动
const saving = ref(false)
const saveError = ref('')

function onProviderChange() {
  const p = PROVIDERS.find(x => x.key === providerKey.value)
  if (p && p.key !== 'custom') {
    llmBaseUrl.value = p.baseUrl
    llmModel.value = p.model
  }
  markLlmDirty()
}
/* 表单任何改动都使「测试通过」失效（先测后存口径） */
function markLlmDirty() {
  testPassed.value = false
  saveError.value = ''
}
const canSaveLlm = computed(() => testPassed.value || forceSave.value)

// ---- 测试连接（B10 / P23：key 输入框非空测临时配置，否则测当前生效配置） ----
const testing = ref(false)
const testResult = ref(null)  // {ok, latency_ms, model, error?}
async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    const key = llmApiKey.value.trim()
    const body = key
      ? { base_url: llmBaseUrl.value.trim(), api_key: key, model: llmModel.value.trim() }
      : {}
    testResult.value = await api.testLlm(body)
    testPassed.value = !!testResult.value.ok
    if (testResult.value.ok) {
      toast(`连接正常 · ${testResult.value.latency_ms ?? '?'}ms · ${testResult.value.model}`)
    } else {
      toastError(`连接失败：${testResult.value.error ?? '未知错误'}`)
    }
  } catch (e) {
    testPassed.value = false
    toastError(`测试连接失败：${e.message}`)
  } finally {
    testing.value = false
  }
}

// ---- 保存 LLM 配置（P23：POST /api/settings/llm；空键不送 = 保持不变） ----
async function saveLlm() {
  if (!canSaveLlm.value || saving.value) return
  saving.value = true
  saveError.value = ''
  try {
    const body = { persist: persistEnv.value }
    if (llmBaseUrl.value.trim()) body.base_url = llmBaseUrl.value.trim()
    if (llmModel.value.trim()) body.model = llmModel.value.trim()
    if (llmApiKey.value.trim()) body.api_key = llmApiKey.value.trim()
    await api.updateLlmSettings(body)
    llmApiKey.value = ''          // 保存后清空 key 输入框（永不展示已存 key）
    testPassed.value = false
    forceSave.value = false
    await load()                  // 刷新 settings 视图（mode/model/掩码/配置态）
    toast(persistEnv.value
      ? 'LLM 配置已保存并写回 .env（重启后仍生效）'
      : 'LLM 配置已保存（进程内生效，重启失效）')
  } catch (e) {
    saveError.value = e.message   // 后端 detail（如 base_url 非 https 的 422 中文错误）
    toastError(`LLM 配置保存失败：${e.message}`)
  } finally {
    saving.value = false
  }
}

// 界面字号选择
const FONT_OPTIONS = [15, 16, 17, 18, 19, 20, 21]
function onFont(e) {
  setFont(parseInt(e.target.value, 10) || 17)
  toast(`正文字号 ${fsSize.value}px`)
}
</script>

<template>
  <!-- 加载错误 / 空态 -->
  <div v-if="error && !raw" class="sv-empty">
    <EmptyState icon="sliders" title="设置不可用"
      :desc="`/api/settings 拉取失败：${error}`" />
  </div>

  <div v-else class="settings">
    <div class="sv-scroll">
      <!-- LLM 接入卡片（P23：可编辑，先测后存） -->
      <section class="card">
        <header class="card-h">
          <span class="card-t">LLM 接入</span>
          <span class="card-tag" :class="{ mock: vm?.llmMode === 'mock' }">
            {{ vm?.llmMode === 'mock' ? 'MOCK 剧本' : (vm?.llmMode || '—') }}
          </span>
        </header>
        <div class="card-body">
          <!-- 状态行：配置态状态点 + 脱敏 base_url + 当前模型 -->
          <div class="llm-status">
            <span class="llm-dot" :class="{ on: vm?.llmConfigured }" aria-hidden="true"></span>
            <span>{{ vm?.llmConfigured ? '已配置' : '未配置' }}</span>
            <span class="llm-status-sep" aria-hidden="true">·</span>
            <span class="mono">{{ vm?.baseUrlMasked || '—' }}</span>
            <span class="llm-status-sep" aria-hidden="true">·</span>
            <span class="mono">{{ vm?.llmModel || '—' }}</span>
          </div>

          <div class="llm-form">
            <label class="llm-field">
              <span class="llm-label">服务商</span>
              <select class="sel llm-input" v-model="providerKey" data-testid="llm-provider-select"
                      aria-label="LLM 服务商快捷选择" @change="onProviderChange">
                <option v-for="p in PROVIDERS" :key="p.key" :value="p.key">{{ p.name }}</option>
              </select>
            </label>
            <label class="llm-field">
              <span class="llm-label">Base URL</span>
              <input class="llm-input" type="text" v-model="llmBaseUrl" spellcheck="false"
                     data-testid="llm-base-url-input"
                     placeholder="https://api.moonshot.cn/v1"
                     aria-label="LLM Base URL" @input="markLlmDirty" />
            </label>
            <label class="llm-field">
              <span class="llm-label">模型</span>
              <input class="llm-input" type="text" v-model="llmModel" spellcheck="false"
                     data-testid="llm-model-input"
                     placeholder="kimi-k2.6"
                     aria-label="LLM 模型名" @input="markLlmDirty" />
            </label>
            <label class="llm-field">
              <span class="llm-label">API Key</span>
              <input class="llm-input" type="password" v-model="llmApiKey" autocomplete="off"
                     data-testid="llm-key-input"
                     :placeholder="vm?.llmConfigured ? '已配置 · 输入以更换' : '粘贴你的 API key'"
                     aria-label="LLM API Key" @input="markLlmDirty" />
            </label>
          </div>

          <div class="llm-opts">
            <label class="llm-check">
              <input type="checkbox" v-model="persistEnv" data-testid="llm-persist-check" />
              写回 .env（重启后仍生效）
            </label>
            <label class="llm-check" title="跳过「先测后存」，直接保存">
              <input type="checkbox" v-model="forceSave" />
              未测试也保存（强制）
            </label>
          </div>

          <div class="test-zone">
            <!-- 包裹 span 保留旧 data-testid="test-connection"（测试指引文档在用），
                 新规范 testid 在按钮本体上 -->
            <span data-testid="test-connection" class="llm-test-wrap">
              <button class="btn primary" :disabled="testing" data-testid="llm-test-btn" @click="testConnection">
                {{ testing ? '测试中…' : '测试连接' }}
              </button>
            </span>
            <button class="btn" :disabled="!canSaveLlm || saving" data-testid="llm-save-btn"
                    :title="canSaveLlm ? '' : '先通过「测试连接」，或勾选「未测试也保存」'"
                    @click="saveLlm">
              {{ saving ? '保存中…' : '保存配置' }}
            </button>
            <span v-if="testResult" class="test-res" :class="{ ok: testResult.ok, fail: !testResult.ok }">
              <template v-if="testResult.ok">
                ✓ {{ testResult.latency_ms ?? '?' }}ms · {{ testResult.model }}
              </template>
              <template v-else>
                ✗ {{ testResult.error ?? '未知错误' }}
              </template>
            </span>
          </div>
          <div v-if="saveError" class="llm-save-err" role="alert">✗ {{ saveError }}</div>
          <div class="hint">
            测试为一次性最小请求（「请回复：好」max_tokens=10），只返回 ok/延迟/model，key 永不回前端。
            API key 留空则保持不变；base_url 必须 https（本机可用 http://localhost）。
          </div>
        </div>
      </section>

      <!-- 三个生成开关 -->
      <section class="card">
        <header class="card-h">
          <span class="card-t">生成行为</span>
          <span class="card-tag">进程内覆盖 · 重启失效</span>
        </header>
        <div class="card-body">
          <div class="gen-hint">
            开关在<b>下一次生成</b>时生效，不会打断当前正在生成的章节。
          </div>
          <div class="switch-row">
            <div class="sw-text">
              <div class="sw-name">快速模式（FAST_MODE）</div>
              <div class="sw-sub">开启后跳过自评闭环（critic+修正全省，速度快一倍、省 token），只留硬规则校验兜底；关闭走完整自评</div>
            </div>
            <label class="switch">
              <input type="checkbox" :checked="fastMode"
                     :disabled="loading"
                     @change="onToggleFast" aria-label="快速模式开关" data-testid="toggle-fast-mode" />
              <span class="slider"></span>
            </label>
          </div>

          <div class="switch-row">
            <div class="sw-text">
              <div class="sw-name">自评迭代（EVAL_ENABLED）</div>
              <div class="sw-sub">开启后生成走 CriticParliament 多轮自评（mock/剧本通道无效）</div>
            </div>
            <label class="switch">
              <input type="checkbox" :checked="evalEnabled"
                     :disabled="loading"
                     @change="onToggleEval" aria-label="自评迭代开关" data-testid="toggle-eval" />
              <span class="slider"></span>
            </label>
          </div>

          <div class="switch-row">
            <div class="sw-text">
              <div class="sw-name">IR-first 优先（IR_FIRST）</div>
              <div class="sw-sub">开启后初稿走 IR-first 路径（失败回退，mock/剧本通道无效）</div>
            </div>
            <label class="switch">
              <input type="checkbox" :checked="irFirst"
                     :disabled="loading"
                     @change="onToggleIr" aria-label="IR-first 优先开关" data-testid="toggle-ir-first" />
              <span class="slider"></span>
            </label>
          </div>

          <div class="switch-row">
            <div class="sw-text">
              <div class="sw-name">自评最大轮数（EVAL_MAX_ROUNDS）</div>
              <div class="sw-sub">钳 [1, 5] 防失控；自评关闭时无效</div>
            </div>
            <div class="num-ctl">
              <input type="number" min="1" max="5" step="1"
                     :value="evalMaxRounds"
                     :disabled="loading"
                     @change="onMaxRounds"
                     aria-label="自评最大轮数" />
            </div>
          </div>
        </div>
      </section>

      <!-- 项目导出（P10.6：设置页导出入口，浏览器直链下载 zip） -->
      <section class="card">
        <header class="card-h">
          <span class="card-t">项目</span>
          <span class="card-tag">zip 打包 · 可分享可备份</span>
        </header>
        <div class="card-body">
          <div class="switch-row">
            <div class="sw-text">
              <div class="sw-name">项目导出</div>
              <div class="sw-sub">
                当前项目《{{ currentName || '—' }}》打包为 zip：story.db 一致快照 + 章节 + 元数据。
                导出的包可在项目页「导入 zip」恢复到任意一台机器。
              </div>
            </div>
            <a v-if="currentName" class="btn" :href="api.exportProjectUrl(currentName)"
               :download="`${currentName}-story.zip`" aria-label="导出当前项目为 zip 下载"
               data-testid="settings-export-zip">导出 zip</a>
          </div>
        </div>
      </section>

      <!-- 界面设置 -->
      <section class="card">
        <header class="card-h">
          <span class="card-t">界面</span>
          <span class="card-tag">本机记忆 · localStorage</span>
        </header>
        <div class="card-body">
          <div class="switch-row">
            <div class="sw-text">
              <div class="sw-name">主题</div>
              <div class="sw-sub">日间 / 夜读（图表类组件订阅主题切换事件重绘）</div>
            </div>
            <button class="btn" @click="toggleTheme" :aria-label="theme === 'night' ? '切到日间' : '切到夜读'"
                    data-testid="settings-theme-toggle">
              {{ theme === 'night' ? '☀ 切到日间' : '☾ 切到夜读' }}
            </button>
          </div>
          <div class="switch-row">
            <div class="sw-text">
              <div class="sw-name">正文字号</div>
              <div class="sw-sub">仅影响手稿 .para 渲染（{{ fsSize }}px）</div>
            </div>
            <select class="sel" :value="fsSize" @change="onFont" aria-label="正文字号" data-testid="settings-font-size">
              <option v-for="n in FONT_OPTIONS" :key="n" :value="n">{{ n }}px</option>
            </select>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.sv-empty { height: 100%; display: flex; align-items: flex-start; justify-content: center; padding-top: 40px; }

.settings { height: 100%; overflow: hidden; background: var(--bg); transition: background .25s; }
.sv-scroll { max-width: 720px; margin: 0 auto; padding: 22px 18px 40px; overflow-y: auto; height: 100%; }

.card { background: var(--s1); border: 1px solid var(--line); border-radius: 8px;
  margin-bottom: 16px; transition: background .25s, border-color .25s; }
.card-h { display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--line); }
.card-t { font: 700 14px var(--serif); color: var(--ink); }
.card-tag { font-size: 11px; color: var(--faint); padding: 2px 8px;
  border-radius: 10px; background: var(--s3); }
.card-tag.mock { color: var(--violet); }
.card-body { padding: 14px 16px; }

.gen-hint { font-size: 11.5px; color: var(--faint); line-height: 1.6;
  margin-bottom: 8px; padding: 6px 10px; background: var(--s3);
  border-radius: 5px; }

.kv { display: flex; padding: 6px 0; font-size: 12.5px; align-items: baseline; gap: 10px; }
.kv .k { color: var(--faint); min-width: 130px; flex-shrink: 0; font-size: 11.5px; }
.kv .v { color: var(--ink2); word-break: break-all; }
.mono { font-family: Menlo, Consolas, monospace; font-size: 11.5px; }

.test-zone { display: flex; align-items: center; gap: 12px; margin-top: 12px;
  padding-top: 12px; border-top: 1px dashed var(--line); flex-wrap: wrap; }
.llm-test-wrap { display: inline-flex; }
.test-res { font-size: 12px; font-family: Menlo, Consolas, monospace; }
.test-res.ok { color: var(--accent); }
.test-res.fail { color: var(--danger); }
.hint { margin-top: 10px; font-size: 11px; color: var(--faint); line-height: 1.6; }

/* P23 LLM 接入表单（editorial 主题变量） */
.llm-status { display: flex; align-items: center; gap: 8px; font-size: 12px;
  color: var(--ink2); padding-bottom: 10px; margin-bottom: 12px;
  border-bottom: 1px dashed var(--line); flex-wrap: wrap; }
.llm-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--faint); flex-shrink: 0; }
.llm-dot.on { background: var(--green); }
.llm-status-sep { color: var(--faint); }
.llm-form { display: flex; flex-direction: column; gap: 10px; }
.llm-field { display: flex; align-items: center; gap: 10px; }
.llm-label { min-width: 64px; flex-shrink: 0; font-size: 11.5px; color: var(--faint); }
.llm-input { flex: 1; min-width: 0; padding: 5px 10px; border: 1px solid var(--line2);
  border-radius: 5px; background: var(--bg); color: var(--ink);
  font: 12px Menlo, Consolas, monospace; }
.llm-input:focus { outline: none; border-color: var(--primary); }
.llm-input::placeholder { color: var(--faint); }
select.llm-input { font-family: var(--sans); font-size: 12.5px; }
.llm-opts { display: flex; align-items: center; gap: 16px; margin-top: 10px; flex-wrap: wrap; }
.llm-check { display: inline-flex; align-items: center; gap: 6px;
  font-size: 11.5px; color: var(--ink2); cursor: pointer; }
.llm-save-err { margin-top: 10px; padding: 8px 12px; border: 1px solid var(--danger);
  border-radius: 6px; font-size: 12px; color: var(--danger); line-height: 1.6; }

.switch-row { display: flex; align-items: center; justify-content: space-between;
  padding: 11px 0; border-bottom: 1px dashed var(--line); gap: 14px; }
.switch-row:last-child { border-bottom: none; }
.sw-text { flex: 1; min-width: 0; }
.sw-name { font-size: 13px; color: var(--ink); font-weight: 600; }
.sw-sub { font-size: 11.5px; color: var(--faint); margin-top: 2px; line-height: 1.5; }

/* toggle switch */
.switch { position: relative; display: inline-block; width: 38px; height: 22px; flex-shrink: 0; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; cursor: pointer; inset: 0; background: var(--s3);
  border-radius: 11px; transition: .2s; }
.slider::before { content: ''; position: absolute; height: 16px; width: 16px;
  left: 3px; top: 3px; background: var(--bg); border-radius: 50%; transition: .2s;
  box-shadow: 0 1px 2px rgba(0,0,0,.15); }
.switch input:checked + .slider { background: var(--primary); }
.switch input:checked + .slider::before { transform: translateX(16px); }
.switch input:focus-visible + .slider { box-shadow: 0 0 0 2px var(--primary-tint); }

.num-ctl input { width: 60px; padding: 4px 8px; border: 1px solid var(--line2);
  border-radius: 5px; background: var(--bg); color: var(--ink);
  font: 13px Menlo, Consolas, monospace; text-align: center; }
.num-ctl input:focus { outline: none; border-color: var(--primary); }

.btn { font-size: 12px; padding: 5px 12px; border-radius: 5px;
  border: 1px solid var(--line); background: var(--s2); color: var(--ink2);
  cursor: pointer; transition: .12s; }
.btn:hover:not(:disabled) { color: var(--primary); border-color: var(--primary); }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.btn.primary { background: var(--primary); color: #fffdf8; border-color: var(--primary); }
.btn.primary:hover:not(:disabled) { filter: brightness(1.05); color: #fffdf8; }

.sel { font-size: 12px; padding: 4px 8px; border: 1px solid var(--line2);
  border-radius: 5px; background: var(--bg); color: var(--ink); }
.sel:focus { outline: none; border-color: var(--primary); }
</style>
