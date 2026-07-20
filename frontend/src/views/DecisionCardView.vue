<script setup>
// 决策卡视图（P6.8）—— editorial 设计语言重做。
// 展示 Showrunner 10 步决策卡的全部 P3.3+ 字段：
//   Step 0 节奏量化 pacing / Step 1 HTN plan_goals / Step 2 轨道调度 /
//   Step 3 CFPG active_payoffs / Step 4 Sternberg 错峰 / Step 5 分形 beat /
//   Step 6 concreteness_curve / Step 7 McKee gaps / Step 8 Snyder 覆盖 /
//   Step 9 pool_stats + queued_foreshadows / Step 10 theme_touch
// 数据源：project.chapters[].card（adapter toCardVM 已铺好全字段 camelCase）。
// 章节选择器：默认最新未回滚章；旧数据章（缺字段）整区 v-if 隐藏不崩。
import { ref, computed, watch } from 'vue'
import EmptyState from '../components/EmptyState.vue'

const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})

/* ---- 章节解析：同 WriteView 口径 —— 同号多记录取最新未回滚 ---- */
const chapters = computed(() =>
  (props.project?.chapters ?? []).slice().sort((a, b) => a.no - b.no))
function resolveChapter(no) {
  if (no == null) return null
  const alive = chapters.value.filter(c => c.no === no && !c.rolledBack)
  return alive.at(-1) ?? chapters.value.find(c => c.no === no) ?? null
}

/* 有决策卡的章（card 非空），用于选择器候选 */
const cardChapters = computed(() =>
  chapters.value.filter(c => c.card).map(c => ({ no: c.no, title: c.title, rolledBack: c.rolledBack })))

const selectedNo = ref(null)
watch(() => props.project, (p) => {
  if (!p) return
  /* 默认最新未回滚且有决策卡的章 */
  if (selectedNo.value == null || !cardChapters.value.some(c => c.no === selectedNo.value)) {
    const alive = cardChapters.value.filter(c => !c.rolledBack)
    selectedNo.value = (alive.at(-1) ?? cardChapters.value.at(-1))?.no ?? null
  }
}, { immediate: true })

const chapter = computed(() => resolveChapter(selectedNo.value))
const card = computed(() => chapter.value?.card ?? null)

/* ---- 显示常量 ---- */
const STERNBERG_NAME = { suspense: '悬念', curiosity: '好奇', surprise: '惊奇' }
const PHASE_NAME = {
  equilibrium: '平衡', disruption: '扰动', recognition: '识别',
  repair: '修复', new_equilibrium: '新平衡',
}
const HOOK_STYLE_COLOR = {   /* 评书扣子类型 → 主题色 */
  明扣: 'var(--primary)',
  暗扣: 'var(--violet)',
  留扣: 'var(--sky)',
  拴马扣: 'var(--danger)',
}
const PACING_LABEL = {
  reversal_density: '反转密度',
  avg_reversal_magnitude: '平均反转幅度',
  pacing_consistency: '节奏一致性',
  cliffhanger_strength: '钩子强度',
}
/* 轨道状态判定（advance / seed / midTouch / dormant） */
function trackState(id, c) {
  if (!c) return 'dormant'
  if (c.advance?.includes(id)) return 'advance'
  if (c.seed?.includes(id)) return 'seed'
  if (c.midTouch?.includes(id)) return 'mid_touch'
  return 'dormant'
}
const TRACK_STATE_LABEL = { advance: '推进', seed: '种子', mid_touch: '触碰', dormant: '休眠' }
const TRACK_STATE_COLOR = {
  advance: 'var(--accent)',
  seed: 'var(--sky)',
  mid_touch: 'var(--primary)',
  dormant: 'var(--faint)',
}

