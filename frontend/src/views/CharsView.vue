<script setup>
// 人物视图（P6.9）：三栏 —— 列表 + 关系（图谱 ≤8 / 表 >8）+ 详情。
// 数据源：GET /api/characters（独立拉取，不在 project 快照内；onMounted 拉一次 +
// refresh 事件时重拉）。图谱节点坐标用圆形布局动态计算（评审 8.3-#4：不硬编码），
// ≤8 人启用 SVG，>8 降级关系表。主题切换订阅 THEME_EVENT 重绘（颜色变量切换）。
// 角色介入：右上按钮 → 简表单（信念/关系/遗忘 三类 + textarea）→ POST /api/intervene
// type=character（本任务只接入口，弹窗复用 ParagraphOps modal 风格）。
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { api } from '../api/api'
import { toCharactersVM } from '../api/adapters'
import { useToast } from '../composables/useToast'
import { THEME_EVENT } from '../composables/useTheme'
import EmptyState from '../components/EmptyState.vue'

const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})

const { toast, toastError } = useToast()

const raw = ref(null)         // /api/characters 原始返回
const loading = ref(false)
const error = ref('')
const vm = computed(() => toCharactersVM(raw.value ?? []))
/* 记录上次拉取时的项目 tick，避免 project prop 浅引用变化触发重拉 */
const lastTick = ref(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    raw.value = await api.characters()
    lastTick.value = props.project?.meta?.headTick ?? null
  } catch (e) {
    error.value = e.message
    toastError(`人物数据加载失败：${e.message}`)
  } finally {
    loading.value = false
  }
}
onMounted(load)
/* project prop 变化（顶部 refresh 触发）→ head_tick 不同则重拉人物 */
watch(() => props.project, p => {
  const t = p?.meta?.headTick ?? null
  if (t !== lastTick.value) load()
})

/* 选中角色 id */
const selectedId = ref(null)
const selected = computed(() =>
  vm.value.characters.find(c => c.id === selectedId.value) ?? vm.value.characters[0] ?? null)
watch(() => vm.value.characters, list => {
  if (!list.length) { selectedId.value = null; return }
  if (!selectedId.value || !list.some(c => c.id === selectedId.value)) {
    selectedId.value = list[0].id
  }
}, { immediate: true })

/* ---- 节点颜色：id 首字 hash → 主题调色板散列（不编造 faction） ---- */
const PALETTE = ['var(--primary)', 'var(--accent)', 'var(--sky)', 'var(--violet)', 'var(--danger)', 'var(--item)']
function colorOf(id) {
  if (!id) return PALETTE[0]
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0
  return PALETTE[h % PALETTE.length]
}

/* ---- 图谱几何：圆形布局（节点 ≤8 时动态计算坐标，不硬编码） ----
 * viewBox 固定 980×480；节点按 N 等分圆周排列。 */
const VB_W = 980, VB_H = 480, R_NODE = 30
const nodes = computed(() => {
  const list = vm.value.characters
  const n = list.length
  if (!n) return []
  const cx = VB_W / 2, cy = VB_H / 2 + 10
  const radius = Math.min(VB_W, VB_H) / 2 - 70
  return list.map((c, i) => {
    const ang = (i / n) * Math.PI * 2 - Math.PI / 2   // 从顶端开始顺时针
    return {
      ...c,
      color: colorOf(c.id),
      x: cx + radius * Math.cos(ang),
      y: cy + radius * Math.sin(ang),
    }
  })
})
const nodeById = computed(() => {
  const m = new Map()
  nodes.value.forEach(n => m.set(n.id, n))
  return m
})

/* 关系线（双向中较强的代表，已在 adapter 去重） */
const rels = computed(() => {
  return vm.value.relations.map(r => ({
    ...r,
    a: nodeById.value.get(r.a),
    b: nodeById.value.get(r.b),
    hot: (r.intensity ?? 0) >= 0.7,
    dash: (r.intensity ?? 0) < 0.3,
  })).filter(r => r.a && r.b)
})

