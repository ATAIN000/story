// 开局抽卡 Node 自检脚本（已入库，随仓库提交）
// 用最小 DOM/BOM shim 在无浏览器环境跑 web/gacha/index.html 内联 JS 的 selftest
// 用法：从仓库根运行 node scripts/gacha_selftest.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(root, "web/gacha/index.html"), "utf8");
const dataJs = readFileSync(join(root, "web/gacha/data.js"), "utf8");

// 提取 <script> 块：页面第 1 个是 <script src="data.js">，第 2 个（无 src）是内联逻辑
const blocks = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
if (blocks.length !== 2) {
  console.error(`FAIL：<script> 块数量=${blocks.length}，预期 2`);
  process.exit(1);
}
if (/\bsrc\s*=/.test(blocks[1][1])) {
  console.error("FAIL：第二个 <script> 块带 src，不是内联脚本");
  process.exit(1);
}
const pageJs = blocks[1][2];

// ---- 最小 shim ----
const elements = new Map();
globalThis.window = globalThis; // window 即全局代理，承载 GACHA_DATA
globalThis.document = {
  getElementById(id) {
    // 返回吸收赋值的对象（textContent/innerHTML/style/onclick/classList 均可写）
    if (!elements.has(id)) {
      elements.set(id, {
        style: {}, dataset: {}, offsetWidth: 0,
        classList: { add() {}, remove() {}, toggle() {} },
        setAttribute() {},
      });
    }
    return elements.get(id);
  },
  createElement() {
    return { click() {}, href: "", download: "" };
  },
  title: "",
};
// 最小 localStorage mock（内存 Map）；Task 7 降级测试会整体替换为抛错版本
const lsStore = new Map();
globalThis.localStorage = {
  getItem: k => (lsStore.has(k) ? lsStore.get(k) : null),
  setItem: (k, v) => { lsStore.set(k, String(v)); },
  removeItem: k => { lsStore.delete(k); },
};
globalThis.history = { replaceState() {} };
globalThis.location = { hash: "", search: "?selftest=1" };
globalThis.addEventListener = () => {}; // Node 无 DOM 事件，hashchange 监听挂空
Object.defineProperty(globalThis, "navigator", {
  value: { clipboard: { writeText: () => Promise.resolve() } },
  configurable: true, writable: true,
});
const alerts = [];
globalThis.alert = msg => alerts.push(String(msg));
// Image 探针 mock：记录每次 src 赋值（服务器统计探针 track() 的载体）
const tracked = [];
globalThis.Image = class { set src(v) { tracked.push(String(v)); } };
// Blob / URL / URL.createObjectURL：Node 22 自带 Blob；createObjectURL 需补
if (!URL.createObjectURL) {
  URL.createObjectURL = () => "blob:shim";
  URL.revokeObjectURL = () => {};
}

const logs = [];
const origLog = console.log;
console.log = (...args) => { logs.push(args.join(" ")); origLog(...args); };

try {
  (0, eval)(dataJs); // data.js 是 window.GACHA_DATA = {...} 赋值
  if (!globalThis.GACHA_DATA) throw new Error("data.js 执行后 window.GACHA_DATA 仍为空");
  // 页面脚本为严格模式 eval，函数不外泄；末尾导出引用供功能点抽查
  (0, eval)(pageJs + "\n;globalThis.__t = {toMarkdown, roll, decode, encode, state, BLOCKS, buildModel, render, switchTab, pickGenre, fortuneOf, almanacOf, setZodiac, toggleFav, isFav, renderRecList, restoreCode, FORTUNE_TPLS, ALMANAC_POOL, ZODIACS};");
} catch (e) {
  console.log = origLog;
  console.error("FAIL：页面脚本执行抛异常：", e);
  process.exit(1);
}
console.log = origLog;

const fails = [];
if (!logs.some(l => l.includes("SELFTEST PASS"))) fails.push("console 输出无 SELFTEST PASS");
if (document.title !== "SELFTEST PASS") fails.push(`document.title=${JSON.stringify(document.title)}`);
if (alerts.length) fails.push(`alert 被调用：${alerts.join("；")}`);

