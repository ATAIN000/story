<script setup>
// 人物（P6.7 填充：角色列表 + 关系图谱 + 角色卡）
import EmptyState from '../components/EmptyState.vue'

defineProps({
  project: { type: Object, default: null },
})
</script>

<template>
  <div class="stub">
    <h2>人物</h2>
    <div class="stub-sub">他知道什么 · 他这时候不该知道</div>
    <EmptyState icon="users" title="人物视图"
      desc="角色卡、关系图谱与心智投影在 P6.7 填充（/api/characters 已就绪）。" />
  </div>
</template>
