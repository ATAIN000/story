<script setup>
// 设置视图（P6.10）：LLM 接入卡（展示掩码 base_url/model/mode + [测试连接]）+
// 三个开关 EVAL_ENABLED / IR_FIRST / EVAL_MAX_ROUNDS（POST /api/settings 进程内覆盖，
// 不持久化，重启失效）+ 界面设置（主题 + 字号，复用全局 composable）。
//
// 明确不做（评审意见 8）：7 步验证开关、违规动作 mark 模式、provider 在线切换、
// 伏笔回收窗口/钩子在线改。key 永不在前端展示或编辑（走 .env）。
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/api'
import { toSettingsVM } from '../api/adapters'
import { useToast } from '../composables/useToast'
import { useTheme } from '../composables/useTheme'
import { useFontSize } from '../composables/useFontSize'
import EmptyState from '../components/EmptyState.vue'

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
    dirty.value = false
    const label = { eval_enabled: '自评迭代', ir_first: 'IR-first 优先',
                    eval_max_rounds: '自评最大轮数' }[key] ?? key
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
function onMaxRounds(e) {
  let n = parseInt(e.target.value, 10)
  if (!Number.isFinite(n)) n = 3
  n = Math.max(1, Math.min(5, n))
  evalMaxRounds.value = n
  saveToggle('eval_max_rounds', n)
}

// ---- 测试连接（B10） ----
const testing = ref(false)
const testResult = ref(null)  // {ok, latency_ms, model, error?}
async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await api.testLlm({})
    if (testResult.value.ok) {
      toast(`连接正常 · ${testResult.value.latency_ms ?? '?'}ms · ${testResult.value.model}`)
    } else {
      toastError(`连接失败：${testResult.value.error ?? '未知错误'}`)
    }
  } catch (e) {
    toastError(`测试连接失败：${e.message}`)
  } finally {
    testing.value = false
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
      <!-- LLM 接入卡片 -->
      <section class="card">
        <header class="card-h">
          <span class="card-t">LLM 接入</span>
          <span class="card-tag" :class="{ mock: vm?.llmMode === 'mock' }">
            {{ vm?.llmMode === 'mock' ? 'MOCK 剧本' : (vm?.llmMode || '—') }}
          </span>
        </header>
        <div class="card-body">
          <div class="kv">
            <span class="k">模型</span>
            <span class="v mono">{{ vm?.llmModel || '—' }}</span>
          </div>
          <div class="kv">
            <span class="k">Base URL（脱敏）</span>
            <span class="v mono">{{ vm?.baseUrlMasked || '—' }}</span>
          </div>
          <div class="kv">
            <span class="k">API Key</span>
            <span class="v">●●●●●●（走 .env，不可见/不可编辑）</span>
          </div>

          <div class="test-zone">
            <button class="btn primary" :disabled="testing" @click="testConnection">
              {{ testing ? '测试中…' : '测试连接' }}
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
          <div class="hint">
            一次性最小请求（「请回复：好」max_tokens=10），只返回 ok/延迟/model，key 永不回前端。
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
          <div class="switch-row">
            <div class="sw-text">
              <div class="sw-name">自评迭代（EVAL_ENABLED）</div>
              <div class="sw-sub">开启后生成走 CriticParliament 多轮自评（mock/剧本通道无效）</div>
            </div>
            <label class="switch">
              <input type="checkbox" :checked="evalEnabled"
                     :disabled="loading"
                     @change="onToggleEval" aria-label="自评迭代开关" />
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
                     @change="onToggleIr" aria-label="IR-first 优先开关" />
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
            <button class="btn" @click="toggleTheme" :aria-label="theme === 'night' ? '切到日间' : '切到夜读'">
              {{ theme === 'night' ? '☀ 切到日间' : '☾ 切到夜读' }}
            </button>
          </div>
          <div class="switch-row">
            <div class="sw-text">
              <div class="sw-name">正文字号</div>
              <div class="sw-sub">仅影响手稿 .para 渲染（{{ fsSize }}px）</div>
            </div>
            <select class="sel" :value="fsSize" @change="onFont" aria-label="正文字号">
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

.kv { display: flex; padding: 6px 0; font-size: 12.5px; align-items: baseline; gap: 10px; }
.kv .k { color: var(--faint); min-width: 130px; flex-shrink: 0; font-size: 11.5px; }
.kv .v { color: var(--ink2); word-break: break-all; }
.mono { font-family: Menlo, Consolas, monospace; font-size: 11.5px; }

.test-zone { display: flex; align-items: center; gap: 12px; margin-top: 12px;
  padding-top: 12px; border-top: 1px dashed var(--line); }
.test-res { font-size: 12px; font-family: Menlo, Consolas, monospace; }
.test-res.ok { color: var(--accent); }
.test-res.fail { color: var(--danger); }
.hint { margin-top: 10px; font-size: 11px; color: var(--faint); line-height: 1.6; }

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
