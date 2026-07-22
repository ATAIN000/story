"""loguru 日志配置（Phase 16）

- 控制台：彩色 INFO，含 trace_id 字段（便于单章全链路 grep）
- 文件：logs/story_engine.log，按天轮转保留 7 天，DEBUG 级别
  （捕获完整 LLM prompt/response 全文）
- InterceptHandler：拦截所有 stdlib ``logging.getLogger`` 调用转发到 loguru，
  现有 10+ 处 ``logger = logging.getLogger(__name__)`` 零改动继续工作
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger

# 统一日志格式（trace_id 缺省 "-"，bind(trace_id=...) 后显示实际值）
_FMT = ("{time:HH:mm:ss} | {level: <5} | {extra[trace_id]:>15} | "
        "{name}:{function}:{line} | {message}")

_FILE_FMT = ("{time:YYYY-MM-DD HH:mm:ss} | {level: <5} | {extra[trace_id]:>15} | "
             "{name}:{function}:{line} | {message}")


class InterceptHandler(logging.Handler):
    """stdlib logging → loguru 转发桥。

    所有 ``logging.getLogger(name)`` 的日志记录经 ``emit`` 转成 loguru 级别
    并经 ``logger.opt(...)`` 回放（保留模块名/行号/异常栈），现有调用点零改动。
    """

    def emit(self, record: logging.LogRecord) -> None:
        # stdlib level → loguru level 名
        try:
            level: str | int = logger.level(record.levelname).name
        except (ValueError, AttributeError):
            level = record.levelno
        # 找到真实调用栈深度（跳过 logging 内部帧）
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage())


def setup_logging(level: str = "INFO") -> None:
    """配置 loguru 日志（幂等：重复调用先清旧 handler）。

    - 控制台：彩色，level（默认 INFO；测试环境传 WARNING 减噪）
    - 文件：``logs/story_engine.log``，rotation="1 day"，retention="7 days"，
      DEBUG 级别（捕获完整 LLM prompt/response 全文），utf-8
    - 拦截 stdlib logging（InterceptHandler），现有 getLogger 调用零改动
    - 给所有日志记录注入默认 ``extra[trace_id]="-"``，引擎内 bind 后显示实际值
    """
    logger.remove()
    logger.configure(extra={"trace_id": "-"})

    logger.add(
        sys.stderr, level=level, format=_FMT, colorize=True, backtrace=False,
        diagnose=False)
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(log_dir / "story_engine.log"),
        level="DEBUG", format=_FILE_FMT, encoding="utf-8",
        rotation="1 day", retention="7 days", backtrace=True, diagnose=True)

    # 拦截 stdlib logging（现有 logging.getLogger 调用零改动）
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