/* tooltip（相对 graph 容器定位：评审 8.2-#9） */
const tip = ref({ show: false, x: 0, y: 0, id: '', role: '', goal: '' })
function onNodeEnter(n, ev) {
  const zone = ev.currentTarget.closest('.graph-zone')
  const zr = zone?.getBoundingClientRect()
  const sr = ev.currentTarget.getBoundingClientRect()
  if (!zr) return
  tip.value = {
    show: true,
    x: sr.left - zr.left + sr.width / 2 - 60,
    y: sr.top - zr.top - 8,
    id: n.id,
    role: n.role || '—',
    goal: n.goals?.[0] || '',
  }
}
function onNodeLeave() { tip.value.show = false }

/* ---- 主题切换重绘订阅（SVG 颜色走 CSS 变量，本身会自动随主题切换；
 *   但 SVG path/text 的内联 stroke 由 JS 计算（pal 色不变）—— 这里用一个
 *   tick 强制重渲染以应对任何以 getComputedStyle 缓存的色值场景） ---- */
const themeTick = ref(0)
function onTheme() { themeTick.value++ }
onMounted(() => window.addEventListener(THEME_EVENT, onTheme))
onUnmounted(() => window.removeEventListener(THEME_EVENT, onTheme))

/* ---- 角色介入弹窗 ---- */
const IV_TYPES = [
  { id: 'belief', label: '信念', field: 'belief', placeholder: '例：张三相信姑母说的是真话' },
  { id: 'relation', label: '关系', field: 'relation', placeholder: '例：刘伯与张三的关系强化为共谋' },
  { id: 'forget', label: '遗忘', field: 'forget', placeholder: '例：公孙策忘记今晨看到的细节' },
]
const ivOpen = ref(false)
const ivType = ref('belief')
const ivText = ref('')
const ivBusy = ref(false)
function openIv() {
  if (!selected.value) { toast('请先选择角色'); return }
  ivType.value = 'belief'
  ivText.value = ''
  ivOpen.value = true
}
function closeIv() { ivOpen.value = false }
async function submitIv() {
  const v = ivText.value.trim()
  if (!v) return
  const t = IV_TYPES.find(x => x.id === ivType.value)
  const cid = selected.value?.id
  ivBusy.value = true
  try {
    const r = await api.intervene('character', {
      character: cid,
      [t.field]: v,
    }, `角色介入 · ${cid} · ${t.label}`)
    if (r.ok !== false) {
      toast(`角色介入已记录 · ${cid} 的${t.label}调整下章生效`)
      closeIv()
    } else {
      toastError(`角色介入失败：${r.message || ''}`)
    }
  } catch (e) {
    toastError(`角色介入失败：${e.message}`)
  } finally {
    ivBusy.value = false
  }
}

/* 监听 project 变化（顶部 refresh）→ 重拉人物（关系/voice 可能变化） */

</script>

