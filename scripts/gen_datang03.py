"""大唐03 连续生成驱动（前置约束改造验证用）：切到大唐03 → 逐章生成到 12 章。

控制变量：大唐03 复制大唐01 的题材/世界观/人物/宏观计划，由前置约束改造后
的系统生成——验证：实体前置注入后漂移是否源头减少、critic 合并/快速模式后
每章 LLM 调用数是否降、字数门是否在线拦。

进度写 logs/datang03_progress.log。
"""
import json
import sys
import time
from pathlib import Path

import requests

BASE = "http://localhost:8111"
TARGET = 12
PROJECT = "大唐03"
LOG = Path("logs/datang03_progress.log")


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def chapter_count():
    try:
        snap = requests.get(f"{BASE}/api/project", timeout=30).json()
        return snap["meta"]["chapter_count"]
    except Exception:
        return -1


def generate_one():
    try:
        r = requests.post(f"{BASE}/api/project/generate",
                          json={"mode": "auto"}, timeout=2400)
        if r.status_code == 200:
            return True, "ok"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)


def main():
    log(f"=== 开始：{PROJECT} 目标 {TARGET} 章 ===")
    r = requests.post(f"{BASE}/api/projects/open", json={"name": PROJECT},
                      timeout=30)
    if r.status_code != 200:
        log(f"切换项目失败：{r.status_code} {r.text[:200]}")
        sys.exit(1)
    log(f"已切换到 {PROJECT}，当前章节数={chapter_count()}")

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
            ok, detail = generate_one()
            if ok:
                log(f"第 {next_ch} 章完成（attempt {attempt}），现共 {chapter_count()} 章")
                break
            log(f"第 {next_ch} 章失败（attempt {attempt}）：{detail}")
            time.sleep(10)
        if not ok:
            log(f"第 {next_ch} 章两次失败，终止")
            sys.exit(2)
        time.sleep(5)


if __name__ == "__main__":
    main()
