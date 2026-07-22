<script setup>
/* 规划图视图：随时查阅当前项目的宏观叙事计划（六大组件）
   从 GET /api/macro/plan 读取，展示蓝图/幕结构/分集/弧光/伏笔/节奏 */
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/api'
import { useToast } from '../composables/useToast'

const props = defineProps({ project: { type: Object, default: null }, config: { type: Object, default: null } })
const emit = defineEmits(['refresh', 'navigate'])

const { toast } = useToast()
const plan = ref(null)
const loading = ref(false)
const expandedSection = ref(null)

// 枚举中文映射（与 GachaView 同款，独立维护避免跨组件耦合）
const BEAT_CN = {
  opening_image:'开场意象', setup:'建置', theme_stated:'点题', inciting_incident:'触发事件',
  debate:'犹豫辩论', break_into_two:'进入第二幕', b_story:'副线开启', fun_and_games:'施展才华',
  midpoint:'中点转折', bad_guys_close_in:'危机逼近', all_is_lost:'全线溃败',
  dark_night:'灵魂黑夜', break_into_three:'进入第三幕', finale:'终局对决', final_image:'终场意象',
}
const STORY_TYPE_CN = { redemption:'救赎型', revenge:'复仇型', growth:'成长型', forbidden_love:'禁忌之恋型', mystery:'悬疑型', coming_of_age:'成长觉醒型', quest:'征途型' }
const PACE_CN = { fast_escalation:'快速升级', slow_burn:'慢热铺垫', wave:'波浪起伏', wave_escalation:'波浪上升', dtg_staircase:'阶梯攀升', linear:'线性递进', custom:'自定义' }
const FS_TYPE_CN = { main_mystery:'主线悬念', subplot:'副线', character_secret:'角色秘密', world_rule:'世界规则', callback:'回调伏笔' }
const ARC_PHASE_CN = { setup:'建置', crack:'裂痕', midpoint_shift:'中点转变', relapse:'倒退', awakening:'觉醒', truth_embrace:'拥抱真相', new_equilibrium:'新均衡', tested:'受考验', strained:'紧绷', vindicated:'被证明', steadfast_positive:'坚定正向' }
const beatCn = n => BEAT_CN[n] || n
const storyTypeCn = t => STORY_TYPE_CN[t] || t
const paceCn = t => PACE_CN[t] || t
const fsTypeCn = t => FS_TYPE_CN[t] || t
const arcPhaseCn = t => ARC_PHASE_CN[t] || t

const sections = computed(() => {
  if (!plan.value) return []
  const p = plan.value
  const list = []
  // 蓝图
  const bp = p.blueprint || {}
  if (bp.logline || bp.thematic_argument) {
    list.push({ id: 'blueprint', title: '故事蓝图', items: [
      { label: '一句话梗概', value: bp.logline || '—' },
      ...(bp.thematic_argument ? [
        { label: '错误信念', value: bp.thematic_argument.lie || '—' },
        { label: '真相', value: bp.thematic_argument.truth || '—' },
      ] : []),
      ...(bp.central_conflict ? [
        { label: '主角想要', value: bp.central_conflict.protagonist_want || '—' },
        { label: '主角需要', value: bp.central_conflict.protagonist_need || '—' },
        { label: '赌注', value: bp.central_conflict.stakes || '—' },
      ] : []),
      { label: '故事类型', value: storyTypeCn(bp.story_type) },
      { label: '节奏定调', value: paceCn(bp.target_pace) },
      { label: '总集数', value: `${bp.total_episodes || '—'} 集` },
    ]})
  }
  // 幕结构
  const acts = (p.act_structure?.acts || [])
  if (acts.length) {
    list.push({ id: 'acts', title: '幕结构', acts: acts.map(a => ({
      name: a.name, range: a.episode_range, function: a.function || '',
      beats: (a.beats || []).map(b => ({ name: beatCn(b.name), ep: b.ep, desc: b.desc || '' }))
    }))})
  }
  // 分集梗概
  const eps = p.episode_outlines || []
  if (eps.length) {
    list.push({ id: 'episodes', title: `分集梗概（${eps.length} 集）`, episodes: eps.map(e => ({
      ep: e.episode, synopsis: e.synopsis || '—', purpose: beatCn(e.purpose || ''),
      hook: e.ends_with_hook || '', events: e.key_events || [],
    }))})
  }
  // 弧光
  const arcs = (p.arc_schedule?.characters || [])
  if (arcs.length) {
    list.push({ id: 'arcs', title: '角色弧光', arcs: arcs.map(c => ({
      name: c.name, arc: arcPhaseCn(c.archetype_arc || ''),
      milestones: (c.milestones || []).map(m => ({
        range: Array.isArray(m.episode_range) ? m.episode_range.join('-') : (m.episode_range || ''),
        phase: arcPhaseCn(m.phase || ''), state: m.state || '', behavior: m.behavior || '',
      }))
    }))})
  }
  // 伏笔
  const fs = (p.foreshadow_blueprint?.threads || [])
  if (fs.length) {
    list.push({ id: 'foreshadow', title: `伏笔线（${fs.length} 条）`, threads: fs.map(f => ({
      id: f.id, name: f.name, type: fsTypeCn(f.type || ''),
      plants: f.plant_episodes || [], harvest: f.harvest_episode,
      ladder: (f.salience_ladder || []).map(s => `第${s.ep}集:${s.form}`),
    }))})
  }
  // 节奏
  const tp = (p.pacing_curve?.key_tension_points || [])
  if (tp.length) {
    list.push({ id: 'pacing', title: '节奏曲线', points: tp })
  }
  return list
})

