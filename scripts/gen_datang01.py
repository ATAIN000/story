"""大唐01 连续生成驱动：等当前章节完成 → 逐章生成到第 12 章。

同步调 POST /api/project/generate（阻塞到章节完成），失败重试 2 次。
进度写 logs/datang_progress.log，供外部检查。
"""
import json
import sys
import time
from pathlib import Path

import requests

BASE = "http://localhost:8111"
TARGET = 12
LOG = Path("logs/datang_progress.log")


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def gen_status():
    try:
        return requests.get(f"{BASE}/api/project/generation-status", timeout=30).json()
    except Exception as e:
        return {"error": str(e)}


def chapter_count():
    try:
        snap = requests.get(f"{BASE}/api/project", timeout=30).json()
        return snap["meta"]["chapter_count"]
    except Exception:
        return -1


def wait_idle(timeout_s=1800):
    """等当前生成完成（busy → False）。"""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        st = gen_status()
        if not st.get("busy"):
            return True
        time.sleep(15)
    return False


def generate_one(expected_ch):
    """同步生成一章。返回 (ok, detail)。"""
    try:
        r = requests.post(f"{BASE}/api/project/generate",
                          json={"mode": "auto"}, timeout=2400)
        if r.status_code == 200:
            return True, "ok"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)


def main():
    log(f"=== 开始：目标 {TARGET} 章 ===")
    # 1. 等当前章节（第 2 章）完成
    log("等当前生成完成...")
    if not wait_idle():
        log("超时：当前生成 30 分钟未完成，退出")
        sys.exit(1)
    log(f"当前完成，章节数={chapter_count()}")

    # 2. 逐章生成到 12
    while True:
        n = chapter_count()
        if n < 0:
            log("读取章节数失败，60s 后重试")
            time.sleep(60)
            continue
        if n >= TARGET:
            log(f"=== 完成：已达 {n} 章 ===")
            break
        next_ch = n + 1
        log(f"--- 生成第 {next_ch} 章 ---")
        ok = False
        for attempt in range(1, 3):
            ok, detail = generate_one(next_ch)
            if ok:
                log(f"第 {next_ch} 章完成（attempt {attempt}），现共 {chapter_count()} 章")
                break
            log(f"第 {next_ch} 章失败（attempt {attempt}）：{detail}")
            if not wait_idle():
                break
            time.sleep(10)
        if not ok:
            log(f"第 {next_ch} 章两次失败，终止")
            sys.exit(2)
        time.sleep(5)


if __name__ == "__main__":
    main()
