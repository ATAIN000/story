<script setup>
// 关于页（P23.2）：产品信息 + 致谢 + 沟通渠道 + 开源协议 + 运行信息。
// 替代原导航左下致谢角（塞角落太憋屈，改独立 TAB 页面）。
import { computed, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'

const props = defineProps({
  project: { type: Object, default: null },
  config: { type: Object, default: null },
})

/* 群二维码：放 frontend/public/group-qr.png 即显示；缺失降级占位框 */
const qrFailed = ref(false)

const runtime = computed(() => {
  const cfg = props.config ?? {}
  const meta = props.project?.meta ?? {}
  return {
    llm: cfg.llmMode === 'mock' ? 'Mock 演示模式' : (cfg.llmModel || '—'),
    genre: meta.genre || cfg.axes?.genre || '—',
    culture: meta.culture || cfg.axes?.culture || '—',
    chapters: meta.chapterCount ?? 0,
  }
})

const LINKS = [
  { icon: 'book', title: 'README · 快速上手', desc: 'pip install → 起后端 → 设置页配 LLM → 抽卡开局' },
  { icon: 'download', title: 'Docker 一键部署', desc: 'docker build & run，镜像内置 demo 项目，开箱即用' },
]
</script>

<template>
  <div class="about">
    <div class="ab-hero">
      <div class="ab-logo" aria-hidden="true">書</div>
      <div>
        <h2>StoryOS · 故事工作台</h2>
        <p class="ab-sub">LLM 从「作者」降级为「语言层」——一致性交给结构化世界模拟层的
          AI 长篇小说写作台。315 题材 × 20 层世界观向导 × 宏观规划 × 章节生成管线。</p>
      </div>
    </div>

    <div class="ab-grid">
      <!-- 致谢卡 -->
      <section class="ab-card" data-testid="about-thanks">
        <div class="ab-card-t">
          <AppIcon name="heart" :size="14" /> 致谢
        </div>
        <p class="ab-text">感谢 <b>「凡事皆可」短剧团队</b> 在本项目调研、素材与方向上的支持。</p>
        <div class="ab-qr-row">
          <img v-if="!qrFailed" class="ab-qr" :src="'/group-qr.png'"
               alt="「凡事皆可」短剧团队交流群二维码" loading="lazy" @error="qrFailed = true" />
          <div v-else class="ab-qr ab-qr-ph">群二维码<br>放 frontend/public/group-qr.png</div>
          <div class="ab-qr-side">
            <b>后续沟通渠道</b>
            <p>扫码加入「凡事皆可」短剧团队交流群：<br>问题反馈 · 题材许愿 · 素材共建 · 版本预告</p>
          </div>
        </div>
        <div class="ab-follow">
          <b>关注抖音</b>
          <p>抖音号 <b>904608659</b> · 「凡事皆可-AIGC」<br>功能演示 · 短剧实操 · 版本预告</p>
        </div>
      </section>

      <!-- 开源协议卡 -->
      <section class="ab-card" data-testid="about-license">
        <div class="ab-card-t">
          <AppIcon name="scale" :size="14" /> 开源协议
        </div>
        <p class="ab-text">本项目以 <b>Apache License 2.0</b> 开源：可自由使用、修改、分发（包括商用），
          需保留版权声明和许可证声明。包含专利授权条款，修改后的文件需标注变更。</p>
        <p class="ab-dim">完整文本见仓库根目录 LICENSE 文件。</p>
        <div class="ab-note">
          <b>⚠️ 单用户部署</b>：本系统是个人写作台，engine/kernel 为进程级单例，
          不支持多人同时在线（会串数据）。适合本地自用或 Docker 自部署。
        </div>
      </section>

      <!-- 文档卡 -->
      <section class="ab-card" data-testid="about-docs">
        <div class="ab-card-t">
          <AppIcon name="book" :size="14" /> 文档
        </div>
        <div v-for="l in LINKS" :key="l.title" class="ab-link">
          <AppIcon :name="l.icon" :size="13" />
          <div>
            <div class="ab-link-t">{{ l.title }}</div>
            <div class="ab-link-d">{{ l.desc }}</div>
          </div>
        </div>
      </section>

      <!-- 运行信息卡 -->
      <section class="ab-card" data-testid="about-runtime">
        <div class="ab-card-t">
          <AppIcon name="zap" :size="14" /> 当前运行
        </div>
        <div class="ab-kv"><span>LLM</span><b>{{ runtime.llm }}</b></div>
        <div class="ab-kv"><span>当前项目题材</span><b>{{ runtime.genre }}</b></div>
        <div class="ab-kv"><span>文化</span><b>{{ runtime.culture }}</b></div>
        <div class="ab-kv"><span>已写章节</span><b>第 {{ runtime.chapters }} 章</b></div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.about { height: 100%; overflow-y: auto; padding: 30px 34px 60px; }

.ab-hero { display: flex; gap: 16px; align-items: flex-start; max-width: 760px; margin-bottom: 26px; }
.ab-logo { width: 52px; height: 52px; border-radius: 12px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font: 700 26px var(--serif); color: #fffdf8; background: var(--primary); }
.ab-hero h2 { font: 700 22px var(--serif); color: var(--ink); margin-bottom: 6px; }
.ab-sub { font-size: 13px; color: var(--ink2); line-height: 1.8; margin: 0; }

.ab-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px; max-width: 1080px; }
.ab-card { border: 1px solid var(--line); border-radius: 10px; background: var(--s1);
  padding: 16px 18px; }
.ab-card-t { display: flex; align-items: center; gap: 7px;
  font: 700 14px var(--serif); color: var(--ink); margin-bottom: 12px; }
.ab-text { font-size: 13px; color: var(--ink); line-height: 1.8; margin: 0 0 10px; }
.ab-text b { color: var(--primary); }
.ab-dim { font-size: 11.5px; color: var(--faint); margin: 0; }
.ab-note { font-size: 12px; color: var(--ink); line-height: 1.7; margin-top: 10px;
  padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px;
  background: var(--s1); }
.ab-note b { color: var(--primary); }

.ab-qr-row { display: flex; gap: 14px; align-items: center; }
.ab-qr { width: 108px; height: 108px; border-radius: 10px; object-fit: cover;
  border: 1px solid var(--line2); flex-shrink: 0; }
.ab-qr-ph { display: flex; align-items: center; justify-content: center; text-align: center;
  font-size: 10px; line-height: 1.6; color: var(--faint);
  border-style: dashed; background: var(--s2); }
.ab-qr-side b { font-size: 13px; color: var(--ink); }
.ab-qr-side p { font-size: 12px; color: var(--ink2); line-height: 1.7; margin: 6px 0 0; }

.ab-follow { margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--line); }
.ab-follow b { font-size: 13px; color: var(--ink); }
.ab-follow p { font-size: 12px; color: var(--ink2); line-height: 1.7; margin: 6px 0 0; }
.ab-follow p b { color: var(--primary); }

.ab-link { display: flex; gap: 10px; align-items: flex-start; padding: 7px 0;
  color: var(--ink2); }
.ab-link + .ab-link { border-top: 1px dashed var(--line); }
.ab-link-t { font-size: 13px; font-weight: 600; color: var(--ink); }
.ab-link-d { font-size: 11.5px; color: var(--faint); margin-top: 2px; }

.ab-kv { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0;
  font-size: 13px; }
.ab-kv + .ab-kv { border-top: 1px dashed var(--line); }
.ab-kv span { color: var(--faint); }
.ab-kv b { color: var(--ink); font-weight: 600; }
</style>