// initPage 渲染断言：结果区 #pack 已显示，hero/tabs/详情面板各元素已渲染，开局码格式正确，codeBar/actions 已显示
const D = globalThis.GACHA_DATA;
const pack = elements.get("pack");
if (pack?.style?.display !== "block") fails.push("#pack 未显示");
const tabsHtml0 = elements.get("tabs")?.innerHTML || "";
if (tabsHtml0.length < 200) fails.push("#tabs 未渲染");
else {
  if ((tabsHtml0.match(/class="tab[ "]/g) || []).length !== 5) fails.push("TAB 数量不是 5 个");
  for (const label of [">题材<", ">世界观<", ">骨架<", ">人物<", ">大纲<"])
    if (!tabsHtml0.includes(label)) fails.push(`TAB 栏缺少标签「${label}」`);
}
if ((elements.get("panel")?.innerHTML || "").length < 200) fails.push("#panel 未渲染或过短");
const t = globalThis.__t;
// hero 摘要区：题材大标题 / 一句话 pitch / 人物一行均非空
for (const id of ["heroTitle", "heroPitch", "heroMetaCast", "heroMetaW", "heroMetaS"])
  if (!elements.get(id)?.textContent) fails.push(`#${id} 为空`);
if (!/主角 .+ · 对手 .+ · 盟友 .+/.test(elements.get("heroMetaCast")?.textContent || ""))
  fails.push(`hero 人物一行格式不对：${JSON.stringify(elements.get("heroMetaCast")?.textContent)}`);
// 默认激活「题材」面板：标题 + 注释 + 标签 chips + 核心冲突
const panel0 = elements.get("panel")?.innerHTML || "";
for (const kw of ["题材 · ", "题材决定故事的轨道、节奏与冲突类型", "核心冲突", "class=\"tag\""])
  if (!panel0.includes(kw)) fails.push(`题材面板缺少「${kw}」`);
// 五个面板注释逐字核对 + 结构抽查
const NOTES = {
  genre: "题材决定故事的轨道、节奏与冲突类型",
  worldview: "世界观决定这个世界的底层设定与运行规则",
  skeleton: "骨架决定 12 集的幕拍结构——每个节点该发生什么",
  cast: "人物阵容由题材与文化推导，名字随重 Roll 更换",
  outline: "按骨架拍点生成的分幕大纲，每拍一句；末尾钩子留给读者",
};
for (const [tab, note] of Object.entries(NOTES)) {
  t.switchTab(tab);
  const ph = elements.get("panel")?.innerHTML || "";
  if (!ph.includes(`<p class="note">${note}</p>`)) fails.push(`${tab} 面板注释不符：预期「${note}」`);
}
t.switchTab("outline");
const panelOutline = elements.get("panel")?.innerHTML || "";
for (const kw of ["分幕大纲（12 集）", "hook-box", "class=\"act\""])
  if (!panelOutline.includes(kw)) fails.push(`大纲面板缺少「${kw}」`);
t.switchTab("cast");
if (!/class="mini-name"/.test(elements.get("panel")?.innerHTML || "")) fails.push("人物面板缺迷你卡");
t.switchTab("skeleton");
if (!/（第\d+-\d+集）—— /.test(elements.get("panel")?.innerHTML || "")) fails.push("骨架面板缺幕结构概览行");
t.switchTab("genre");
// 副标题动态计数
if (elements.get("sub")?.textContent !== "315 题材 × 10 世界观 × 31 骨架 · 一次抽齐开局，锁定满意的部分再 Roll")
  fails.push(`副标题不对：${JSON.stringify(elements.get("sub")?.textContent)}`);
const codeText = elements.get("codeText")?.textContent;
if (!/^[0-9a-z]{2}-[0-9a-z]-[0-9a-z]-[0-9a-z]{4}-[0-9a-z]{4}$/.test(codeText || ""))
  fails.push(`开局码格式不对：${JSON.stringify(codeText)}`);
if (elements.get("codeBar")?.style?.display !== "flex") fails.push("#codeBar 未显示");
if (elements.get("actions")?.style?.display !== "flex") fails.push("#actions 未显示");
if (elements.get("err")?.style?.display === "block") fails.push("#err 被显示（GACHA_DATA 缺失分支）");
if (elements.get("footer")?.textContent !== "开局结构来自 StoryOS 题材库 · 315 题材 × 10 世界观 × 31 骨架")
  fails.push(`页脚计数未按数据动态生成：${JSON.stringify(elements.get("footer")?.textContent)}`);
