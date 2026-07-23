<script setup>
// 伏笔账（P6.9）：CFPG 三列看板 —— 已种下未到期 / 到期回收中 / 已回收。
// 数据源：project.world.foreshadows（池真值）+ 最新决策卡 activePayoffs（到期标记）。
// B7（伏笔操作介入）未做：操作按钮降级为「记一笔」入口（intent 文本指令，下章决策卡生效）。
// 列宽固定，卡片悬停高亮；空态友好提示。
import { computed, ref } from 'vue'
import { api } from '../api/api'
import { toThreadsVM } from '../api/adapters'
import { useToast } from '../composables/useToast'
import EmptyState from '../components/EmptyState.vue'

const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})
const emit = defineEmits(['refresh'])

const { toast, toastError } = useToast()

const vm = computed(() => toThreadsVM(props.project))

const COLS = computed(() => [
  { key: 'open', name: '已种下 · 未到收时', color: 'var(--sky)', items: vm.value.open },
  { key: 'due', name: '到期 · 该收了', color: 'var(--primary)', items: vm.value.due },
  { key: 'done', name: '已回收', color: 'var(--violet)', items: vm.value.done },
])

/* 「记一笔」入口（B7 伏笔操作降级 → intent 介入） */
const noteTarget = ref(null)   // {id, content}
const noteText = ref('')
const noteBusy = ref(false)

function openNote(item) {
  noteTarget.value = item
  noteText.value = ''
}
function closeNote() { noteTarget.value = null; noteText.value = '' }

async function submitNote() {
  const v = noteText.value.trim()
  if (!v || !noteTarget.value) return
  noteBusy.value = true
  try {
    const r = await api.intervene('intent', {
      constraint: `[伏笔 ${noteTarget.value.id}] ${v}`,
      note_type: '伏笔',
    }, `伏笔账 · ${noteTarget.value.id} 记一笔`)
    if (r.ok !== false) {
      toast(`已记入 — 下章决策卡生效`)
      closeNote()
      emit('refresh')
    } else {
      toastError(`记一笔失败：${r.message || ''}`)
    }
  } catch (e) {
    toastError(`记一笔失败：${e.message}`)
  } finally {
    noteBusy.value = false
  }
}

function fmtWhen(item) {
  if (item.status === 'done' && item.paidAtChapter != null) {
    return `第${item.plantedChapter}章种 → 第${item.paidAtChapter}章收`
  }
  if (item.status === 'due') {
    return `种于第${item.plantedChapter}章${item.overdue ? ' · 老化债' : ' · 本章回收中'}`
  }
  return `种于第${item.plantedChapter}章`
}
</script>

<template>
  <div v-if="!vm.hasAny" class="tv-empty">
    <EmptyState icon="bookmark" title="暂无伏笔"
      desc="生成章节后，Showrunner 会在决策卡里种下伏笔三元组（content/trigger/payoff）进 CFPG 池。这里会按 已种下/到期/已回收 三列记账。" />
  </div>

  <div v-else class="kb-zone">
    <div class="kb-head">
      <h2>伏笔账</h2>
      <span>CFPG 池 · 三列看板 · 进 CFPG 池，系统会盯着回收</span>
    </div>

    <div class="kb">
      <div v-for="col in COLS" :key="col.key" class="kb-col">
        <div class="kc-t">
          <span class="kc-dot" :style="{ background: col.color }"></span>
          {{ col.name }}
          <span class="cnt">{{ col.items.length }}</span>
        </div>

        <div v-if="col.items.length" class="kb-list">
          <div v-for="(item, i) in col.items" :key="`${col.key}-${i}`" class="fs-card"
               :class="{ overdue: item.overdue }"
               :data-testid="`foreshadow-card-${item.id}`">
            <div class="fh">
              <span class="fid" :style="{ color: col.color }">{{ item.id }}</span>
              <span class="fwhen">{{ fmtWhen(item) }}</span>
            </div>
            <div class="fb">{{ item.content }}</div>
            <div v-if="item.trigger" class="fb-meta">触发：{{ item.trigger }}</div>
            <div v-if="item.payoff" class="fb-meta payoff">→ {{ item.payoff }}</div>
            <!-- 操作（B7 未做 → 降级「记一笔」intent 入口） -->
            <div class="fops">
              <button class="mini-btn" data-testid="foreshadow-note" @click="openNote(item)">记一笔</button>
            </div>
          </div>
        </div>

        <div v-else class="kb-col-empty">— 无 —</div>
      </div>
    </div>

    <div class="kb-foot">
      <span class="muted">伏笔操作介入（B7）尚未接入 · 本视图只读 + 记一笔入口（intent 文本指令，下章决策卡生效）</span>
    </div>
  </div>

  <!-- 记一笔弹窗 -->
  <teleport to="body">
    <div v-if="noteTarget" class="modal-mask" @click.self="closeNote" role="dialog"
         aria-modal="true" aria-labelledby="noteTitle">
      <div class="modal">
        <div class="d-t" id="noteTitle">记一笔 · 伏笔 {{ noteTarget.id }}</div>
        <div class="iv-sub">{{ noteTarget.content }}</div>
        <textarea class="rw-ta" rows="3" v-model="noteText"
                  placeholder="例：这条伏笔可压一章再收 / 直接作废 / 改为暗线回收"
                  @keydown.enter.prevent="submitNote"
                  @keydown.esc.prevent="closeNote"></textarea>
        <div class="iv-bar">
          <span class="ie-hint">Enter 确定 · 进作者意图，下章决策卡生效</span>
          <button class="ie-ok" :disabled="!noteText.trim() || noteBusy" @click="submitNote">
            {{ noteBusy ? '提交中…' : '✓ 记账' }}
          </button>
          <button class="ie-cancel" @click="closeNote" :disabled="noteBusy">取消</button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.tv-empty { height: 100%; display: flex; align-items: flex-start; justify-content: center; overflow-y: auto; padding-top: 40px; }

