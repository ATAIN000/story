<script setup>
// 空态组件（评审 8.3-#1：零章冷启动第一屏 —— 无章节/无介入/无伏笔/无人物时
// 的缺省展示 + 引导动作；story.html 无对应物，按 editorial 风新设 .empty-state）。
import AppIcon from './AppIcon.vue'

defineProps({
  icon: { type: String, default: 'feather' },
  title: { type: String, required: true },
  desc: { type: String, default: '' },
})
</script>

<template>
  <div class="empty-state">
    <span class="es-ic"><AppIcon :name="icon" :size="30" /></span>
    <div class="es-t">{{ title }}</div>
    <div v-if="desc" class="es-d">{{ desc }}</div>
    <div v-if="$slots.default" class="es-act"><slot /></div>
  </div>
</template>
