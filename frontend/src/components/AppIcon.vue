<script setup>
// 内联 SVG 图标（currentColor，图标库本体在 icons.js）
// v-html 安全口径：paths 仅限本地静态库（icons.js 手写常量），不接受任何
// 外部输入/用户数据——name 只作 ICONS 查表键，查不到即空串。
import { computed } from 'vue'
import { ICONS } from './icons'

const props = defineProps({
  name: { type: String, required: true },
  size: { type: Number, default: 15 },
})

const paths = computed(() => ICONS[props.name] || '')
</script>

<template>
  <svg class="ico" :width="size" :height="size" viewBox="0 0 24 24" fill="none"
       stroke="currentColor" stroke-width="2" stroke-linecap="round"
       stroke-linejoin="round" aria-hidden="true" v-html="paths"></svg>
</template>