.kb-zone { height: 100%; overflow: auto; padding: 26px 28px 80px; }
.kb-head { display: flex; align-items: baseline; gap: 14px; margin-bottom: 20px; }
.kb-head h2 { font: 700 22px var(--serif); color: var(--ink); }
.kb-head span { font-size: 11.5px; color: var(--faint); }

.kb { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; align-items: start; }
@media (max-width: 900px) { .kb { grid-template-columns: 1fr; } }
.kb-col { background: transparent; }
.kc-t { display: flex; align-items: center; gap: 8px; font: 700 13px var(--serif);
  padding: 2px 4px 10px; border-bottom: 1px solid var(--line); margin-bottom: 12px; color: var(--ink); }
.kc-t .cnt { margin-left: auto; font-size: 11px; color: var(--faint); font-family: Menlo, monospace; }
.kc-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.kb-col-empty { font-size: 12px; color: var(--faint); padding: 10px 4px; text-align: center; }

.fs-card { background: var(--s2); border: 1px solid var(--line); border-radius: 8px;
  padding: 11px 13px; margin-bottom: 10px; transition: border-color .12s; }
.fs-card:hover { border-color: var(--line2); }
.fs-card.overdue { border-left: 3px solid var(--danger); }
.fh { display: flex; gap: 8px; align-items: center; }
.fid { font-family: Menlo, monospace; font-weight: 800; font-size: 12px; }
.fwhen { margin-left: auto; font-size: 10px; color: var(--faint); text-align: right; }
.fb { font-size: 12.5px; color: var(--ink); margin-top: 6px; line-height: 1.7; }
.fb-meta { font-size: 11px; color: var(--ink2); margin-top: 3px; line-height: 1.6; }
.fb-meta.payoff { color: var(--accent); }
.fops { display: flex; gap: 6px; margin-top: 9px; }
.mini-btn { font-size: 11px; padding: 3px 10px; border-radius: 4px;
  border: 1px solid var(--line); color: var(--ink2); background: var(--s2); cursor: pointer; transition: .12s; }
.mini-btn:hover { color: var(--primary); border-color: var(--primary); }

.kb-foot { margin-top: 24px; padding-top: 14px; border-top: 1px dashed var(--line); }
.muted { color: var(--faint); font-size: 11.5px; }

/* 弹窗（与 CharsView 同款） */
.modal-mask { position: fixed; inset: 0; background: rgba(0, 0, 0, .4); z-index: 1000;
  display: flex; align-items: center; justify-content: center; padding: 20px; }
.modal { background: var(--s2); border: 1px solid var(--line2); border-radius: 10px;
  padding: 20px 22px; width: 100%; max-width: 440px; box-shadow: 0 8px 28px rgba(0, 0, 0, .18); }
.d-t { font: 700 15px var(--serif); color: var(--ink); }
.iv-sub { font-size: 11.5px; color: var(--faint); margin-top: 4px; line-height: 1.6; }
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
