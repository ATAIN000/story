"""genre 包运行时校验（H7 检查集）——抽卡 synth/confirm 与后续批量导入共用"""
import re

ARCHETYPES = {"Quest", "Monster", "Tragedy", "Rebirth"}
PRIMITIVES = {"Conflict", "Suspense", "TurningPoint", "Revelation",
              "Sacrifice", "Betrayal", "Recognition", "GoalFormation"}
FACTS = {"has_supernatural", "is_resolution", "narrator_is_killer",
         "case_age_days", "introduces_new_key_clue"}
KNOWN_CRITICS = {"plot_coherence", "character_motivation", "setting_consistency",
                 "dialogue_authenticity", "sensory_detail", "cliche_detection",
                 "theme_depth", "emotion_arc"}
TRACK_KEYS = {"id", "name", "arc_type", "archetype", "progress", "last_touched"}
PHASES = {"equilibrium", "disruption", "recognition", "repair", "new_equilibrium"}
IDENT_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

def validate_genre_pack(d: dict) -> list[str]:
    errs: list[str] = []
    params = d.get("params")
    if not isinstance(params, dict):
        return ["缺 params 段"]
    tracks = params.get("tracks") or []
    if len(tracks) < 3:
        errs.append(f"tracks 需 ≥3 条（当前 {len(tracks)}）")
    ids = set()
    for t in tracks:
        if not TRACK_KEYS <= set(t):
            errs.append(f"轨道 {t.get('id','?')} 缺键（需 {sorted(TRACK_KEYS)}）")
        ids.add(t.get("id"))
        if t.get("archetype") not in ARCHETYPES:
            errs.append(f"轨道 {t.get('id','?')} archetype 非法：{t.get('archetype')}")
    for k in ("main_track", "theme_track"):
        if params.get(k) not in ids:
            errs.append(f"{k} 必须指向真实轨道 id")
    bpc = params.get("beats_per_chapter")
    if not isinstance(bpc, int) or not 3 <= bpc <= 6:
        errs.append("beats_per_chapter 需为 3-6 的整数")
    if not isinstance(params.get("payoff_window"), int) or params["payoff_window"] < 1:
        errs.append("payoff_window 需为 ≥1 的整数")
    prompt = params.get("prompt") or {}
    for k in ("role", "setting", "characters", "style", "hard_requirements"):
        if k not in prompt:
            errs.append(f"prompt 段缺 {k} 键")
    beats = params.get("phase_beats") or {}
    if set(beats) != PHASES:
        errs.append(f"phase_beats 需含 5 相 {sorted(PHASES)}")
    for ph, bl in beats.items():
        for b in (bl or []):
            if b.get("primitive") not in PRIMITIVES:
                errs.append(f"phase_beats.{ph} 含非法 primitive：{b.get('primitive')}")
    for r in (params.get("world_rules") or []):
        for tok in IDENT_RE.findall(r.get("expr") or ""):
            if tok not in FACTS | {"not", "and", "or", "true", "false"}:
                errs.append(f"world_rules[{r.get('id','?')}] expr 超词汇表：{tok}")
    w = params.get("evaluation_weights") or {}
    if abs(sum(w.values()) - 1.0) > 0.01:
        errs.append(f"evaluation_weights 和={sum(w.values()):.3f} ≠ 1.0")
    for c in (params.get("active_critics") or []):
        if c not in KNOWN_CRITICS:
            errs.append(f"active_critics 未知维度：{c}")
    return errs
