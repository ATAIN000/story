<script setup>
// 写作台（P6.6 填充：binder 章节列表 + 手稿段落操作 + 情境栏）
import EmptyState from '../components/EmptyState.vue'

defineProps({
  project: { type: Object, default: null },
})
</script>

<template>
  <div class="stub">
    <h2>写作台</h2>
    <div class="stub-sub">看方案 → 等生成 → 审读 → 提交归档</div>
    <EmptyState icon="pen" title="暂无章节"
      desc="新项目从第 1 章开始。生成第一稿后，在这里逐段审读、改字、重写。"
      v-if="!project || !project.chapters.length" />
    <EmptyState v-else icon="pen" :title="`已有 ${project.chapters.length} 章`"
      desc="写作台在 P6.6 填充：章节列表、手稿段落操作、生成控制台。" />
  </div>
</template>