if (!html.includes("凡事皆可 · ALL THINGS POSSIBLE")) fails.push("缺页脚品牌行「凡事皆可 · ALL THINGS POSSIBLE」");

// 暗黑主题断言：设计 token 就位，旧皮肤（橙/米色/衬线字体栈）与 emoji 零残留
// 契合度星号 ★(U+2605)☆(U+2606) 为 brief 特许文本字符，从 emoji 区间中剔除
const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{2604}\u{2607}-\u{27BF}]/u;
if (EMOJI_RE.test(html)) fails.push("index.html 源码含 emoji 残留");
for (const legacy of ["#b5501f", "#f7f3ea", "#fffdf8", "🎲", "🔒", "🔓", "✓"])
  if (html.includes(legacy)) fails.push(`index.html 含旧皮肤残留「${legacy}」`);
// 主站字体栈以 sans-serif 收尾，故 serif 残留检测需排除 sans- 前缀
if (/(?<!sans-)serif/.test(html)) fails.push("index.html 含旧皮肤残留「serif 字体栈」");
for (const token of ["--bg: #0d1117", "--card: #12161d", "--line: #232a35",
                     "--ink: #e6e9ee", "--ink2: #94a0ac",
                     "#ff5f6d", "#ffb35c", "#f7e96b", "#5fd08a", "#5aa7ff", "#b07cff"])
  if (!html.includes(token)) fails.push(`index.html 缺设计 token「${token}」`);
// 主站融合断言：彩虹波 SVG + hueflow 流动动画就位，静态渐变短线已删，开局码条在按钮组下方
if (!html.includes('class="rainbow"')) fails.push('缺主站彩虹波 SVG（class="rainbow"）');
if (!html.includes("hueflow")) fails.push("缺 hueflow 渐变流动动画");
if (html.includes("brand-line")) fails.push("静态渐变短线 brand-line 未删除");
if (!(html.indexOf('id="actions"') < html.indexOf('id="codeBar"')))
  fails.push("开局码条 #codeBar 未移到按钮组 #actions 下方");
// 图标渲染断言：按钮与 TAB 锁钮真实渲染 <svg>，渲染结果无 emoji
const renderedHtml = ["rollBtn", "copyCodeBtn", "restoreBtn", "copyMdBtn", "dlMdBtn", "tabs", "panel"]
  .map(id => elements.get(id)?.innerHTML || "").join("\n");
if (EMOJI_RE.test(renderedHtml)) fails.push("渲染结果 innerHTML 含 emoji 残留");
if (!renderedHtml.includes("<svg")) fails.push("渲染结果未渲染任何 <svg 图标");
for (const btnId of ["rollBtn", "copyCodeBtn", "restoreBtn", "copyMdBtn", "dlMdBtn"])
  if (!(elements.get(btnId)?.innerHTML || "").includes("<svg")) fails.push(`#${btnId} 缺 SVG 图标`);
if (!tabsHtml0.includes("<svg")) fails.push("TAB 锁钮未渲染 SVG 图标");