const sparkPoints = computed(() => {
  const pts = (plan.value?.pacing_curve?.key_tension_points || [])
  if (!pts.length) return ''
  return pts.map((t, i) => `${i * 20},${40 - (t.tension || 0) * 35}`).join(' ')
})

async function loadPlan() {
  loading.value = true
  try {
    plan.value = await api.macroPlanGet()
  } catch (e) {
    if (e.message && e.message.includes('404')) {
      plan.value = null
    } else {
      toast('加载宏观计划失败：' + (e.message || e))
    }
  }
  loading.value = false
}

function toggle(id) {
  expandedSection.value = expandedSection.value === id ? null : id
}

onMounted(loadPlan)
</script>

<template>
  <div class="macro-view">
    <div v-if="loading" class="macro-loading">加载中…</div>

    <div v-else-if="!plan" class="macro-empty">
      <p>当前项目还没有宏观计划。</p>
      <button class="btn-main" @click="emit('navigate', 'gacha')">前往开局向导生成</button>
    </div>

    <div v-else class="macro-content">
      <!-- 蓝图摘要卡（始终展开） -->
      <section v-if="sections[0]?.id === 'blueprint'" class="macro-card macro-blueprint">
        <div class="macro-card-title">故事蓝图</div>
        <p class="macro-logline">{{ sections[0].items[0].value }}</p>
        <div class="macro-bp-grid">
          <template v-for="item in sections[0].items.slice(1)" :key="item.label">
            <span class="macro-bp-label">{{ item.label }}</span>
            <span class="macro-bp-value">{{ item.value }}</span>
          </template>
        </div>
      </section>

      <!-- 可折叠的组件 -->
      <section v-for="s in sections.slice(1)" :key="s.id" class="macro-card macro-section"
               :class="{ expanded: expandedSection === s.id }">
        <button class="macro-section-header" @click="toggle(s.id)" :aria-expanded="expandedSection === s.id">
          <span>{{ s.title }}</span>
          <span class="macro-toggle">{{ expandedSection === s.id ? '▾' : '▸' }}</span>
        </button>

        <div v-if="expandedSection === s.id" class="macro-section-body">
          <!-- 幕结构 -->
          <template v-if="s.id === 'acts'">
            <div v-for="(a, i) in s.acts" :key="i" class="macro-act">
              <div class="macro-act-head">
                <span class="macro-act-name">{{ a.name }}</span>
                <span class="macro-act-range">第 {{ a.range[0] }}-{{ a.range[1] }} 集</span>
                <span class="macro-act-fn">{{ a.function }}</span>
              </div>
              <div v-for="(b, bi) in a.beats" :key="bi" class="macro-beat">
                <span class="macro-beat-name">{{ b.name }}</span>
                <span class="macro-beat-ep">{{ b.ep }}</span>
                <span class="macro-beat-desc">{{ b.desc }}</span>
              </div>
            </div>
          </template>

          <!-- 分集梗概 -->
          <template v-if="s.id === 'episodes'">
            <div v-for="e in s.episodes" :key="e.ep" class="macro-ep">
              <div class="macro-ep-head">
                <span class="macro-ep-num">第 {{ e.ep }} 集</span>
                <span v-if="e.purpose" class="macro-ep-purpose">{{ e.purpose }}</span>
              </div>
              <p class="macro-ep-syn">{{ e.synopsis }}</p>
              <p v-if="e.hook" class="macro-ep-hook">钩子：{{ e.hook }}</p>
              <div v-if="e.events.length" class="macro-ep-events">
                <span v-for="ev in e.events" :key="ev" class="macro-ep-event">{{ ev }}</span>
              </div>
            </div>
          </template>

          <!-- 弧光 -->
          <template v-if="s.id === 'arcs'">
            <div v-for="c in s.arcs" :key="c.name" class="macro-arc-char">
              <div class="macro-arc-name">{{ c.name }}（{{ c.arc }}）</div>
              <div class="macro-arc-ms">
                <div v-for="(m, mi) in c.milestones" :key="mi" class="macro-ms">
                  <span class="macro-ms-range">{{ m.range }}</span>
                  <span class="macro-ms-phase">{{ m.phase }}</span>
                  <span class="macro-ms-state">{{ m.state }}</span>
                  <span v-if="m.behavior" class="macro-ms-behavior">→ {{ m.behavior }}</span>
                </div>
              </div>
            </div>
          </template>

          <!-- 伏笔 -->
          <template v-if="s.id === 'foreshadow'">
            <div v-for="f in s.threads" :key="f.id" class="macro-fs">
              <span class="macro-fs-name">{{ f.name }}</span>
              <span class="macro-fs-type">{{ f.type }}</span>
              <span class="macro-fs-flow">埋 {{ f.plants.join(',') }} → 收 第{{ f.harvest }}集</span>
              <div v-if="f.ladder.length" class="macro-fs-ladder">
                <span v-for="l in f.ladder" :key="l" class="macro-fs-level">{{ l }}</span>
              </div>
            </div>
          </template>

          <!-- 节奏 -->
          <template v-if="s.id === 'pacing'">
            <svg :viewBox="`0 0 ${s.points.length * 20} 40`" preserveAspectRatio="none" class="macro-spark">
              <polyline :points="sparkPoints" fill="none" stroke="var(--accent)" stroke-width="2" />
              <circle v-for="(t, i) in s.points" :key="i" :cx="i * 20" :cy="40 - t.tension * 35" r="2"
                      :fill="t.tension > 0.8 ? 'var(--danger)' : 'var(--accent)'" />
            </svg>
            <div class="macro-tp-list">
              <span v-for="t in s.points" :key="t.episode" class="macro-tp">
                第{{ t.episode }}集: {{ (t.tension * 100).toFixed(0) }}% — {{ t.reason || '' }}
              </span>
            </div>
          </template>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.macro-view { max-width: 800px; margin: 0 auto; padding: 20px; }
