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
      });
    }
    return elements.get(id);
  },
  createElement() {
    return { click() {}, href: "", download: "" };
  },
  title: "",
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
  (0, eval)(pageJs + "\n;globalThis.__t = {toMarkdown, roll, decode, encode, state, BLOCKS, buildModel, render, switchTab};");
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

// 数据卫生断言：50 组随机码 × 5 个 tab 的渲染结果中不得有 slug 残留
// （tags/setting/characters 展示区不出现 [a-z]+_[a-z]+ 模式与已知内部代号）
const SLUG_RE = /[a-z]+_[a-z]+/;
const KNOWN_SLUGS = /modern-chinese-urban|infinite_flow|dungeon_loop|hard_reality|western_fantasy|xianxia_cultivation|post_apocalyptic/;
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
    const m1 = r.match(SLUG_RE), m2 = r.match(KNOWN_SLUGS);
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

if (fails.length) {
  console.error("FAIL：\n- " + fails.join("\n- "));
  process.exit(1);
}
console.log("NODE SELFTEST OK：SELFTEST PASS 已输出、document.title 已置、hero/TAB/详情面板已渲染、开局码格式正确、副标题与页脚计数动态生成");
console.log("EXTRAS OK：toMarkdown 结构完整、五面板注释逐字一致、锁定 roll 语义正确、全锁 alert、坏码拒绝（含旧格式与越界下标）、大写码可还原、slug 残留零检出");