// 数据卫生断言：50 组随机码 × 5 个 tab 的渲染结果中不得有 slug 残留
// （tags/setting/characters 展示区不出现 [a-z]+[_-][a-z]+ 模式与已知内部代号）
// 注意：innerHTML 含 HTML 属性（如 data-tab），先剥标签再匹配文本内容
const SLUG_RE = /[a-z]+[_-][a-z]+/;
const KNOWN_SLUGS = /modern-chinese-urban|infinite_flow|dungeon_loop|hard_reality|western_fantasy|xianxia_cultivation|post_apocalyptic/;
const stripTags = html => html.replace(/<[^>]*>/g, " ");
t.state.locks = {};
let slugHits = 0;
for (let i = 0; i < 50; i++) {
  t.state.gi = Math.floor(Math.random() * D.genres.length);
  t.state.wi = Math.floor(Math.random() * D.worldviews.length);
  t.state.si = Math.floor(Math.random() * D.skeletons.length);
  t.state.cast = Math.floor(Math.random() * 36 ** 4).toString(36).padStart(4, "0");
  t.state.outline = Math.floor(Math.random() * 36 ** 4).toString(36).padStart(4, "0");
  t.render();
  const heroText = ["heroTitle", "heroPitch", "heroMetaCast", "heroMetaW", "heroMetaS"]
    .map(id => elements.get(id)?.textContent || "").join(" ");
  const regions = [heroText, elements.get("tabs")?.innerHTML || ""];
  for (const tab of ["genre", "worldview", "skeleton", "cast", "outline"]) {
    t.switchTab(tab);
    regions.push(elements.get("panel")?.innerHTML || "");
  }
  for (const r of regions) {
    const text = stripTags(r);
    const m1 = text.match(SLUG_RE), m2 = text.match(KNOWN_SLUGS);
    if (m1 || m2) {
      fails.push(`渲染结果含 slug 残留 @码=${t.encode(t.state)}：${JSON.stringify((m1 || m2)[0])}`);
      slugHits++;
      break;
    }
  }
}
if (!slugHits) console.log("SLUG-SCAN OK：50 组随机码 × 5 tab 渲染结果无 slug 残留");

// 功能点抽查：MD 导出 / 锁定重 Roll / 坏开局码拒绝
const md = t.toMarkdown();
for (const kw of ["# ", "开局码 `", "## 题材", "## 世界观 ·", "## 骨架 ·", "## 人物", "## 分幕大纲（12 集）", "**E"])
  if (!md.includes(kw)) fails.push(`toMarkdown 缺少「${kw}」`);
if (!md.includes("数据版本 " + globalThis.GACHA_DATA.version)) fails.push("toMarkdown 缺数据版本");
// 锁定 2 块后 roll：锁定块（下标/种子）不变，其余变化
t.state.locks = { genre: true, cast: true };
const before = { gi: t.state.gi, wi: t.state.wi, si: t.state.si, cast: t.state.cast, outline: t.state.outline };
t.roll();
if (t.state.gi !== before.gi || t.state.cast !== before.cast)
  fails.push("锁定块被 roll 改变");
if (t.state.wi === before.wi && t.state.si === before.si && t.state.outline === before.outline)
  fails.push("未锁定块未变化（极小概率事件，重跑一次再判）");
// 全锁定时 roll 应 alert 且不改动
t.state.locks = Object.fromEntries(t.BLOCKS.map(b => [b, true]));
const frozen = t.encode(t.state);
t.roll();
if (t.encode(t.state) !== frozen) fails.push("全锁定 roll 改动了开局码");
if (!alerts.length) fails.push("全锁定 roll 未 alert 提示");
// 坏开局码：空 / 旧格式 5×4（功能未发布不兼容）/ 段长错 / 非法字符 / 6 段 / 三类下标越界
for (const bad of ["", "k7x2-m9p4-q3z8-n1b6-r5t7", "3k-9-b-k7x2-m9p", "3-a-b-k7x2-m9p4",
                   "3k-9-b-k7x2!m9p4", "3k-9-b-k7x2-m9p4-00", "zz-0-0-aaaa-bbbb",
                   "00-a-0-aaaa-bbbb", "00-0-v-aaaa-bbbb"])
  if (t.decode(bad) !== null) fails.push(`decode 应拒绝 ${JSON.stringify(bad)}`);
// 大写开局码应可还原（trim+toLowerCase），且下标解析正确
const up = t.decode("  3K-9-B-K7X2-M9P4 ");
if (!up || up.gi !== 128 || up.wi !== 9 || up.si !== 11 || up.cast !== "k7x2" || up.outline !== "m9p4")
  fails.push(`decode 未正确还原大写开局码：${JSON.stringify(up)}`);

