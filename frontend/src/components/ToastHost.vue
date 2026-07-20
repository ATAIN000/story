<script setup>
// toast 宿主：挂在 App 根部一次，渲染 useToast 队列（story.html :424-426 #toast）。
import { useToast } from '../composables/useToast'
import AppIcon from './AppIcon.vue'

const { toasts } = useToast()
</script>

<template>
  <div id="toast" role="status" aria-live="polite">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type">
      <AppIcon v-if="t.type === 'err'" name="alert" :size="12" />
      {{ t.message }}
    </div>
  </div>
</template>