<template>
  <!-- 加载错误 / 空态 -->
  <div v-if="error && !raw" class="cv-empty">
    <EmptyState icon="users" title="人物数据不可用"
      :desc="`/api/characters 拉取失败：${error}`" />
  </div>
  <div v-else-if="!loading && !vm.characters.length" class="cv-empty">
    <EmptyState icon="users" title="还没有角色"
      desc="生成首章后，事件流会确立角色心智，这里能看到角色卡、关系图谱与声音样本。" />
  </div>

  <div v-else class="chars" :key="themeTick">
    <!-- 左：列表 -->
    <aside class="char-list" aria-label="角色列表">
      <div class="b-t">人物 · {{ vm.characters.length }}</div>
      <button v-for="c in vm.characters" :key="c.id" class="cl-item"
              :class="{ active: c.id === selected?.id }"
              :aria-current="c.id === selected?.id ? 'true' : undefined"
              @click="selectedId = c.id">
        <span class="avatar" :style="{ background: colorOf(c.id) }">{{ c.id[0] }}</span>
        <span class="cl-meta">
          <span class="n">{{ c.id }}</span>
          <span class="r">{{ c.role || '—' }}</span>
        </span>
      </button>
    </aside>

    <!-- 中：关系（图谱 ≤8 / 表 >8） -->
    <section class="graph-zone" aria-label="关系图">
      <div class="graph-hint">{{ vm.useGraph
        ? `≤8 人 · 图谱视图（圆形布局）`
        : `>8 人 · 降级为关系表（评审 8.3-#4）` }}</div>

      <svg v-if="vm.useGraph" class="rel-graph" :viewBox="`0 0 ${VB_W} ${VB_H}`"
           preserveAspectRatio="xMidYMid meet" role="img" aria-label="角色关系图谱">
        <!-- 关系曲线 -->
        <g class="rel-lines">
          <path v-for="(r, i) in rels" :key="`l${i}`"
                :d="`M ${r.a.x} ${r.a.y} Q ${(r.a.x + r.b.x) / 2} ${(r.a.y + r.b.y) / 2 - 26}, ${r.b.x} ${r.b.y}`"
                fill="none"
                :stroke="r.hot ? 'var(--danger)' : 'var(--edge)'"
                :stroke-width="1 + (r.intensity || 0) * 3"
                :stroke-dasharray="r.dash ? '6 5' : 'none'"
                :opacity="r.hot ? 0.7 : 0.9" />
          <text v-for="(r, i) in rels" :key="`lt${i}`"
                :x="(r.a.x + r.b.x) / 2" :y="(r.a.y + r.b.y) / 2 - 22"
                text-anchor="middle" font-size="12" fill="var(--faint)">{{ r.type }}</text>
        </g>
        <!-- 节点 -->
        <g v-for="n in nodes" :key="`n${n.id}`" class="g-node"
           :tabindex="0" role="button" :aria-label="`${n.id} · ${n.role}`"
           @click="selectedId = n.id"
           @mouseenter="onNodeEnter(n, $event)"
           @mouseleave="onNodeLeave"
           @keydown.enter.prevent="selectedId = n.id">
          <circle :cx="n.x" :cy="n.y" :r="R_NODE"
                  :fill="n.color + '22'" :stroke="n.color"
                  :stroke-width="n.id === selected?.id ? 3 : 1.5" />
          <text :x="n.x" :y="n.y + 5" text-anchor="middle"
                font-size="15" font-weight="700" :fill="n.color"
                style="font-family: var(--serif)">{{ n.id[0] }}</text>
          <text :x="n.x" :y="n.y + R_NODE + 16" text-anchor="middle"
                font-size="12" fill="var(--faint)">{{ n.role || '—' }}</text>
        </g>
      </svg>

      <!-- >8 人降级：关系表 -->
      <div v-else class="rel-table-wrap">
        <table class="rel-table">
          <thead><tr><th>角色 A</th><th>关系</th><th>强度</th><th>角色 B</th></tr></thead>
          <tbody>
            <tr v-for="(r, i) in vm.relations" :key="i">
              <td>{{ r.a }}</td>
              <td>{{ r.type }}</td>
              <td><span class="bar"><i :style="{ width: Math.round((r.intensity || 0) * 100) + '%' }"></i></span></td>
              <td>{{ r.b }}</td>
            </tr>
            <tr v-if="!vm.relations.length"><td colspan="4" class="muted">暂无关系记录。</td></tr>
          </tbody>
        </table>
      </div>

      <!-- tooltip -->
      <div class="g-tip" :style="{ left: tip.x + 'px', top: tip.y + 'px', opacity: tip.show ? 1 : 0 }">
        <b>{{ tip.id }}</b> · {{ tip.role }}<br>
        <span style="color:var(--faint)">{{ tip.goal }}</span>
      </div>

      <!-- 角色介入按钮 -->
      <button class="iv-fab" @click="openIv" title="角色介入" aria-label="角色介入">✋ 角色介入</button>
    </section>

    <!-- 右：详情 -->
    <aside class="char-detail" aria-label="角色详情" v-if="selected">
      <div class="cd-head">
        <span class="avatar lg" :style="{ background: colorOf(selected.id) }">{{ selected.id[0] }}</span>
        <div>
          <div class="n">{{ selected.id }}</div>
          <div class="r">{{ selected.role || '—' }}</div>
        </div>
      </div>

      <div class="cd-sec">
        <div class="s-t">他知道（合法认知）</div>
        <div v-if="selected.knows.length" class="tags">
          <span v-for="(k, i) in selected.knows" :key="i" class="tag k">{{ k }}</span>
        </div>
        <div v-else class="muted">—</div>
      </div>

      <div v-if="selected.secrets.length" class="cd-sec">
        <div class="s-t">他的秘密（对读者/其他角色不可见）</div>
        <div class="tags">
          <span v-for="(s, i) in selected.secrets" :key="i" class="tag s">🔒 {{ s }}</span>
        </div>
      </div>

      <div v-if="selected.goals.length" class="cd-sec">
        <div class="s-t">目标</div>
        <div class="tags">
          <span v-for="(g, i) in selected.goals" :key="i" class="tag g">{{ g }}</span>
        </div>
      </div>

      <div v-if="selected.voice" class="cd-sec">
        <div class="s-t">声音样本</div>
        <blockquote class="voice-q">{{ selected.voice }}</blockquote>
      </div>

      <div v-if="selected.relations?.length" class="cd-sec">
        <div class="s-t">他的关系</div>
        <div class="rel-mini">
          <div v-for="(r, i) in selected.relations" :key="i" class="rel-mini-row">
            <span class="rm-target" @click="selectedId = r.target">{{ r.target }}</span>
            <span class="rm-type">{{ r.type }}</span>
            <span class="rm-int">· {{ (r.intensity ?? 0).toFixed(2) }}</span>
          </div>
        </div>
      </div>

      <button class="iv-btn" @click="openIv">✋ 角色介入：直改心智/弧线</button>
    </aside>
  </div>

  <!-- 角色介入弹窗（最简表单：信念/关系/遗忘 + textarea，复用 .diag 风格） -->
  <teleport to="body">
    <div v-if="ivOpen" class="modal-mask" @click.self="closeIv" role="dialog"
         aria-modal="true" aria-labelledby="ivTitle">
      <div class="modal iv-modal">
        <div class="d-t" id="ivTitle">角色介入 · {{ selected?.id }}</div>
        <div class="iv-sub">进作者意图，下章决策卡生效（与段落操作共享介入流）</div>
        <div class="rw-chips" style="margin: 10px 0">
          <span v-for="t in IV_TYPES" :key="t.id" class="rw-chip"
                :class="{ on: ivType === t.id }" @click="ivType = t.id">{{ t.label }}</span>
        </div>
        <textarea class="rw-ta" rows="3" v-model="ivText"
                  :placeholder="IV_TYPES.find(t => t.id === ivType)?.placeholder || ''"
                  @keydown.enter.prevent="submitIv"
                  @keydown.esc.prevent="closeIv"></textarea>
        <div class="iv-bar">
          <span class="ie-hint">Enter 确定 · Esc 取消</span>
          <button class="ie-ok" :disabled="!ivText.trim() || ivBusy" @click="submitIv">
            {{ ivBusy ? '提交中…' : '✓ 确定' }}
          </button>
          <button class="ie-cancel" @click="closeIv" :disabled="ivBusy">取消</button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.cv-empty { height: 100%; display: flex; align-items: flex-start; justify-content: center; overflow-y: auto; padding-top: 40px; }