function trackName(id) {
  return card.value?.trackNames?.[id] || id
}
function concretenessAt(i) {
  /* concretenessCurve 是与 beats 同序的数组（adapter 透传 Step 6 CONCOCT）；
   * beat 自带 concreteness 字段时优先（向前兼容），否则查 curve[i] */
  const beat = card.value?.beats?.[i]
  if (beat && typeof beat.concreteness === 'number') return beat.concreteness
  const cv = card.value?.concretenessCurve
  return Array.isArray(cv) && cv[i] != null ? cv[i] : null
}

/* Snyder 覆盖键序化（旧数据可能空对象） */
const snyderEntries = computed(() => Object.entries(card.value?.snyder ?? {}))

/* McKee gap 列表防御 */
const gaps = computed(() => card.value?.gaps ?? [])

/* P3.3+ 节奏区整体可见性：pacing !== undefined 才出（旧数据无字段整区隐藏） */
const showPacing = computed(() => card.value?.pacing !== undefined)
/* plan_goals / creative_seeds 区可见性 */
const planGoals = computed(() => card.value?.planGoals ?? [])
const creativeSeeds = computed(() => card.value?.creativeSeeds ?? [])
const showExtraRow = computed(() =>
  showPacing.value || planGoals.value.length || creativeSeeds.value.length)

/* 旧数据预警：决策卡存在但所有 P3.3+ 新字段都缺（pacing undefined 且无 plan_goals/creative_seeds/concreteness_curve） */
const isLegacyCard = computed(() => {
  const c = card.value
  if (!c) return false
  return c.pacing === undefined
    && !planGoals.value.length
    && !creativeSeeds.value.length
    && !(c.beats ?? []).some(b => typeof b.concreteness === 'number' || b.primitives?.length || b.macro_phase)
})

function selectNo(no) { selectedNo.value = no }
</script>