.macro-loading, .macro-empty { text-align: center; padding: 60px 20px; color: var(--text-sec, #888); }
.macro-empty button { margin-top: 16px; }
.macro-content { display: flex; flex-direction: column; gap: 12px; }

.macro-card { background: var(--s1); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.macro-card-title { font-size: 12px; font-weight: 600; color: var(--text-sec); letter-spacing: 0.05em; padding: 10px 14px; border-bottom: 1px solid var(--border); }
.macro-logline { font: 15px/1.7 var(--serif); padding: 12px 14px; color: var(--text); }
.macro-bp-grid { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; padding: 0 14px 12px; font-size: 12px; }
.macro-bp-label { color: var(--text-sec); }
.macro-bp-value { color: var(--text); }

.macro-section-header { width: 100%; text-align: left; padding: 10px 14px; font-size: 13px; font-weight: 600; display: flex; justify-content: space-between; cursor: pointer; }
.macro-section-header:hover { background: var(--s2); }
.macro-toggle { color: var(--text-sec); }

.macro-section-body { padding: 0 14px 12px; font-size: 12px; line-height: 1.6; }

.macro-act { margin-bottom: 12px; }
.macro-act-head { display: flex; gap: 8px; align-items: baseline; margin-bottom: 4px; }
.macro-act-name { font-weight: 600; }
.macro-act-range { color: var(--text-sec); font-size: 11px; }
.macro-act-fn { color: var(--text-sec); font-size: 11px; }
.macro-beat { padding: 2px 0 2px 16px; display: flex; gap: 6px; }
.macro-beat-name { font-weight: 500; min-width: 80px; }
.macro-beat-ep { color: var(--text-sec); min-width: 40px; }

.macro-ep { padding: 6px 0; border-bottom: 1px dashed var(--border); }
.macro-ep-head { display: flex; gap: 8px; }
.macro-ep-num { font-weight: 600; }
.macro-ep-purpose { color: var(--accent); font-size: 11px; }
.macro-ep-syn { margin: 2px 0; color: var(--text); }
.macro-ep-hook { font-size: 11px; color: var(--text-sec); }
.macro-ep-events { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 2px; }
.macro-ep-event { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: var(--s3); }

.macro-arc-char { margin-bottom: 12px; }
.macro-arc-name { font-weight: 600; margin-bottom: 4px; }
.macro-ms { display: flex; gap: 6px; padding: 2px 0; font-size: 11px; }
.macro-ms-range { color: var(--text-sec); min-width: 50px; }
.macro-ms-phase { color: var(--accent); min-width: 70px; }

.macro-fs { padding: 4px 0; border-bottom: 1px dashed var(--border); }
.macro-fs-name { font-weight: 600; }
.macro-fs-type { color: var(--text-sec); font-size: 11px; margin-left: 6px; }
.macro-fs-flow { font-size: 11px; color: var(--text-sec); }
.macro-fs-ladder { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 2px; }
.macro-fs-level { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: var(--s3); }

.macro-spark { width: 100%; height: 60px; margin-bottom: 8px; }
.macro-tp-list { display: flex; flex-wrap: wrap; gap: 4px; }
.macro-tp { font-size: 11px; color: var(--text-sec); }
</style>
