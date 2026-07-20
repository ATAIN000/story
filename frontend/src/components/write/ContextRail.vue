<script setup>
// 情境栏（P6.7 rail，story.html :882-911）：三区
//   1. 介入流：GET /api/interventions → flow-item 列表（类型色 + tick + 内容摘要）
//   2. 训练信号：GET /api/training/stats → 三计数（skills/preferences/style）
//   3. 本章关联：决策卡 active_payoffs（到期回收）+ new_foreshadows（本章种下）+ pool_stats
//
// 只消费 adapter VM（toInterventionVM / toTrainingStatsVM / toChapterContextVM）。
// 介入流与训练信号由父组件按节奏刷新（介入后/切章时拉取），不在本组件内自轮询。
import { computed } from 'vue'
import AppIcon from '../AppIcon.vue'
import { toInterventionVM, toTrainingStatsVM, toChapterContextVM } from '../../api/adapters'

const props = defineProps({
  interventions: { type: Array, default: () => [] },   // 原始事件数组（GET /api/interventions）
  trainingStats: { type: Object, default: null },      // 原始 stats（GET /api/training/stats）
  chapter: { type: Object, default: null },            // chapter VM（activeChapter）
})

/* 介入类型 → 类型色（spec addFlow 色表） */
const IV_COLOR = {
  textual: 'var(--suspect)',
  structural: 'var(--sky)',
  character: 'var(--violet)',
  intent: 'var(--sky)',
  evaluation: 'var(--sky)',
}

const flow = computed(() =>
  (props.interventions || []).map(toInterventionVM).filter(Boolean))
const stats = computed(() => toTrainingStatsVM(props.trainingStats))
const ctx = computed(() => toChapterContextVM(props.chapter))

function ivColor(t) { return IV_COLOR[t] || 'var(--faint)' }
</script>

<template>
  <!-- 1. 介入流 -->
  <div class="rail-sec">
    <div class="rail-t">介入流 · 你的每个动作都存档</div>
    <div v-if="flow.length">
      <div v-for="iv in flow" :key="iv.id" class="flow-item">
        <div class="fh">
          <span class="ft" :style="{ color: ivColor(iv.ivType) }">{{ iv.ivLabel }}</span>
          <span class="fm">tick {{ iv.tick }}</span>
        </div>
        <div class="fb">{{ iv.body }}</div>
      </div>
    </div>
    <div v-else class="flow-empty">
      还没有介入。改字 / 记一笔 / 重写 / 诊断任意操作都会出现在这里。
    </div>
  </div>

  <!-- 2. 训练信号 -->
  <div class="rail-sec">
    <div class="rail-t">训练信号</div>
    <div class="mini-stat">
      <span><AppIcon name="puzzle" :size="13" /> 技能结晶</span>
      <b>{{ stats?.skills ?? 0 }}</b>
    </div>
    <div class="mini-stat">
      <span><AppIcon name="scale" :size="13" /> 偏好数据</span>
      <b>{{ stats?.preferences ?? 0 }}</b>
    </div>
    <div class="mini-stat">
      <span><AppIcon name="feather" :size="13" /> 文风样本</span>
      <b>{{ stats?.style ?? 0 }}</b>
    </div>
  </div>

  <!-- 3. 本章关联（CFPG） -->
  <div class="rail-sec">
    <div class="rail-t">本章关联</div>
    <template v-if="ctx">
      <!-- 3a. 到期回收中（CFPG due_payoffs） -->
      <div v-if="ctx.payoffs.length" class="ctx-row">
        <b>回收中（{{ ctx.payoffs.length }}）</b>
        <div v-for="(p, i) in ctx.payoffs" :key="i"
             class="ctx-fs" :class="{ overdue: p.overdue }">
          <span v-if="p.overdue" style="color:var(--danger);font-weight:600">[逾期]</span>
          {{ p.content }}
          <span v-if="p.payoff" style="color:var(--accent)">→ {{ p.payoff }}</span>
          <span v-if="p.plantedChapter" style="color:var(--faint)">（第{{ p.plantedChapter }}章种）</span>
        </div>
      </div>
      <div v-else class="ctx-empty">无到期伏笔。</div>

      <!-- 3b. 本章种下 -->
      <div v-if="ctx.newSeeds.length" class="ctx-row" style="margin-top:8px">
        <b>本章种下（{{ ctx.newSeeds.length }}）</b>
        <div v-for="(f, i) in ctx.newSeeds" :key="i" class="ctx-fs">
          {{ f.content }}
          <span v-if="f.payoff" style="color:var(--accent)">→ {{ f.payoff }}</span>
        </div>
      </div>
      <div v-else-if="!ctx.plantedCount" class="ctx-empty">本章未种新伏笔。</div>

      <!-- 3c. 池状态 -->
      <div v-if="ctx.pool && (ctx.pool.active || ctx.pool.overdue || ctx.pool.queued)"
           class="ctx-row" style="margin-top:8px">
        <b>伏笔池</b>
        <span style="color:var(--ink2)">
          活跃 {{ ctx.pool.active ?? 0 }} · 逾期 {{ ctx.pool.overdue ?? 0 }} · 排队 {{ ctx.pool.queued ?? 0 }}
        </span>
      </div>
    </template>
    <div v-else class="ctx-empty">无选中章节。</div>
  </div>
</template>