// 锁定泄漏核心断言：固定 wi/si/cast/outline 遍历全部 315 个 gi——
// 世界观/骨架/句式模板选择必须零漂移；姓名按名字池分组一致（池随题材文化切换属预期）；
// 填空词随题材变化（line 变体数 > 1，证明题材仍有影响力）
const fixed = { wi: 3, si: 5, cast: "k7x2", outline: "m9p4" };
const ref = t.buildModel({ gi: 0, ...fixed });
const refTpls = ref.acts.flatMap(a => a.beats.map(b => b.tpl)).join("␟");
const poolOf = gi => D.culturePool[D.genres[gi].recommendedCulture || "modern-chinese-urban"] || "cn";
const poolNames = new Map(), lineSets = new Set();
let wsDrift = 0;
for (let gi = 0; gi < D.genres.length; gi++) {
  const m = t.buildModel({ gi, ...fixed });
  if (m.w.key !== ref.w.key || m.s.id !== ref.s.id) { wsDrift++; continue; }
  if (m.acts.flatMap(a => a.beats.map(b => b.tpl)).join("␟") !== refTpls)
    fails.push(`gi=${gi} 句式模板选择随题材漂移（锁定泄漏）`);
  const p = poolOf(gi), nj = JSON.stringify(m.names);
  if (poolNames.has(p)) { if (poolNames.get(p) !== nj) fails.push(`gi=${gi} 同名字池姓名随题材漂移（锁定泄漏）`); }
  else poolNames.set(p, nj);
  lineSets.add(JSON.stringify(m.acts.map(a => a.beats.map(b => b.line))));
}
if (wsDrift) fails.push(`${wsDrift} 个题材的世界观/骨架随 gi 漂移（锁定泄漏）`);
if (poolNames.size < 2) fails.push("名字池分组不足，跨池场景未真正覆盖");
if (lineSets.size < 2) fails.push("填空词未随题材变化（题材失去影响力，异常）");
console.log(`LOCK-SCAN OK：遍历 315 题材，世界观/骨架/句式模板零漂移，名字池分组 ${poolNames.size} 个，line 变体 ${lineSets.size} 种`);

// roll 跟随当前题材推荐：锁 genre=0（recommendedPreset=western_fantasy）只摇世界观，命中率应≈73%（0.7+0.3/10）
t.state.locks = { genre: true, skeleton: true, cast: true, outline: true };
t.state.gi = 0;
const wantWi = D.worldviews.findIndex(x => x.key === D.genres[0].recommendedPreset);
let hit = 0; const N = 300;
for (let i = 0; i < N; i++) { t.roll(); if (t.state.wi === wantWi) hit++; }
if (hit / N < 0.5) fails.push(`推荐跟随命中率异常：${hit}/${N}（期望≈73%）`);
console.log(`FOLLOW OK：锁题材摇世界观 ${N} 次命中推荐 ${hit} 次（${(hit / N * 100).toFixed(1)}%，期望≈73%）`);

// ==================== Task 7：玄学加成 / 抽卡历史 / 收藏 ====================
// 结构断言：黄历在抽卡按钮上方、玄学区在按钮下方、「记录」是按钮组第三钮、记录面板在按钮组下方
if (!(html.indexOf('id="almanac"') !== -1 && html.indexOf('id="almanac"') < html.indexOf('id="rollBtn"')))
  fails.push("黄历行 #almanac 不在抽卡按钮上方");
if (!(html.indexOf('id="rollBtn"') < html.indexOf('id="mystic"')))
  fails.push("玄学折叠区 #mystic 不在抽卡按钮下方");
if (!(html.indexOf('id="copyMdBtn"') < html.indexOf('id="dlMdBtn"') && html.indexOf('id="dlMdBtn"') < html.indexOf('id="recBtn"')))
  fails.push("「记录」不是底部按钮组第三个按钮");
if (!(html.indexOf('id="actions"') < html.indexOf('id="recPanel"') && html.indexOf('id="recPanel"') < html.indexOf('id="codeBar"')))
  fails.push("记录面板 #recPanel 不在按钮组下方");
// 黄历渲染：灰字一行、宜 3 忌 2、用词在词池内
const almanacText = elements.get("almanac")?.textContent || "";
if (!/^今日黄历 · 宜 .+ · 忌 .+$/.test(almanacText)) fails.push(`黄历行格式不对：${JSON.stringify(almanacText)}`);
// 玄学折叠区：12 星座 chips 渲染
const chipsHtml = elements.get("zodiacChips")?.innerHTML || "";
if ((chipsHtml.match(/class="chip"/g) || []).length !== 12) fails.push("星座 chips 不是 12 个");
for (const zn of ["白羊", "金牛", "双子", "巨蟹", "狮子", "处女", "天秤", "天蝎", "射手", "摩羯", "水瓶", "双鱼"])
  if (!chipsHtml.includes(`>${zn}<`)) fails.push(`星座 chips 缺「${zn}」`);
