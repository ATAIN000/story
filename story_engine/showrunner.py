"""Showrunner — 多轨道调度器（Module 3）

多线叙事的核心是"状态外部化"：轨道进度/伏笔债/Sternberg主因/节奏
维护在显式数据结构里，不靠 LLM 注意力。

每集生成前产出决策卡（10步 control loop 的精简实现）：
  1. 轨道调度（推进/种子/触碰/休眠）  2. CFPG 伏笔查询（到期 payoff）
  3. Sternberg 三主因错峰             4. beat 规划（Todorov 5态×Genre）
  5. 情感弧目标                       6. Snyder 覆盖率
  7. McKee gap 提示                   8. 伏笔池更新计划
  9. 集末钩子（文化插件）             10. 主题 touch 检查
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from .types import WorldState, ForeshadowTriple

STERNBERG_MODES = ["suspense", "curiosity", "surprise"]
TODOROV_PHASES = ["equilibrium", "disruption", "recognition", "repair", "new_equilibrium"]


@dataclass
class Track:
    id: str
    name: str
    arc_type: str          # Serialized / Anthology
    archetype: str
    progress: float = 0.0
    last_touched: int = 0  # chapter
    min_main_progress: float = 0.0   # 激活条件：主线进度达到该阈值才进入轮换


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

    def to_dict(self) -> dict:
        return asdict(self)


class Showrunner:
    def __init__(self, genre_params: dict, culture_params: dict):
        self.genre = genre_params
        self.culture = culture_params
        self.tracks: dict[str, Track] = {}
        for t in genre_params.get("tracks", []):
            self.tracks[t["id"]] = Track(**t)

    def generate_decision_card(self, episode: int, state: WorldState) -> DecisionCard:
        pool = state.narrative.foreshadow_pool

        # Step 1: 轨道调度 — 主线必推进；副线按激活条件+最久未触碰轮换
        main_prog = state.narrative.track_progress.get(
            self.genre.get("main_track", "A"), 0.0)
        advance, seed, mid_touch, dormant = self._schedule(episode, main_prog)

        # Step 2: CFPG 伏笔查询 — 到期的 payoff（种满 N 章即到期）
        payoff_window = self.genre.get("payoff_window", 2)
        active_payoffs = [
            {"foreshadow_id": fs.foreshadow_id, "content": fs.content,
             "payoff": fs.payoff, "trigger": fs.trigger_condition,
             "planted_chapter": fs.planted_chapter}
            for fs in pool
            if not fs.payed_off and episode - fs.planted_chapter >= payoff_window
        ]

        # Step 3: Sternberg 三主因错峰（同集不同模式，逐集轮换）
        sternberg = {}
        for i, tid in enumerate(advance + mid_touch):
            sternberg[tid] = STERNBERG_MODES[(episode + i) % 3]

        # Step 4: beat 规划（Todorov 5态 × Genre 每章 beat 数）
        beats = self._plan_beats(episode, advance)

        # Step 5: 情感弧目标（Reagan 6弧轮换）
        arcs = self.genre.get("emotion_arcs", ["man_in_hole"])
        target_arc = arcs[episode % len(arcs)]

        # Step 6: Snyder 覆盖率（按章进度映射 15 拍锚点）
        snyder = self._snyder_coverage(episode)

        # Step 7: McKee gap 提示（每条推进轨道给一个预期违反点）
        gaps = [f"{self.tracks[t].name}：读者预期 vs 实际发生的落差设计" for t in advance]

        # Step 8: 本集新伏笔计划（seed 轨道各种一个）
        new_foreshadows = self._plan_new_foreshadows(episode, seed)

        # Step 9: 集末钩子（文化插件：评书扣子轮换）
        ending_hook = self._ending_hook(episode)

        # Step 10: 主题 touch（北极星轨道每集必触）
        theme_track = self.genre.get("theme_track", "E")
        theme_touch = theme_track in (advance + mid_touch)

        return DecisionCard(
            episode=episode, advance=advance, seed=seed, mid_touch=mid_touch,
            dormant=dormant, sternberg_distribution=sternberg,
            active_payoffs=active_payoffs, beats=beats,
            snyder_coverage=snyder, target_arc=target_arc, gaps=gaps,
            ending_hook=ending_hook, theme_touch=theme_touch,
            new_foreshadows=new_foreshadows,
        )

    # ---------- 内部 ----------
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

    def _plan_beats(self, episode: int, advance: list[str]) -> list[dict]:
        n_beats = self.genre.get("beats_per_chapter", 4)
        beats = []
        for i in range(n_beats):
            phase = TODOROV_PHASES[min(i * len(TODOROV_PHASES) // n_beats,
                                       len(TODOROV_PHASES) - 1)]
            track = advance[i % len(advance)]
            beats.append({
                "beat_id": f"ep{episode}_b{i+1}",
                "phase": phase,
                "track": track,
                "track_name": self.tracks[track].name,
                "tension": round(0.35 + 0.55 * (i + 1) / n_beats, 2),
            })
        return beats

    def _snyder_coverage(self, episode: int) -> dict[str, bool]:
        anchors = ["开场画面", "主题呈现", "铺垫", "催化剂", "争执", "进入第二幕",
                   "B故事", "游戏时间", "中点", "坏人逼近", "一无所有",
                   "灵魂黑夜", "进入第三幕", "结局", "终场画面"]
        per = max(1, len(anchors) // 12)
        covered = {}
        for i, a in enumerate(anchors):
            covered[a] = (i // per) < episode
        return covered

    def _plan_new_foreshadows(self, episode: int, seed: list[str]) -> list[dict]:
        templates = self.genre.get("foreshadow_templates", [])
        plans = []
        for i, tid in enumerate(seed):
            if i < len(templates):
                t = templates[(episode + i) % len(templates)]
                plans.append({"track": tid, **t})
        return plans

    def _ending_hook(self, episode: int) -> dict:
        styles = self.culture.get("cliffhanger_cycle",
                                  ["明扣", "暗扣", "留扣", "拴马扣"])
        style = styles[episode % len(styles)]
        return {"style": style,
                "periodic": episode % 3 == 0 and "留扣" or episode % 5 == 0 and "拴马扣" or "常规",
                "desc": f"以「{style}」收束本章"}
