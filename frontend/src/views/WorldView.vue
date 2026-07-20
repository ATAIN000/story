<script setup>
// 世界观（P6.9）：规则卡 + 简化条目（地点/物品/势力/人物）。
// 数据源：toWorldViewVM —— world_rules 从 genre 静态回退（后端 /api/config 未暴露，
// brief 允许「静态读或省略」）；条目从 world 快照聚合（physical/relationships/minds），
// 不编造。稀疏时友好提示「世界观条目由生成过程填充，本视图展示已建立的规则与出场统计」。
import { computed, ref, watch } from 'vue'
import { toWorldViewVM } from '../api/adapters'
import EmptyState from '../components/EmptyState.vue'

const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})

const vm = computed(() => toWorldViewVM(props.project, props.config))

/* 左侧分类：规则 + 条目按 kind 分组 */
const CATS = computed(() => {
  const groups = new Map()
  /* 规则独立一类 */
  if (vm.value.rules.length) groups.set('世界规则', { type: 'rules', items: vm.value.rules })
  /* 条目按 kind 归类 */
  for (const e of vm.value.entries) {
    const k = e.kind || '其他'
    if (!groups.has(k)) groups.set(k, { type: 'entries', items: [] })
    groups.get(k).items.push(e)
  }
  return [...groups.entries()].map(([name, g]) => ({ name, ...g }))
})

const activeCat = ref(null)
function ensureSelection() {
  if (!CATS.value.length) { activeCat.value = null; return }
  if (!activeCat.value || !CATS.value.some(c => c.name === activeCat.value)) {
    activeCat.value = CATS.value[0].name
  }
}
watch(CATS, ensureSelection, { immediate: true })

const activeGroup = computed(() => CATS.value.find(c => c.name === activeCat.value) ?? null)

const GENRE_LABEL = { mystery: '悬疑 · 公案', romance: '言情', wuxia: '武侠' }
</script>

