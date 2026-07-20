<script setup>
// 设置（P6.10 填充：LLM 配置 / 题材 meta / 训练信号）
import EmptyState from '../components/EmptyState.vue'

defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})
</script>

<template>
  <div class="stub">
    <h2>设置</h2>
    <div class="stub-sub">LLM 连接 · 题材 · 训练信号</div>
    <EmptyState icon="sliders" title="设置视图"
      desc="LLM 配置、题材参数与训练统计在 P6.10 填充（/api/training/stats 已就绪）。" />
  </div>
</template>