// 批注模板库 8 条逐字核对
const TPLS8 = [
  "{zodiac}今日与「{genre}」相位相合——这开局藏着你的本命故事",
  "水星顺行：{mc}的决断力加成，宜立刻动笔",
  "{zodiac}的守护星落在「{world}」，世界观与你同频",
  "卦象显示：「{main}」线宜慢热，前三集忍住别爆",
  "{zodiac}注意：{rival}这类对手，专治你的拖延症",
  "今日抽到「{genre}」：{zodiac}的直觉会替你写好第一章",
  "黄道吉日加持：此坑烂尾率下降（玄学意义上）",
  "{zodiac}×「{genre}」：星盘说这里有个你没见过的反转",
];
if (JSON.stringify(t.FORTUNE_TPLS) !== JSON.stringify(TPLS8)) fails.push("批注模板库与 brief 8 条逐字不符");

// 抽卡历史：点抽卡按钮 3 次 → 3 条、码格式合法；再 60 次 → 封顶 50
t.state.locks = {};
localStorage.removeItem("storyos_gacha_history");
for (let i = 0; i < 3; i++) elements.get("rollBtn").onclick();
let hist = JSON.parse(localStorage.getItem("storyos_gacha_history") || "[]");
if (hist.length !== 3) fails.push(`抽卡 3 次后 history=${hist.length} 条（预期 3）`);
else if (!hist.every(h => /^[0-9a-z]{2}-[0-9a-z]-[0-9a-z]-[0-9a-z]{4}-[0-9a-z]{4}$/.test(h.code) && h.genreTitle && h.ts > 0))
  fails.push(`history 记录格式不对：${JSON.stringify(hist[0])}`);
for (let i = 0; i < 60; i++) elements.get("rollBtn").onclick();
hist = JSON.parse(localStorage.getItem("storyos_gacha_history") || "[]");
if (hist.length !== 50) fails.push(`history 未封顶 50：${hist.length}`);

// 服务器统计探针：63 次有效抽卡 → 63 次 pixel.gif 请求，query 含码/版本/星座；还原不触发
if (tracked.length !== 63) fails.push(`63 次抽卡后探针请求=${tracked.length} 次（预期 63）`);
else {
  const last = tracked[tracked.length - 1];
  const m = last.match(/^pixel\.gif\?c=([0-9a-z-]+)&v=([^&]+)&z=(.+)$/);
  if (!m) fails.push(`探针 URL 格式不对：${last}`);
  else if (m[1] !== t.encode(t.state)) fails.push(`探针码 ${m[1]} ≠ 当前码 ${t.encode(t.state)}`);
  else if (m[3] !== "-") fails.push(`未选星座时 z 应为 -，实为 ${m[3]}`);
}
t.setZodiac("天蝎");
elements.get("rollBtn").onclick();
if (!tracked[tracked.length - 1].endsWith("&z=天蝎"))
  fails.push(`选天蝎后探针 z 参数不对：${tracked[tracked.length - 1]}`);
t.setZodiac(null);
const trackedBefore = tracked.length;
t.restoreCode(t.encode(t.state));
if (tracked.length !== trackedBefore) fails.push("码还原不应触发统计探针");
// 历史列表行：题材+时间+码+还原钮+转收藏星钮
t.renderRecList();
const recHistHtml = elements.get("recList")?.innerHTML || "";
if (!recHistHtml.includes('data-act="restore"')) fails.push("历史列表缺「还原」钮");
if (!recHistHtml.includes('data-act="fav"')) fails.push("历史行缺转收藏星钮");
if (!/rec-code/.test(recHistHtml)) fails.push("历史行缺等宽码");

