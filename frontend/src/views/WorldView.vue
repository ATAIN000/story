<script setup>
// 世界观（P6.8 填充：分类条目 + 世界状态四层）
import EmptyState from '../components/EmptyState.vue'

defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})
</script>

<template>
  <div class="stub">
    <h2>世界观</h2>
    <div class="stub-sub">物理层 · 关系层 · 心智层 · 叙事层</div>
    <EmptyState icon="map" title="世界观视图"
      desc="世界状态四层结构与条目详情在 P6.8 填充。" />
  </div>
</template>