/* 三栏（story.html :134） */
.chars { display: grid; grid-template-columns: 220px 1fr 300px; height: 100%; overflow: hidden; }
@media (max-width: 1100px) { .chars { grid-template-columns: 180px 1fr 260px; } }
@media (max-width: 880px) { .chars { grid-template-columns: 1fr; grid-template-rows: auto 1fr auto; height: auto; } }

/* 左列：列表 */
.char-list { border-right: 1px solid var(--line); background: var(--s1); padding: 14px 10px; overflow-y: auto; transition: background .25s; }
.b-t { font: 700 12px var(--serif); color: var(--ink2); padding: 0 8px 10px; letter-spacing: 1px; }
.cl-item { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px;
  border: none; background: transparent; border-radius: 6px; cursor: pointer; margin-bottom: 1px;
  text-align: left; transition: background .12s; }
.cl-item:hover { background: var(--s3); }
.cl-item.active { background: var(--primary-tint); }
.avatar { width: 32px; height: 32px; border-radius: 50%; display: inline-flex;
  align-items: center; justify-content: center; font: 700 14px var(--serif);
  color: #fffdf8; flex-shrink: 0; border: none; }
.avatar.lg { width: 42px; height: 42px; font-size: 17px; }
.cl-meta { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.cl-meta .n { font-size: 13px; font-weight: 600; color: var(--ink); }
.cl-meta .r { font-size: 11px; color: var(--faint); }

/* 中列：关系区 */
.graph-zone { position: relative; overflow: hidden; background: var(--bg); transition: background .25s; }
.graph-hint { position: absolute; left: 18px; top: 14px; font-size: 11px; color: var(--faint); z-index: 2; }
.rel-graph { width: 100%; height: 100%; display: block; }
.g-node { cursor: pointer; }
.g-node:focus { outline: none; }
.g-node:focus-visible circle { filter: brightness(1.15); }
.g-node:hover circle { filter: brightness(1.15); }
.g-tip { position: absolute; pointer-events: none; background: var(--s2);
  border: 1px solid var(--line2); border-radius: 6px; padding: 7px 11px;
  font-size: 11px; line-height: 1.6; z-index: 9; opacity: 0; transition: opacity .12s;
  color: var(--ink); transform: translateY(-100%); }

/* 角色介入浮动按钮 */
.iv-fab { position: absolute; right: 16px; top: 12px; font-size: 12px;
  padding: 5px 12px; border-radius: 6px; border: 1px solid var(--line);
  background: var(--s2); color: var(--ink2); cursor: pointer; transition: .12s; z-index: 3; }
.iv-fab:hover { color: var(--primary); border-color: var(--primary); }

/* 关系表（>8 人降级） */
.rel-table-wrap { padding: 48px 20px 20px; overflow: auto; height: 100%; }
.rel-table { width: 100%; max-width: 720px; margin: 0 auto; border-collapse: collapse; font-size: 12.5px; }
.rel-table th { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line2);
  color: var(--faint); font-weight: 600; font-size: 11px; }
.rel-table td { padding: 8px 10px; border-bottom: 1px dashed var(--line); color: var(--ink2); }
.rel-table .bar { display: inline-block; width: 80px; height: 4px; border-radius: 2px; background: var(--s3); position: relative; }
.rel-table .bar i { position: absolute; left: 0; top: 0; bottom: 0; background: var(--sky); border-radius: 2px; }
.rel-table .muted { color: var(--faint); text-align: center; padding: 20px; }

/* 右列：详情 */
.char-detail { border-left: 1px solid var(--line); background: var(--s1); overflow-y: auto;
  padding: 20px 18px; transition: background .25s; }
.cd-head { display: flex; gap: 12px; align-items: center; margin-bottom: 18px;
  padding-bottom: 14px; border-bottom: 1px solid var(--line); }
.cd-head .n { font: 700 19px var(--serif); color: var(--ink); }
.cd-head .r { font-size: 11.5px; color: var(--faint); margin-top: 2px; }
.cd-sec { margin-bottom: 16px; }
.s-t { font-size: 10px; color: var(--faint); letter-spacing: 1.5px; margin-bottom: 8px; }
.muted { color: var(--faint); font-size: 11.5px; }
.tags { display: flex; flex-wrap: wrap; gap: 5px; }
.tag { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 4px;
  border: 1px solid var(--line); color: var(--ink2); background: var(--s2); line-height: 1.5; }
.tag.k { color: var(--accent); border-color: var(--accent); }
.tag.s { color: var(--violet); border-color: var(--violet); }
.tag.g { color: var(--sky); border-color: var(--sky); }
.voice-q { border-left: 2px solid var(--primary); padding: 8px 13px;
  margin: 0; font: italic 13px/1.9 var(--serif); color: var(--ink2); background: var(--s2); border-radius: 0 4px 4px 0; }
.rel-mini { display: flex; flex-direction: column; gap: 4px; }
.rel-mini-row { font-size: 12px; color: var(--ink2); display: flex; gap: 6px; align-items: baseline; }
.rm-target { color: var(--primary); cursor: pointer; font-weight: 600; }
.rm-target:hover { text-decoration: underline; }
.rm-type { color: var(--ink); }
.rm-int { color: var(--faint); font: 10px Menlo, monospace; }
.iv-btn { margin-top: 10px; font-size: 12px; padding: 6px 12px; border-radius: 5px;
  border: 1px solid var(--line); background: var(--s2); color: var(--ink2); cursor: pointer; width: 100%; }
.iv-btn:hover { color: var(--primary); border-color: var(--primary); }

/* 弹窗（与 ParagraphOps .diag/.rw-* 视觉一致，迁移到 scoped .modal 容器） */
.modal-mask { position: fixed; inset: 0; background: rgba(0, 0, 0, .4); z-index: 1000;
  display: flex; align-items: center; justify-content: center; padding: 20px; }
.modal { background: var(--s2); border: 1px solid var(--line2); border-radius: 10px;
  padding: 20px 22px; width: 100%; max-width: 440px; box-shadow: 0 8px 28px rgba(0, 0, 0, .18); }
.iv-modal .d-t { font: 700 15px var(--serif); color: var(--ink); }
.iv-sub { font-size: 11.5px; color: var(--faint); margin-top: 4px; line-height: 1.6; }
.rw-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.rw-chip { font-size: 12px; padding: 3px 10px; border-radius: 4px; border: 1px solid var(--line);
  background: var(--s2); color: var(--ink2); cursor: pointer; transition: .12s; }
.rw-chip.on { border-color: var(--primary); color: var(--primary); background: var(--primary-tint); }
.rw-ta { width: 100%; margin-top: 10px; padding: 8px 10px; border: 1px solid var(--line2);
  border-radius: 6px; background: var(--bg); color: var(--ink); font: 13px/1.6 var(--serif);
  resize: vertical; min-height: 64px; }
.rw-ta:focus { outline: none; border-color: var(--primary); }
.iv-bar { display: flex; gap: 8px; align-items: center; margin-top: 12px; flex-wrap: wrap; }
.ie-hint { font-size: 11px; color: var(--faint); flex: 1; min-width: 120px; }
.ie-ok, .ie-cancel { font-size: 12px; padding: 5px 14px; border-radius: 5px; cursor: pointer;
  border: 1px solid var(--line); transition: .12s; }
.ie-ok { background: var(--primary); color: #fffdf8; border-color: var(--primary); }
.ie-ok:disabled { opacity: .5; cursor: not-allowed; }
.ie-cancel { background: var(--s2); color: var(--ink2); }
.ie-cancel:hover { color: var(--ink); }
</style>