<template>
  <div v-if="!vm.hasAny" class="wv-empty">
    <EmptyState icon="map" title="世界观尚未建立"
      desc="世界观条目由生成过程填充。生成章节后，这里会展示题材规则卡（Z3 硬约束）+ 已确立的地点/物品/人物/势力条目。" />
  </div>

  <div v-else class="world">
    <!-- 左：分类 -->
    <aside class="w-cats" aria-label="世界观分类">
      <div class="b-t">世界观条目</div>
      <button v-for="c in CATS" :key="c.name" class="w-cat"
              :class="{ active: c.name === activeCat }"
              :aria-current="c.name === activeCat ? 'true' : undefined"
              @click="activeCat = c.name">
        <div class="cn">{{ c.name }}</div>
        <div class="cc">{{ c.items.length }} 条</div>
      </button>
    </aside>

    <!-- 右：详情 -->
    <section class="w-detail" aria-label="分类详情">
      <div class="w-entry">
        <!-- 规则卡 -->
        <template v-if="activeGroup?.type === 'rules'">
          <h2>世界规则 <span class="w-genre">{{ GENRE_LABEL[vm.genre] || vm.genre || '—' }}</span></h2>
          <div class="w-type">Z3 SMT 硬约束 · validator 实时校验 · 违反即拒绝事件提交</div>
          <div v-for="(r, i) in activeGroup.items" :key="i" class="rule-card">
            <div class="r-id">{{ r.id }} · {{ r.kind }}</div>
            <div class="r-desc">{{ r.desc }}</div>
            <div class="r-expr">{{ r.expr }}</div>
          </div>
          <hr class="w-sep" />
          <div class="w-note">
            <span class="muted">规则来源：story_engine/plugins/genres/*.yaml 的 world_rules 字段。
              后端 /api/config 暂未暴露，本视图按题材静态回退展示（brief §「world_rules 在 genre params 里」）。</span>
          </div>
        </template>

        <!-- 普通条目 -->
        <template v-else-if="activeGroup">
          <h2>{{ activeGroup.name }}</h2>
          <div class="w-type">{{ activeGroup.items.length }} 条 · 从世界状态快照聚合</div>

          <template v-for="(it, i) in activeGroup.items" :key="i">
            <div class="w-item">
              <h3>{{ it.name }}</h3>
              <p>{{ it.desc }}</p>
              <div v-if="it.scenes?.length" class="w-scenes">
                <span v-for="(s, si) in it.scenes" :key="si" class="scene-chip">{{ s }}</span>
              </div>
            </div>
            <hr class="w-sep" />
          </template>
        </template>

        <!-- 稀疏提示 -->
        <div v-if="vm.entries.length < 3" class="w-sparse">
          <span class="muted">
            世界观条目由生成过程填充，本视图展示已建立的规则与出场统计。
            更多条目（地点/物品/势力）会在后续章节的事件流中逐步聚合出来。
          </span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.wv-empty { height: 100%; display: flex; align-items: flex-start; justify-content: center; overflow-y: auto; padding-top: 40px; }

.world { display: grid; grid-template-columns: 220px 1fr; height: 100%; overflow: hidden; }
@media (max-width: 880px) { .world { grid-template-columns: 1fr; } }
.w-cats { border-right: 1px solid var(--line); background: var(--s1); padding: 14px 10px;
  overflow-y: auto; transition: background .25s; }
.b-t { font: 700 12px var(--serif); color: var(--ink2); padding: 0 8px 10px; letter-spacing: 1px; }
.w-cat { display: block; width: 100%; padding: 8px 10px; border: none; background: transparent;
  border-radius: 6px; cursor: pointer; margin-bottom: 1px; text-align: left; transition: background .12s; }
.w-cat:hover { background: var(--s3); }
.w-cat.active { background: var(--primary-tint); }
.w-cat .cn { font-size: 13px; font-weight: 600; color: var(--ink); }
.w-cat.active .cn { color: var(--primary); }
.w-cat .cc { font-size: 11px; color: var(--faint); margin-top: 2px; }

.w-detail { overflow-y: auto; padding: 30px 34px; transition: background .25s; }
.w-entry { max-width: 720px; }
.w-entry h2 { font: 700 24px var(--serif); color: var(--ink); margin-bottom: 4px; }
.w-entry h3 { font: 700 16px var(--serif); color: var(--ink); margin-bottom: 4px; }
.w-genre { font-size: 12px; color: var(--faint); font-family: Menlo, monospace; font-weight: 400; margin-left: 8px; }
.w-type { font-size: 12px; color: var(--faint); margin-bottom: 14px; }
.w-entry p { font: 14px/1.9 var(--serif); color: var(--ink); }
.w-item { margin-bottom: 4px; }
.w-scenes { margin-top: 8px; }
.scene-chip { display: inline-block; font-size: 11px; padding: 2px 9px; border-radius: 4px;
  margin: 0 5px 5px 0; color: var(--sky); border: 1px solid var(--sky); }

.rule-card { border-left: 2px solid var(--danger); background: var(--s2);
  border-radius: 0 8px 8px 0; padding: 11px 15px; margin: 12px 0; font-size: 13px; }
.rule-card .r-id { font-family: Menlo, monospace; font-size: 10.5px; color: var(--faint); }
.rule-card .r-desc { margin-top: 4px; color: var(--ink); line-height: 1.7; }
.rule-card .r-expr { margin-top: 4px; font-family: Menlo, monospace; font-size: 11px;
  color: var(--accent); word-break: break-all; }

.w-sep { border: none; border-top: 1px solid var(--line); margin: 18px 0; }
.w-note, .w-sparse { margin-top: 14px; padding: 10px 14px; background: var(--s2);
  border-left: 2px solid var(--faint); border-radius: 0 6px 6px 0; }
.muted { color: var(--faint); font-size: 12px; line-height: 1.7; }
</style>
