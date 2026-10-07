"""开局抽卡导出脚本测试（spec: docs/superpowers/specs/2026-10-07-gacha-web-design.md）"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_JS = ROOT / "web" / "gacha" / "data.js"


def _run_export() -> dict:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_gacha_web.py")],
        check=True, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    text = DATA_JS.read_text(encoding="utf-8")
    m = re.fullmatch(r"window\.GACHA_DATA = (\{.*\});\n?", text, re.S)
    assert m, "data.js 必须是单行 window.GACHA_DATA = {...};"
    return json.loads(m.group(1))


def test_export_integrity():
    data = _run_export()
    yaml_count = len(list((ROOT / "story_engine" / "plugins" / "genres").glob("*.yaml")))
    assert len(data["genres"]) == yaml_count, "题材数必须等于 YAML 文件数"
    for g in data["genres"]:
        assert g["title"] and g["coreConflict"] and g["tracks"], g["id"]
        assert g["setting"] and g["characters"], g["id"]
    assert len(data["worldviews"]) == 10
    for w in data["worldviews"]:
        assert len(w["rules"]) >= 6, w["key"]
    assert len(data["skeletons"]) >= 30
    for s in data["skeletons"]:
        eps = [int(b["ep"]) for a in s["acts"] for b in a["beats"]]
        assert eps and all(1 <= e <= 12 for e in eps), s["id"]
    assert set(data["namePools"]) == {"cn", "jp", "western", "other"}
    assert "jianghu-martial" in data["culturePool"]
