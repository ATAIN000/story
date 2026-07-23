<script setup>
// 手稿（写作台中栏，story.html :476-479 + :653-667）
// 只消费 adapter 的 chapter VM（toChapterVM：paras 已按 P6.3 段落协议切分、
// 标题行不入段）。选中=单选本地态；已读=本地 Set，sessionStorage 记忆不入库。
// 父组件以 :key="chapter.no + '@' + chapter.timestamp" 挂载 —— 换章/换记录即重建本组件，
// 选中/已读按章隔离；存储键带章身份判别（timestamp，空则 tickRange），
// 防回滚后重生成的同号章继承旧记录的已读标记。
//
// P6.7：段落四操作（改字/这不对…/重写这段/记一笔）经 ParagraphOps 组件挂载。
// fab 浮在选中段右上角；改字面板原地替换段文本；其它三面板（重写/记一笔/诊断）
// 插在该段文本之下。介入成功 → emit 给父刷新项目快照（rail 同步）。
import { ref, computed } from 'vue'
import ParagraphOps from './ParagraphOps.vue'

const props = defineProps({
  chapter: { type: Object, required: true },
  reviewing: { type: Boolean, default: false },
  fsSize: { type: Number, default: 17 },
  generating: { type: Boolean, default: false },  // 全局生成锁（禁 fab）
})
const emit = defineEmits(['intervened', 'text-updated'])

const sel = ref(null)          // 选中段序号（0 基，同段落协议）
const storeKey = `storyos.read.ch${props.chapter.no}@${props.chapter.timestamp || props.chapter.tickRange.join('-')}`
const fixedKey = `storyos.fixed.ch${props.chapter.no}@${props.chapter.timestamp || props.chapter.tickRange.join('-')}`
const readSet = ref(loadRead())
const fixedSet = ref(loadFixed())

/* 当前操作面板展开段（同段只挂一种 fab 或面板） */
const opPara = ref(null)       // 当前正在操作的段序号；null=无

function loadRead() {
  try {
    const arr = JSON.parse(sessionStorage.getItem(storeKey) || '[]')
    return new Set(Array.isArray(arr) ? arr : [])
  } catch { return new Set() }
}
function loadFixed() {
  try {
    const arr = JSON.parse(sessionStorage.getItem(fixedKey) || '[]')
    return new Set(Array.isArray(arr) ? arr : [])
  } catch { return new Set() }
}

function clickPara(i) {
  if (opPara.value === i) return   // 该段已在操作中，不重复切
  sel.value = i
  opPara.value = i
  const s = new Set(readSet.value)
  s.add(i)
  readSet.value = s
  try { sessionStorage.setItem(storeKey, JSON.stringify([...s])) } catch { /* 写失败忽略 */ }
}

function onOpsClosed() { opPara.value = null; sel.value = null }

function onFixed(i) {
  const s = new Set(fixedSet.value)
  s.add(i)
  fixedSet.value = s
  try { sessionStorage.setItem(fixedKey, JSON.stringify([...s])) } catch { /* 写失败忽略 */ }
}
function onIntervened() { emit('intervened') }
function onTextUpdated() { emit('text-updated') }

// 章题：后端已给 title；本身以「第N章」开头（actor 路径默认题）则不重复拼
const heading = computed(() =>
  /^第\d+章/.test(props.chapter.title) ? props.chapter.title : `第 ${props.chapter.no} 章 · ${props.chapter.title}`)

const totalChars = computed(() => props.chapter.paras.join('').length)
const MODE_LABEL = { scripted: '剧本通道', llm: 'LLM 成稿', actor: 'Actor 群像' }
const modeLabel = computed(() => MODE_LABEL[props.chapter.generationMode] || props.chapter.llmMode || '')
</script>

<template>
  <div class="manuscript">
    <h2>
      {{ heading }}
      <span v-if="reviewing" class="m-badge">审读中</span>
      <span v-else-if="chapter.rolledBack" class="m-badge rb">已回滚</span>
    </h2>
    <div class="m-sub">
      {{ chapter.paraCount }} 段 · 约 {{ totalChars }} 字 · 已读 {{ readSet.size }}/{{ chapter.paraCount }} 段
      <span class="sys">{{ modeLabel }} · tick {{ chapter.tickRange[0] }}–{{ chapter.tickRange[1] }}</span>
    </div>
    <div v-for="(p, i) in chapter.paras" :key="i" class="para-block">
      <div class="para"
           :class="{ sel: sel === i && opPara !== i, read: readSet.has(i) }"
           :style="{ fontSize: fsSize + 'px' }"
           :data-testid="`paragraph-${i}`"
           tabindex="0" role="button" :aria-pressed="sel === i"
           @click="opPara === i ? null : clickPara(i)"
           @keydown.enter.prevent="clickPara(i)" @keydown.space.prevent="clickPara(i)">
        <span class="read-mark" aria-hidden="true">✓</span>

        <!-- 段落文本：操作中由 ParagraphOps 接管（fab + 面板 + 文本/textarea）；
             非操作中正常显示（含 fixed 下划线标记） -->
        <template v-if="opPara === i">
          <ParagraphOps :chapter="chapter" :para-index="i" :text="p"
                        :fixed-set="fixedSet"
                        @closed="onOpsClosed"
                        @fixed="onFixed" @intervened="onIntervened"
                        @text-updated="onTextUpdated" />
        </template>
        <span v-else-if="fixedSet.has(i)" class="fixed">{{ p }}</span>
        <template v-else>{{ p }}</template>
      </div>
    </div>
  </div>
</template>
