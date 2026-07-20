<script setup>
// 内联 SVG 图标（currentColor，图标库本体在 icons.js）
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
