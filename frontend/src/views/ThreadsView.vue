<script setup>
// 伏笔账（P6.10 填充：CFPG 三元组看板 —— 种下/待收/已收）
import EmptyState from '../components/EmptyState.vue'

defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})
</script>

<template>
  <div class="stub">
    <h2>伏笔账</h2>
    <div class="stub-sub">伏笔进 CFPG 池，系统会盯着回收</div>
    <EmptyState icon="bookmark" title="暂无伏笔"
      desc="伏笔三元组看板在 P6.10 填充；生成章节后这里会自动记账。" />
  </div>
</template>