// 收藏：往返正确 + 上限 100 + hero 星钮状态刷新
localStorage.removeItem("storyos_gacha_favs");
t.toggleFav();
let favs = JSON.parse(localStorage.getItem("storyos_gacha_favs") || "[]");
if (favs.length !== 1 || favs[0].code !== t.encode(t.state)) fails.push("收藏未写入或内容不对");
if (!t.isFav(t.encode(t.state))) fails.push("收藏后 isFav 应为 true");
if (!(elements.get("favBtn")?.innerHTML || "").includes('fill="currentColor"')) fails.push("收藏后星钮未变实心");
t.toggleFav();
favs = JSON.parse(localStorage.getItem("storyos_gacha_favs") || "[]");
if (favs.length !== 0 || t.isFav(t.encode(t.state))) fails.push("取消收藏未生效");
if ((elements.get("favBtn")?.innerHTML || "").includes('fill="currentColor"')) fails.push("取消收藏后星钮未还原空心");
for (let i = 0; i < 105; i++) { t.state.cast = i.toString(36).padStart(4, "0"); t.toggleFav(); }
favs = JSON.parse(localStorage.getItem("storyos_gacha_favs") || "[]");
if (favs.length !== 100) fails.push(`收藏未封顶 100：${favs.length}`);
localStorage.removeItem("storyos_gacha_favs");
// 收藏子 TAB：删除钮就位；清空后灰字提示
t.toggleFav();
elements.get("recTabFav").onclick();
const recFavHtml = elements.get("recList")?.innerHTML || "";
if (!recFavHtml.includes('data-act="del"')) fails.push("收藏列表缺「删除」钮");
localStorage.removeItem("storyos_gacha_favs");
t.renderRecList();
if (!(elements.get("recList")?.innerHTML || "").includes("暂无记录，去抽一发")) fails.push("空收藏列表缺灰字提示");
elements.get("recTabHist").onclick();

// 记录面板「还原」= decode → state → render，不记历史
const histLenBefore = JSON.parse(localStorage.getItem("storyos_gacha_history") || "[]").length;
t.restoreCode("3k-9-b-k7x2-m9p4");
if (t.encode(t.state) !== "3k-9-b-k7x2-m9p4") fails.push("记录面板还原未生效");
if (JSON.parse(localStorage.getItem("storyos_gacha_history") || "[]").length !== histLenBefore)
  fails.push("记录面板还原记了历史（不应记）");

// 批注确定性：同码同星座同日期完全一致；12 星座至少 2 种结果；星数 1-5
const fc = "3k-9-b-k7x2-m9p4", fd = "2026-10-07";
const f1 = t.fortuneOf(fc, "天蝎", fd), f2 = t.fortuneOf(fc, "天蝎", fd);
if (JSON.stringify(f1) !== JSON.stringify(f2)) fails.push("同码同星座同日期批注不一致");
if (!(f1.stars >= 1 && f1.stars <= 5)) fails.push(`契合度星数越界：${f1.stars}`);
if (new Set(t.ZODIACS.map(z => JSON.stringify(t.fortuneOf(fc, z.name, fd)))).size < 2)
  fails.push("12 星座批注全部相同（异常）");

// 黄历确定性：同日期两次一致、宜 3 忌 2、宜忌不重叠、用词不出词池
const a1 = t.almanacOf(fd), a2 = t.almanacOf(fd);
if (JSON.stringify(a1) !== JSON.stringify(a2)) fails.push("黄历同日期两次计算不一致");
if (a1.yi.length !== 3 || a1.ji.length !== 2) fails.push("黄历宜忌数量不是 3 宜 2 忌");
if (a1.yi.some(w => a1.ji.includes(w))) fails.push("黄历宜忌重叠");
if (![...a1.yi, ...a1.ji].every(w => t.ALMANAC_POOL.includes(w))) fails.push("黄历用词超出词池");
if (t.ALMANAC_POOL.length !== 20) fails.push(`黄历词池不是 20 词：${t.ALMANAC_POOL.length}`);