<template>
  <!-- 无决策卡：空态 -->
  <div v-if="!cardChapters.length" class="dc-empty">
    <EmptyState icon="bookmark" title="还没有决策卡"
      desc="Showrunner 在「写作台」生成下一章方案时会产出决策卡（轨道调度 + 节拍 + 钩子 + Snyder 覆盖等 10 步产物）。批准第一章方案后，这里能看到完整决策卡。" />
  </div>

  <div v-else class="dc">
    <!-- 章节选择器：横排按钮，灰显已回滚章 -->
    <div class="dc-tabs" role="tablist" aria-label="选择章节决策卡">
      <button v-for="c in cardChapters" :key="c.no" role="tab"
              :aria-selected="c.no === selectedNo"
              class="dc-tab" :class="{ active: c.no === selectedNo, rb: c.rolledBack }"
              @click="selectNo(c.no)">
        第{{ c.no }}章<span class="dc-tab-t">{{ c.title }}</span>
      </button>
    </div>

    <div v-if="card" class="dc-body">
      <!-- 旧数据提示（不阻断，只标注缺哪些字段） -->
      <div v-if="isLegacyCard" class="dc-legacy" role="note">
        本章为旧版持久化数据，缺少 P3.3+ 新增字段（pacing / HTN goals / 创意种子 / beat primitives 与 concreteness）。基础轨道调度与节拍仍可查看。
      </div>

      <!-- ===== 第一行：轨道调度（Step 2）+ Sternberg 错峰（Step 4） ===== -->
      <section class="dc-card">
        <div class="dc-card-h">
          <h3>轨道调度</h3>
          <span class="dc-step">Step 2</span>
          <span class="dc-hint">推进 / 种子 / 触碰 / 休眠 — 多线状态外部化</span>
        </div>
        <div class="dc-tracks">
          <div v-for="st in ['advance','seed','mid_touch','dormant']" :key="st" class="dc-track-group">
            <div class="dc-track-label" :style="{ color: TRACK_STATE_COLOR[st] }">{{ TRACK_STATE_LABEL[st] }}</div>
            <div class="dc-track-items">
              <span v-for="id in (card[st === 'mid_touch' ? 'midTouch' : st] || [])" :key="id"
                    class="dc-track-chip" :style="{ borderColor: TRACK_STATE_COLOR[st], color: TRACK_STATE_COLOR[st] }">
                <span class="dc-track-id">{{ id }}</span>{{ trackName(id) }}
                <span v-if="card.sternberg?.[id]" class="dc-sternberg">{{ STERNBERG_NAME[card.sternberg[id]] || card.sternberg[id] }}</span>
              </span>
              <span v-if="!(card[st === 'mid_touch' ? 'midTouch' : st] || []).length" class="dc-track-empty">—</span>
            </div>
          </div>
        </div>
        <div class="dc-card-foot">
          <span class="dc-note">Sternberg 三主因错峰（Step 4）：同集不同模式 · 同轨道连续两集不同</span>
        </div>
      </section>

      <!-- ===== 第二行：集末钩子 + 情感弧 + 主题 touch ===== -->
      <div class="dc-grid-2">
        <section v-if="card.endingHook" class="dc-card">
          <div class="dc-card-h">
            <h3>集末钩子</h3>
            <span class="dc-step">补充 · 评书扣子</span>
          </div>
          <div class="dc-hook">
            <span class="dc-hook-style"
                  :style="{ color: HOOK_STYLE_COLOR[card.endingHook.style] || 'var(--ink2)', borderColor: HOOK_STYLE_COLOR[card.endingHook.style] || 'var(--line)' }">
              {{ card.endingHook.style || '—' }}
            </span>
            <div class="dc-hook-body">
              <div class="dc-hook-desc">{{ card.endingHook.desc || '—' }}</div>
              <div v-if="card.endingHook.periodic" class="dc-hook-meta">周期约束：{{ card.endingHook.periodic }}</div>
            </div>
          </div>
        </section>

        <section class="dc-card">
          <div class="dc-card-h">
            <h3>情感弧目标</h3>
            <span class="dc-step">补充 · Reagan 6 弧</span>
          </div>
          <div class="dc-arc">{{ card.targetArc || '—' }}</div>
          <div class="dc-theme-touch">
            主题 touch（Step 10）：
            <span :class="card.themeTouch ? 'ok' : 'no'">{{ card.themeTouch ? '✓ 已触碰北极星轨道' : '✗ 未触碰' }}</span>
          </div>
        </section>
      </div>

      <!-- ===== 第三行：Beat 规划（Step 5 + Step 1 primitives + Step 6 concreteness + tension） ===== -->
      <section v-if="card.beats?.length" class="dc-card">
        <div class="dc-card-h">
          <h3>Beat 规划</h3>
          <span class="dc-step">Step 5 · 分形 beat（幕级 × 章级）</span>
          <span class="dc-hint">primitives = Step 1 HTN 原语 · 具体度 = Step 6 CONCOCT · tension 张力条</span>
        </div>
        <div class="dc-beats">
          <div v-for="(b, i) in card.beats" :key="b.beat_id ?? i" class="dc-beat">
            <div class="dc-beat-h">
              <span class="dc-beat-id">{{ b.beat_id ?? `b${i + 1}` }}</span>
              <span v-if="b.phase" class="dc-beat-phase">{{ PHASE_NAME[b.phase] || b.phase }}</span>
            </div>
            <div class="dc-beat-track">
              <span class="dc-beat-id-label">{{ b.track || '—' }}</span>
              <span class="dc-beat-track-name">{{ b.track_name || trackName(b.track) }}</span>
            </div>
            <div v-if="b.macro_phase" class="dc-beat-macro">
              幕级：{{ PHASE_NAME[b.macro_phase] || b.macro_phase }}
            </div>
            <!-- tension 张力条（旧数据无则不显示） -->
            <div v-if="typeof b.tension === 'number'" class="dc-bar-row">
              <span class="dc-bar-label">张力</span>
              <div class="dc-bar"><i :style="{ width: Math.round(b.tension * 100) + '%' }"></i></div>
              <span class="dc-bar-val">{{ b.tension.toFixed(2) }}</span>
            </div>
            <!-- Step 6 CONCOCT 具体度（旧数据无则不显示） -->
            <div v-if="concretenessAt(i) != null" class="dc-bar-row">
              <span class="dc-bar-label">具体度</span>
              <div class="dc-bar dc-bar-sky"><i :style="{ width: Math.round(concretenessAt(i) * 100) + '%' }"></i></div>
              <span class="dc-bar-val">{{ concretenessAt(i).toFixed(2) }}</span>
            </div>
            <!-- Step 1 HTN primitives -->
            <div v-if="b.primitives?.length" class="dc-beat-prims">
              <span v-for="(p, pi) in b.primitives" :key="pi" class="dc-prim">{{ p }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- ===== 第四行：Snyder 覆盖（Step 8） ===== -->
      <section v-if="snyderEntries.length" class="dc-card">
        <div class="dc-card-h">
          <h3>Snyder 15 拍覆盖</h3>
          <span class="dc-step">Step 8</span>
        </div>
        <div class="dc-snyder">
          <span v-for="([name, ok], i) in snyderEntries" :key="i"
                class="dc-snyder-chip" :class="{ ok, no: !ok }">
            {{ ok ? '✓' : '·' }} {{ name }}
          </span>
        </div>
      </section>

      <!-- ===== 第五行：CFPG（Step 3 到期 + Step 9 池 + Step 7 gap） ===== -->
      <div class="dc-grid-2">
        <section class="dc-card">
          <div class="dc-card-h">
            <h3>到期伏笔</h3>
            <span class="dc-step">Step 3 · CFPG 查询</span>
          </div>
          <div v-if="card.activePayoffs?.length" class="dc-payoffs">
            <div v-for="(p, i) in card.activePayoffs" :key="i" class="dc-payoff" :class="{ overdue: p.overdue }">
              <span class="dc-fs-id">{{ p.id }}</span>
              <span class="dc-fs-content">{{ p.content }}</span>
              <span v-if="p.payoff" class="dc-fs-payoff">→ {{ p.payoff }}</span>
              <span v-if="p.overdue" class="dc-fs-overdue">[逾期]</span>
              <span v-else-if="p.plantedChapter" class="dc-fs-planted">（第{{ p.plantedChapter }}章种）</span>
            </div>
          </div>
          <div v-else class="dc-empty-line">本章无到期伏笔。</div>

          <!-- McKee Gap（Step 7） -->
          <div v-if="gaps.length" class="dc-gap">
            <div class="dc-card-sub-h">McKee Gap · Step 7 预期违反</div>
            <div v-for="(g, i) in gaps" :key="i" class="dc-gap-item">◇ {{ g }}</div>
          </div>
        </section>

        <section v-if="card.poolStats && (card.poolStats.active || card.poolStats.overdue || card.poolStats.queued)"
                 class="dc-card">
          <div class="dc-card-h">
            <h3>伏笔池</h3>
            <span class="dc-step">Step 9 · CFPG 池更新</span>
          </div>
          <div class="dc-pool-stats">
            <div class="dc-pool-stat">
              <div class="dc-pool-num">{{ card.poolStats.active ?? 0 }}</div>
              <div class="dc-pool-label">未回收</div>
            </div>
            <div class="dc-pool-stat">
              <div class="dc-pool-num danger">{{ card.poolStats.overdue ?? 0 }}</div>
              <div class="dc-pool-label">老化债</div>
            </div>
            <div class="dc-pool-stat">
              <div class="dc-pool-num sky">{{ card.poolStats.queued ?? 0 }}</div>
              <div class="dc-pool-label">排队</div>
            </div>
          </div>
          <div v-if="card.queuedForeshadows?.length" class="dc-pool-queued">
            <div class="dc-card-sub-h">满池排队（待容量释放后种下）</div>
            <div v-for="(q, i) in card.queuedForeshadows" :key="i" class="dc-pool-q-item">
              <span class="dc-fs-id sky">{{ q.track }}</span>
              <span>{{ q.content }}</span>
              <span v-if="q.payoff" class="dc-fs-payoff">→ {{ q.payoff }}</span>
            </div>
          </div>
        </section>
      </div>

      <!-- ===== 第六行：P3.3+ 新增字段（pacing / plan_goals / creative_seeds；旧数据整区隐藏） ===== -->
      <div v-if="showExtraRow" class="dc-grid-2">
        <section v-if="showPacing" class="dc-card">
          <div class="dc-card-h">
            <h3>节奏量化</h3>
            <span class="dc-step">Step 0 · 上章实测 → 本章修正</span>
          </div>
          <template v-if="card.pacing">
            <div class="dc-pacing-meta">基于第 {{ card.pacing.measured_episode ?? '?' }} 章事件流实测</div>
            <div class="dc-pacing-grid">
              <div v-for="(label, key) in PACING_LABEL" :key="key" class="dc-pacing-cell">
                <div class="dc-pacing-label">{{ label }}</div>
                <div class="dc-pacing-val">{{ card.pacing.score?.[key]?.toFixed(2) ?? '—' }}</div>
              </div>
            </div>
          </template>
          <div v-else class="dc-empty-line">首章无历史：上一章节奏数据不存在，本章不做 tension 修正。</div>
        </section>

        <section v-if="planGoals.length || creativeSeeds.length" class="dc-card">
          <div v-if="planGoals.length" class="dc-extra">
            <div class="dc-card-sub-h">HTN 规划目标 · Step 1 NarrativePlanner</div>
            <div v-for="(g, i) in planGoals" :key="i" class="dc-goal">
              <span class="dc-goal-holder">{{ g.holder }}</span>
              <span class="dc-goal-desc">{{ g.desc }}</span>
              <span v-if="g.status" class="dc-goal-status">{{ g.status }}</span>
            </div>
          </div>
          <div v-if="creativeSeeds.length" class="dc-extra">
            <div class="dc-card-sub-h">可选灵感 · P3.7 ConceptualBlending</div>
            <div v-for="(s, i) in creativeSeeds" :key="i" class="dc-seed">
              <div v-if="s.domains?.length" class="dc-seed-domains">{{ s.domains.join(' × ') }}</div>
              <div class="dc-seed-text">{{ s.emergent }}</div>
              <div v-if="s.novelty != null || s.surprise != null" class="dc-seed-meta">
                新颖度 {{ s.novelty?.toFixed(2) ?? '—' }} · 意外度 {{ s.surprise?.toFixed(2) ?? '—' }}
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 组件作用域样式：决策卡专属类（dc-*），复用 theme.css 全局变量与基础组件类。
 * editorial 设计语言：serif 标题 + sans 正文 + 主色调描边卡片 + 标签 chip；
 * 不使用 Tailwind，颜色全走 CSS 变量以支持双主题。 */
.dc { padding: 22px 34px 80px; max-width: 960px; margin: 0 auto; }
.dc-empty { height: 100%; display: flex; align-items: flex-start; justify-content: center; overflow-y: auto; }

/* 章节选择器（横排标签） */
.dc-tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 20px; }
.dc-tab {
  padding: 6px 13px; border-radius: 6px; font-size: 12.5px; color: var(--ink2);
  border: 1px solid var(--line); background: var(--s2); transition: .12s;
}
.dc-tab:hover { border-color: var(--primary); color: var(--primary); }
.dc-tab.active { border-color: var(--primary); color: var(--primary); background: var(--primary-tint); font-weight: 600; }
.dc-tab.rb { opacity: .5; }
.dc-tab-t { margin-left: 6px; font-size: 11px; opacity: .75; }

