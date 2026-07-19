<script setup>
// 渲染带 ⟪v⟫违规⟪/v⟫ / ⟪f⟫修正⟪/f⟫ 标记的故事文本
import { computed } from 'vue'

const props = defineProps({ text: { type: String, required: true } })

const segments = computed(() => {
  const out = []
  const re = /⟪(v|f)⟫([\s\S]*?)⟪\/\1⟫/g
  let last = 0, m
  while ((m = re.exec(props.text)) !== null) {
    if (m.index > last) out.push({ kind: 'plain', text: props.text.slice(last, m.index) })
    out.push({ kind: m[1] === 'v' ? 'violation' : 'fixed', text: m[2] })
    last = re.lastIndex
  }
  if (last < props.text.length) out.push({ kind: 'plain', text: props.text.slice(last) })
  return out
})
</script>

<template>
  <span>
    <template v-for="(seg, i) in segments" :key="i">
      <mark v-if="seg.kind === 'violation'" class="mark-violation" title="违规片段">{{ seg.text }}</mark>
      <mark v-else-if="seg.kind === 'fixed'" class="mark-fixed" title="修正片段">{{ seg.text }}</mark>
      <span v-else>{{ seg.text }}</span>
    </template>
  </span>
</template>