// 星座加权：选天蝎抽 300 次，本命标签（暗黑/复仇/恐怖）题材占比 > 1.3 倍均匀期望
t.setZodiac("天蝎");
if (JSON.parse(localStorage.getItem("storyos_gacha_zodiac") || "null") !== "天蝎") fails.push("星座选择未持久化");
const scoTags = ["暗黑", "复仇", "恐怖"];
const scoIdx = new Set(D.genres.map((g, i) => g.tags.some(tg => scoTags.includes(tg)) ? i : -1).filter(i => i >= 0));
if (!scoIdx.size) fails.push("天蝎本命标签零命中题材（映射全落空）");
const TRIALS = 300;
let zHit = 0;
for (let i = 0; i < TRIALS; i++) if (scoIdx.has(t.pickGenre())) zHit++;
const uniExp = TRIALS * scoIdx.size / D.genres.length;
if (zHit <= uniExp * 1.3) fails.push(`天蝎加权不明显：命中 ${zHit}/${TRIALS}，均匀期望 ${uniExp.toFixed(1)}（要求 >1.3 倍）`);
else console.log(`ZODIAC-WEIGHT OK：天蝎抽 ${TRIALS} 次命中本命题材 ${zHit} 次，均匀期望 ${uniExp.toFixed(1)}（${(zHit / uniExp).toFixed(2)} 倍）`);
// 未选星座退化为均匀随机：命中不应显著超期望（粗检上限 1.6 倍，防卡死）
t.setZodiac(null);
if (localStorage.getItem("storyos_gacha_zodiac") !== null) fails.push("取消星座后 localStorage 未清除");
let z0 = 0;
for (let i = 0; i < TRIALS; i++) if (scoIdx.has(t.pickGenre())) z0++;
if (z0 > uniExp * 1.6) fails.push(`无星座时题材分布异常偏高：${z0}/${TRIALS}（期望 ${uniExp.toFixed(1)}）`);

// localStorage 抛错降级：抽卡/渲染/星座/收藏/记录面板全不崩
const realLS = { getItem: localStorage.getItem, setItem: localStorage.setItem, removeItem: localStorage.removeItem };
localStorage.getItem = () => { throw new Error("denied"); };
localStorage.setItem = () => { throw new Error("denied"); };
localStorage.removeItem = () => { throw new Error("denied"); };
try {
  t.state.locks = {};
  elements.get("rollBtn").onclick();
  t.render();
  t.setZodiac("白羊");
  t.setZodiac(null);
  t.toggleFav();
  t.renderRecList();
} catch (e) {
  fails.push("localStorage 抛错时主流程崩溃：" + (e && e.message));
}
Object.assign(localStorage, realLS);
localStorage.removeItem("storyos_gacha_history");
localStorage.removeItem("storyos_gacha_favs");
// 降级后渲染内容仍完整（最近一次 render 产物）
if (!elements.get("heroTitle")?.textContent) fails.push("localStorage 抛错降级后 hero 未渲染");

// 新 UI 渲染结果无 emoji（星号 ★☆ 特许）：批注/记录面板/黄历/星座 chips/折叠钮/星钮
t.setZodiac("天蝎");
t.render();
t.renderRecList();
const newUiHtml = ["fortune", "recList", "zodiacChips", "mysticToggle", "favBtn"]
  .map(id => elements.get(id)?.innerHTML || "").join("\n") + (elements.get("almanac")?.textContent || "");
if (EMOJI_RE.test(newUiHtml)) fails.push("新增 UI 渲染结果含 emoji");
if (!(elements.get("fortune")?.innerHTML || "").includes("★")) fails.push("批注区未渲染契合度星号");
t.setZodiac(null);

if (fails.length) {
  console.error("FAIL：\n- " + fails.join("\n- "));
  process.exit(1);
}
console.log("NODE SELFTEST OK：SELFTEST PASS 已输出、document.title 已置、hero/TAB/详情面板已渲染、开局码格式正确、副标题与页脚计数动态生成");
console.log("THEME OK：暗黑设计 token 就位，旧皮肤（橙/米色/衬线）与 emoji 零残留，按钮与 TAB 锁钮 SVG 图标渲染到位");
console.log("EXTRAS OK：toMarkdown 结构完整、五面板注释逐字一致、锁定 roll 语义正确、全锁 alert、坏码拒绝（含旧格式与越界下标）、大写码可还原、slug 残留零检出");
console.log("MYSTIC OK：黄历 3 宜 2 忌确定性且不重叠、批注 8 模板逐字+同码同星座同日期恒定、星座加权显著（未选退化均匀）、历史 50 封顶、收藏往返+100 封顶、还原不记历史、localStorage 抛错静默降级不崩");
