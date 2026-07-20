<script setup>
// 插件（P6.10 填充：注册插件清单 + 技能结晶）
import EmptyState from '../components/EmptyState.vue'

defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})
</script>

<template>
  <div class="stub">
    <h2>插件</h2>
    <div class="stub-sub">genre × culture × 技能结晶</div>
    <EmptyState icon="puzzle" title="插件视图"
      desc="已注册插件与训练结晶的技能在 P6.10 填充（/api/config.plugins 已就绪）。" />
  </div>
</template>
