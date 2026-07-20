<script setup>
// 时间线（P6.9 填充：事件溯源 + 回滚 + 故事内时间轴）
import EmptyState from '../components/EmptyState.vue'

defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})
</script>

<template>
  <div class="stub">
    <h2>时间线</h2>
    <div class="stub-sub">事件溯源 · 可回滚</div>
    <EmptyState icon="clock" title="时间线视图"
      desc="事件流、快照与回滚操作在 P6.9 填充。" />
  </div>
</template>