/* 旧数据提示 */
.dc-legacy {
  margin-bottom: 16px; padding: 10px 14px; border-left: 2px solid var(--faint);
  background: var(--s2); border-radius: 0 6px 6px 0;
  font-size: 12px; color: var(--ink2); line-height: 1.7;
}

/* 卡片基础 */
.dc-body { display: flex; flex-direction: column; gap: 16px; }
.dc-card {
  border: 1px solid var(--line); border-radius: 10px; background: var(--s2);
  padding: 16px 18px; transition: border-color .12s;
}
.dc-card-h { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.dc-card-h h3 { font: 700 16px var(--serif); color: var(--ink); }
.dc-step {
  font: 10px Menlo, monospace; color: var(--faint);
  padding: 1px 7px; border: 1px solid var(--line); border-radius: 4px;
}
.dc-hint { margin-left: auto; font-size: 11px; color: var(--faint); }
.dc-card-foot { margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--line); }
.dc-note { font-size: 11px; color: var(--faint); }
.dc-card-sub-h { font-size: 11px; color: var(--faint); margin: 14px 0 8px; padding-top: 10px; border-top: 1px dashed var(--line); }
.dc-empty-line { font-size: 12px; color: var(--faint); line-height: 1.7; padding: 2px 0; }

/* 双列布局 */
.dc-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 880px) { .dc-grid-2 { grid-template-columns: 1fr; } }

