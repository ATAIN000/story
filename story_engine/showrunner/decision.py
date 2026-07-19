"""决策卡与 10 步 control loop（Module 3 showrunner 子包）

多线叙事的核心是"状态外部化"：轨道进度/伏笔债/Sternberg主因/节奏
维护在显式数据结构里，不靠 LLM 注意力。

每集生成前产出决策卡（按蓝图 3.2 顺序的 10 步 control loop，全部规则化）：
  0. 节奏量化闭环（P3.4 — 上一章 PacingScore × pacing_targets → tension 修正）
  1. HTN 分解（P3.6 NarrativePlanner：Todorov 5 态 → genre phase_beats → 原语序列，
     输出挂 DecisionCard.plan_goals + beats[].primitives）
  2. 轨道调度（推进/种子/触碰/休眠）
  3. CFPG 伏笔查询（到期 payoff + 池上限 + 债务老化）
  4. Sternberg 三主因错峰（硬约束：同集唯一 / 同轨道连续两集不同）
  5. Yorke 分形 beat（macro 幕级 × micro 章级 双尺度）
  6. CONCOCT 具体度曲线（每 beat 一个 0-1 目标）
  7. McKee gap（按轨道原型的规则模板）
  8. Snyder 覆盖率（15 拍锚点 × target_length 进度映射）
  9. CFPG 池更新（满池排队 + pool_stats）
  10. 主题 touch（北极星轨道每集必触）
另有既有补充步骤（不在决策3表内，行为保持不变）：情感弧目标、集末钩子。
"""
from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field, asdict

from ..types import WorldState, GenreBundle
from ..creativity import (
    AuthorIntent, NarrativePlanner, StateView, state_view_from_world,
)
from .tracks import Track, ForeshadowPoolManager
from .pacing import (
    PacingEngine, chapter_events, resolve_targets,
    suggest_tension_adjustment, apply_tension_adjustment,
)

STERNBERG_MODES = ["suspense", "curiosity", "surprise"]
TODOROV_PHASES = ["equilibrium", "disruption", "recognition", "repair", "new_equilibrium"]

# Step 7 McKee gap：按轨道 archetype 的规则模板（取值集合以现有 genre 插件为准：
# mystery/romance/wuxia 中共出现 Quest/Monster/Tragedy/Rebirth 四种，
# 其余原型退回通用模板）
GAP_TEMPLATES = {
    "Quest": "接近目标时代价显现",
    "Monster": "威胁看似解除，实则逼近更深一层",
    "Tragedy": "挽回之举反而加速坠落",
    "Rebirth": "旧我惯性反扑，蜕变受阻",
}
GAP_TEMPLATE_DEFAULT = "读者预期 vs 实际发生的落差设计"


@dataclass
class DecisionCard:
    episode: int
    advance: list[str]
    seed: list[str]
    mid_touch: list[str]
    dormant: list[str]
    sternberg_distribution: dict[str, str]
    active_payoffs: list[dict]
    beats: list[dict]
    snyder_coverage: dict[str, bool]
    target_arc: str
    gaps: list[str]
    ending_hook: dict
    theme_touch: bool
    new_foreshadows: list[dict]
    # ---- P3.3 新增（只增不改）----
    plan_goals: list[dict] = field(default_factory=list)      # Step 1 占位：P3.6 planner 输出
    concreteness_curve: list[float] = field(default_factory=list)  # Step 6 CONCOCT
    pool_stats: dict = field(default_factory=dict)            # Step 9 {active, overdue, queued}
    queued_foreshadows: list[dict] = field(default_factory=list)   # Step 9 满池排队
    pacing: dict | None = None                                # P3.4 填
    creative_seeds: list[dict] = field(default_factory=list)  # P3.7 填

    def to_dict(self) -> dict:
        return asdict(self)


