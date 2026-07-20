<script setup>
// 手稿（写作台中栏，story.html :476-479 + :653-667）
// 只消费 adapter 的 chapter VM（toChapterVM：paras 已按 P6.3 段落协议切分、
// 标题行不入段）。选中=单选本地态；已读=本地 Set，sessionStorage 记忆不入库。
// 父组件以 :key="chapter.no" 挂载 —— 换章即重建本组件，选中/已读按章隔离。
import { ref, computed } from 'vue'

const props = defineProps({
  chapter: { type: Object, required: true },
  reviewing: { type: Boolean, default: false },
  fsSize: { type: Number, default: 17 },
})

const sel = ref(null)          // 选中段序号（0 基，同段落协议）
const readSet = ref(loadRead())

const storeKey = `storyos.read.ch${props.chapter.no}`
function loadRead() {
  try {
    const arr = JSON.parse(sessionStorage.getItem(`storyos.read.ch${props.chapter.no}`) || '[]')
    return new Set(Array.isArray(arr) ? arr : [])
  } catch { return new Set() }
}

function clickPara(i) {
  sel.value = sel.value === i ? null : i
  const s = new Set(readSet.value)
  s.add(i)
  readSet.value = s
  try { sessionStorage.setItem(storeKey, JSON.stringify([...s])) } catch { /* 写失败忽略 */ }
}

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
    <div v-for="(p, i) in chapter.paras" :key="i" class="para"
         :class="{ sel: sel === i, read: readSet.has(i) }"
         :style="{ fontSize: fsSize + 'px' }"
         tabindex="0" role="button" :aria-pressed="sel === i"
         @click="clickPara(i)" @keydown.enter.prevent="clickPara(i)" @keydown.space.prevent="clickPara(i)">
      <span class="read-mark" aria-hidden="true">✓</span>{{ p }}
    </div>
  </div>
</template>