/* 轨道调度：按状态分组渲染 */
.dc-tracks { display: flex; flex-direction: column; gap: 10px; }
.dc-track-group { display: grid; grid-template-columns: 56px 1fr; gap: 12px; align-items: start; }
.dc-track-label { font-size: 12px; font-weight: 600; padding-top: 4px; }
.dc-track-items { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.dc-track-chip {
  display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
  padding: 3px 10px; border-radius: 5px; border: 1px solid var(--line);
  background: var(--bg); color: var(--ink2);
}
.dc-track-id { font: 600 11px Menlo, monospace; opacity: .85; }
.dc-sternberg {
  font-size: 10px; padding: 1px 6px; border-radius: 3px;
  background: var(--violet); color: #fffdf8;
}
.dc-track-empty { font-size: 11px; color: var(--faint); padding: 4px 0; }

/* 钩子 */
.dc-hook { display: flex; gap: 14px; align-items: flex-start; }
.dc-hook-style {
  flex-shrink: 0; font: 700 14px var(--serif); padding: 4px 12px; border-radius: 6px;
  border: 1px solid var(--line);
}
.dc-hook-body { flex: 1; }
.dc-hook-desc { font-size: 13px; color: var(--ink); line-height: 1.7; }
.dc-hook-meta { font-size: 11px; color: var(--faint); margin-top: 4px; }

/* 情感弧 */
.dc-arc { font: 600 16px Menlo, monospace; color: var(--accent); }
.dc-theme-touch { margin-top: 10px; font-size: 11.5px; color: var(--ink2); }
.dc-theme-touch .ok { color: var(--accent); }
.dc-theme-touch .no { color: var(--faint); }

/* Beat 规划 */
.dc-beats { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
.dc-beat {
  border: 1px solid var(--line); border-radius: 8px; background: var(--bg);
  padding: 10px 12px;
}
.dc-beat-h { display: flex; justify-content: space-between; align-items: center; }
.dc-beat-id { font: 10px Menlo, monospace; color: var(--faint); }
.dc-beat-phase {
  font-size: 10px; padding: 1px 6px; border-radius: 3px;
  background: var(--s3); color: var(--ink2);
}
.dc-beat-track { margin-top: 6px; font-size: 12px; color: var(--ink2); display: flex; gap: 6px; }
.dc-beat-id-label { font-family: Menlo, monospace; font-weight: 600; }
.dc-beat-track-name { color: var(--ink); }
.dc-beat-macro { margin-top: 4px; font-size: 10.5px; color: var(--faint); }
.dc-bar-row { display: flex; align-items: center; gap: 6px; margin-top: 6px; }
.dc-bar-label { font-size: 10px; color: var(--faint); width: 36px; flex-shrink: 0; }
.dc-bar { flex: 1; height: 4px; border-radius: 2px; background: var(--s3); overflow: hidden; }
.dc-bar i { display: block; height: 100%; width: 0; background: var(--primary); transition: width .2s; }
.dc-bar-sky i { background: var(--sky); }
.dc-bar-val { font: 10px Menlo, monospace; color: var(--faint); width: 30px; text-align: right; }
.dc-beat-prims { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }
.dc-prim {
  font: 10px Menlo, monospace; padding: 1px 6px; border-radius: 3px;
  background: var(--s3); color: var(--ink2);
}

/* Snyder 覆盖 */
.dc-snyder { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 6px; }
.dc-snyder-chip {
  font-size: 11.5px; padding: 4px 8px; border-radius: 4px; text-align: center;
  background: var(--bg);
}
.dc-snyder-chip.ok { color: var(--accent); border: 1px solid var(--accent); }
.dc-snyder-chip.no { color: var(--faint); border: 1px solid var(--line); }

/* CFPG 到期 */
.dc-payoffs { display: flex; flex-direction: column; gap: 6px; }
.dc-payoff {
  font-size: 12px; line-height: 1.7; color: var(--ink2);
  padding: 6px 10px; border-left: 2px solid var(--accent);
  background: var(--bg); border-radius: 0 4px 4px 0;
}
.dc-payoff.overdue { border-left-color: var(--danger); }
.dc-fs-id { font-family: Menlo, monospace; color: var(--violet); margin-right: 6px; }
.dc-fs-id.sky { color: var(--sky); }
.dc-fs-content { color: var(--ink); }
.dc-fs-payoff { color: var(--accent); margin-left: 6px; }
.dc-fs-overdue { color: var(--danger); font-weight: 600; margin-left: 6px; }
.dc-fs-planted { color: var(--faint); margin-left: 6px; font-size: 11px; }

/* McKee gap */
.dc-gap { margin-top: 8px; }
.dc-gap-item { font-size: 12px; color: var(--ink2); padding: 3px 0; line-height: 1.7; }

/* 伏笔池 */
.dc-pool-stats { display: flex; gap: 24px; padding: 4px 0; }
.dc-pool-stat { text-align: center; }
.dc-pool-num { font: 700 22px Menlo, monospace; color: var(--accent); }
.dc-pool-num.danger { color: var(--danger); }
.dc-pool-num.sky { color: var(--sky); }
.dc-pool-label { font-size: 10.5px; color: var(--faint); margin-top: 2px; }
.dc-pool-queued { margin-top: 10px; }
.dc-pool-q-item { font-size: 12px; color: var(--ink2); padding: 4px 0; line-height: 1.7; }

/* 节奏量化 */
.dc-pacing-meta { font-size: 11.5px; color: var(--faint); margin-bottom: 10px; }
.dc-pacing-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.dc-pacing-cell {
  border: 1px solid var(--line); border-radius: 6px; background: var(--bg);
  padding: 8px 10px;
}
.dc-pacing-label { font-size: 10.5px; color: var(--faint); }
.dc-pacing-val { font: 600 15px Menlo, monospace; color: var(--primary); margin-top: 2px; }

/* HTN goals + creative seeds */
.dc-extra { margin-bottom: 8px; }
.dc-goal { font-size: 12px; color: var(--ink2); padding: 4px 0; line-height: 1.7; }
.dc-goal-holder { color: var(--faint); margin-right: 6px; }
.dc-goal-desc { color: var(--ink); }
.dc-goal-status { font: 10px Menlo, monospace; color: var(--faint); margin-left: 6px; }
.dc-seed { padding: 8px 0; border-bottom: 1px dashed var(--line); }
.dc-seed:last-child { border-bottom: none; }
.dc-seed-domains { font-size: 11px; color: var(--violet); margin-bottom: 3px; }
.dc-seed-text { font-size: 12.5px; color: var(--ink); line-height: 1.7; }
.dc-seed-meta { font: 10px Menlo, monospace; color: var(--faint); margin-top: 4px; }
</style>