class Showrunner:
    def __init__(self, bundle: GenreBundle,
                 event_source: Callable[[], list[dict]] | None = None):
        self.bundle = bundle
        self.genre = bundle.genre_params
        self.culture = bundle.culture_params
        self.target_length = max(1, bundle.target_length)
        self.tracks: dict[str, Track] = {}
        for t in self.genre.get("tracks", []):
            self.tracks[t["id"]] = Track(**t)
        self.pool = ForeshadowPoolManager(
            pool_max=self.genre.get("foreshadow_pool_max", 8),
            payoff_window=self.genre.get("payoff_window", 2))
        # P3.4：节奏量化闭环（事件源可选；无源时 pacing 保持 None）
        self._pacing = PacingEngine()
        self._event_source = event_source
        # P3.6：NarrativePlanner（决策6，纯规则无 LLM），_plan_beats 调用
        self._planner = NarrativePlanner()
        # Sternberg 历史（{集号: {track_id: 模式}}）：NarrativeState 尚无该历史字段，
        # 最小改动为由 Showrunner 实例自持；历史不可得（首集/重启）时按轮换逻辑即可
        self._sternberg_history: dict[int, dict[str, str]] = {}

    def generate_decision_card(self, episode: int, state: WorldState) -> DecisionCard:
        # Step 0（P3.4 决策4）：上一章节奏量化 → PacingScore × pacing_targets → tension 修正
        pacing = self._pacing_feedback(episode)

        # Step 1: HTN 分解 — 由 NarrativePlanner 承担（P3.6）；章级 intent 依赖
        #         Step 2 的 advance 轨道，故实际分解在 _plan_beats（Step 5）执行，
        #         planner 输出的 goal 轨迹在此回填并挂 DecisionCard.plan_goals
        plan_goals: list[dict] = []

        # Step 2: 轨道调度 — 主线必推进；副线按激活条件+最久未触碰轮换
        main_prog = state.narrative.track_progress.get(
            self.genre.get("main_track", "A"), 0.0)
        advance, seed, mid_touch, dormant = self._schedule(episode, main_prog)

        # Step 3: CFPG 伏笔查询 — 到期 payoff + 债务老化（overdue/priority 升级）
        active_payoffs = self.pool.due_payoffs(
            state.narrative.foreshadow_pool, episode)

        # Step 4: Sternberg 三主因错峰（硬约束：同集唯一；同轨道连续两集不同）
        sternberg = self._sternberg_assign(episode, advance + mid_touch)

        # Step 5: beat 规划（Yorke 分形：macro 幕级 × micro 章级；
        #         P3.6 叠加 NarrativePlanner 原语序列 → beats/primitives + plan_goals）
        beats, plan_goals = self._plan_beats(episode, advance, state)
        if pacing:  # P3.4：用上一章节奏偏差修正本章 beat tension 曲线
            beats = apply_tension_adjustment(beats, pacing["tension_adjustment"])

        # Step 6: CONCOCT — 每 beat 一个 0-1 具体度目标
        concreteness_curve = self._concreteness_curve(len(beats))

        # Step 7: McKee gap — 按轨道 archetype 的规则模板 + 上章场景
        gaps = self._mckee_gaps(advance, state)

        # Step 8: Snyder 覆盖率（15 拍锚点按 episode/target_length 进度映射）
        snyder = self._snyder_coverage(episode)

        # Step 9: CFPG 池更新 — 新伏笔计划受池容量约束，满池排队
        plans = self._plan_new_foreshadows(episode, seed)
        new_foreshadows, queued = self.pool.split_plans(
            state.narrative.foreshadow_pool, plans)
        pool_stats = self.pool.stats(
            state.narrative.foreshadow_pool, episode, queued)

        # Step 10: 主题 touch（北极星轨道每集必触）
        theme_track = self.genre.get("theme_track", "E")
        theme_touch = theme_track in (advance + mid_touch)

        # 既有补充（不在决策3表内，保持不变）：情感弧目标 + 集末钩子
        arcs = self.genre.get("emotion_arcs", ["man_in_hole"])
        target_arc = arcs[episode % len(arcs)]
        ending_hook = self._ending_hook(episode)

        return DecisionCard(
            episode=episode, advance=advance, seed=seed, mid_touch=mid_touch,
            dormant=dormant, sternberg_distribution=sternberg,
            active_payoffs=active_payoffs, beats=beats,
            snyder_coverage=snyder, target_arc=target_arc, gaps=gaps,
            ending_hook=ending_hook, theme_touch=theme_touch,
            new_foreshadows=new_foreshadows,
            plan_goals=plan_goals, concreteness_curve=concreteness_curve,
            pool_stats=pool_stats, queued_foreshadows=queued,
            pacing=pacing,
        )

    # ---------- P3.4: 节奏量化闭环（决策4） ----------
    def _pacing_feedback(self, episode: int) -> dict | None:
        """上一章 PacingScore × pacing_targets → 本章 tension 修正参数。
        首集 / 无事件源 / 空事件流时返回 None（DecisionCard.pacing 保持 None）"""
        if episode <= 1 or self._event_source is None:
            return None
        # all_events 含已回滚时间线，只取 active 事件
        events = [e for e in self._event_source() if e.get("active", True)]
        prev_events = chapter_events(events, episode)
        if not prev_events:
            return None
        report = self._pacing.analyze(prev_events)
        if report is None:
            return None
        targets = resolve_targets(self.genre.get("pacing_targets"))
        adjustment = suggest_tension_adjustment(report["score"], targets)
        return {
            "measured_episode": episode - 1,
            "score": report["score"].to_dict(),
            "metrics": report["metrics"],
            "targets": {k: [lo, hi] for k, (lo, hi) in targets.items()},
            "deviations": adjustment["deviations"],
            "tension_adjustment": {
                "variance_scale": adjustment["variance_scale"],
                "ending_boost": adjustment["ending_boost"],
            },
        }

    # ---------- Step 2: 轨道调度 ----------
    def _schedule(self, episode: int, main_prog: float):
        main = self.genre.get("main_track", "A")
        theme = self.genre.get("theme_track", "E")
        advance = [main]
        # 副线轮换：满足激活条件（主线进度阈值）的轨道里，挑最久未碰的
        sides = [t for tid, t in self.tracks.items() if tid not in (main, theme)]
        eligible = [t for t in sides if main_prog >= t.min_main_progress]
        if eligible:
            stalest = min(eligible, key=lambda t: t.last_touched)
            advance.append(stalest.id)
        mid_touch = [theme]
        seed_pool = [t for t in eligible if t.id not in advance]
        seed = [seed_pool[episode % len(seed_pool)].id] if seed_pool else []
        dormant = [tid for tid in self.tracks
                   if tid not in advance + mid_touch + seed]
        for tid in advance + mid_touch:
            self.tracks[tid].last_touched = episode
        return advance, seed, mid_touch, dormant

    # ---------- Step 4: Sternberg 硬约束 ----------
    def _sternberg_assign(self, episode: int, track_ids: list[str]) -> dict[str, str]:
        """同集模式唯一（>3 轨道按调度优先级取前 3）；同轨道连续两集不同模式"""
        chosen = track_ids[:3]
        if not chosen:
            return {}
        # 与最近的上一集模式比较（同集重复生成时仍对齐上一集，幂等）
        prev_eps = [e for e in self._sternberg_history if e < episode]
        prev = self._sternberg_history[max(prev_eps)] if prev_eps else {}
        # 既有轮换基线：无历史时保持旧行为
        base = [STERNBERG_MODES[(episode + i) % 3] for i in range(len(chosen))]
        best, best_score = None, None
        for perm in itertools.permutations(STERNBERG_MODES, len(chosen)):
            violations = sum(
                1 for t, m in zip(chosen, perm)
                if prev.get(t) == m)
            drift = sum(1 for i, m in enumerate(perm) if m != base[i])
            score = (violations, drift)  # 先满足连续约束，再贴近轮换基线
            if best_score is None or score < best_score:
                best, best_score = dict(zip(chosen, perm)), score
            if score == (0, 0):
                break
        self._sternberg_history[episode] = best
        # 只保留最近两集，避免无限增长
        for e in [e for e in self._sternberg_history if e < episode - 1]:
            del self._sternberg_history[e]
        return best

    # ---------- Step 5: 分形 beat ----------
    def _macro_phase(self, episode: int) -> str:
        """幕级 Todorov：episode/target_length 比例五等分映射"""
        idx = min(int(episode / self.target_length * len(TODOROV_PHASES)),
                  len(TODOROV_PHASES) - 1)
        return TODOROV_PHASES[idx]

    def _plan_beats(self, episode: int, advance: list[str],
                    state: WorldState | None = None) -> tuple[list[dict], list[dict]]:
        """Yorke 分形 beat（旧逻辑保留）+ P3.6 NarrativePlanner 原语序列。

        返回 (beats, plan_goals)：beat dict 新增 `primitives` 摘要键（按 micro_phase
        对齐 planner 各 Todorov 态的原语类名）；plan_goals 为 planner 的 goal 轨迹。
        """
        n_beats = self.genre.get("beats_per_chapter", 4)
        macro = self._macro_phase(episode)
        beats = []
        for i in range(n_beats):
            micro = TODOROV_PHASES[min(i * len(TODOROV_PHASES) // n_beats,
                                       len(TODOROV_PHASES) - 1)]
            track = advance[i % len(advance)]
            beats.append({
                "beat_id": f"ep{episode}_b{i+1}",
                "phase": micro,          # 旧键保留（前端在用），等价 micro_phase
                "micro_phase": micro,    # 章级（现有逻辑）
                "macro_phase": macro,    # 幕级（episode/target_length）
                "track": track,
                "track_name": self.tracks[track].name,
                "tension": round(0.35 + 0.55 * (i + 1) / n_beats, 2),
            })

        # ---- P3.6 决策6：advance 轨道章级 intent（决策卡步骤 1 构造）→ planner ----
        intent = AuthorIntent(
            text=f"第{episode}章推进：{'、'.join(self.tracks[t].name for t in advance)}",
            metadata={"episode": episode, "macro_phase": macro,
                      "tracks": list(advance)})
        view = state_view_from_world(state) if state is not None else StateView()
        primitives, trace = self._planner.plan_with_trace(
            intent, self.bundle, state_view=view)
        names_by_phase: dict[str, list[str]] = {}
        for p in primitives:
            names_by_phase.setdefault(getattr(p, "phase", "") or "", []) \
                .append(p.__class__.__name__)
        for b in beats:
            b["primitives"] = names_by_phase.get(b["micro_phase"], [])
        return beats, trace["goals"]

    # ---------- Step 6: CONCOCT ----------
    def _concreteness_curve(self, n_beats: int) -> list[float]:
        """每 beat 一个 0-1 具体度目标；genre params `concreteness_shape`
        可选 rising/valley/peak，默认 rising"""
        if n_beats <= 0:
            return []
        shape = self.genre.get("concreteness_shape", "rising")
        xs = [i / (n_beats - 1) for i in range(n_beats)] if n_beats > 1 else [0.5]
        curve = []
        for x in xs:
            if shape == "peak":
                v = 0.3 + 0.6 * (1 - abs(2 * x - 1))
            elif shape == "valley":
                v = 0.3 + 0.6 * abs(2 * x - 1)
            else:  # rising（含未知 shape 的兜底）
                v = 0.3 + 0.6 * x
            curve.append(round(v, 2))
        return curve

    # ---------- Step 7: McKee gap ----------
    def _mckee_gaps(self, advance: list[str], state: WorldState) -> list[str]:
        """每条推进轨道：按 archetype 选 gap 模板，结合上一章场景生成具体描述"""
        last_scene = state.narrative.current_scene
        gaps = []
        for tid in advance:
            track = self.tracks[tid]
            template = GAP_TEMPLATES.get(track.archetype, GAP_TEMPLATE_DEFAULT)
            context = f"（承接上章「{last_scene}」）" if last_scene else ""
            gaps.append(f"{track.name}：{template}{context}")
        return gaps

    # ---------- Step 8: Snyder 覆盖 ----------
    def _snyder_coverage(self, episode: int) -> dict[str, bool]:
        anchors = ["开场画面", "主题呈现", "铺垫", "催化剂", "争执", "进入第二幕",
                   "B故事", "游戏时间", "中点", "坏人逼近", "一无所有",
                   "灵魂黑夜", "进入第三幕", "结局", "终场画面"]
        covered = {}
        for i, a in enumerate(anchors):
            # 按 target_length 进度比例映射：末集全覆盖
            covered[a] = (i + 1) * self.target_length / len(anchors) <= episode
        return covered

    # ---------- Step 9: 新伏笔计划 ----------
    def _plan_new_foreshadows(self, episode: int, seed: list[str]) -> list[dict]:
        templates = self.genre.get("foreshadow_templates", [])
        plans = []
        for i, tid in enumerate(seed):
            if i < len(templates):
                t = templates[(episode + i) % len(templates)]
                plans.append({"track": tid, **t})
        return plans

    # ---------- 集末钩子（既有补充） ----------
    def _ending_hook(self, episode: int) -> dict:
        styles = self.culture.get("cliffhanger_cycle",
                                  ["明扣", "暗扣", "留扣", "拴马扣"])
        style = styles[episode % len(styles)]
        return {"style": style,
                "periodic": episode % 3 == 0 and "留扣" or episode % 5 == 0 and "拴马扣" or "常规",
                "desc": f"以「{style}」收束本章"}
