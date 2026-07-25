#!/usr/bin/env python3
"""从 docs/logo.png 生成多尺寸 favicon（圆角 + 透明边距）。

用法： python scripts/make_favicon.py
产物写入 frontend/public/：
  - favicon.ico     浏览器 tab（多尺寸打包：16/32/48）
  - apple-touch-icon.png   iOS / 桌面快捷方式（180，圆角）
  - favicon-32.png         通用 32 备用

设计：原 logo 是填满画布的深色方块，直接当 favicon 边缘生硬。
本脚本把内容缩到 ~82%、四周加透明 padding、再做圆角遮罩，
让浏览器 tab / 书签栏里显示为「带圆角的浮动图标」而非黑方块。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

# 仓库根 = story-engine/ 本身；docs/logo.png 在上一层（story os/docs/）。
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT.parent / "docs" / "logo.png"
OUT = ROOT / "frontend" / "public"

# 内容相对画布的占比 + 圆角比例。82% 内容 / 22% 圆角半径 = 视觉舒适。
CONTENT_RATIO = 0.82
CORNER_RATIO = 0.22


def rounded_mask(size: int, radius: int) -> Image.Image:
    """返回 L 模式圆角矩形遮罩（不透明区域为圆角方块）。"""
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [(0, 0), (size - 1, size - 1)], radius=radius, fill=255
    )
    return mask


def render(size: int) -> Image.Image:
    """生成指定尺寸的圆角 + 透明 padding 图标。"""
    src = Image.open(SRC).convert("RGBA")
    # 内容缩放到 CONTENT_RATIO，再居中贴到透明画布
    inner = int(round(size * CONTENT_RATIO))
    src_resized = src.resize((inner, inner), Image.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = ((size - inner) // 2, (size - inner) // 2)
    canvas.paste(src_resized, offset)

    # 圆角遮罩：让整张图边缘圆角 + 周围透明
    radius = int(round(size * CORNER_RATIO))
    mask = rounded_mask(size, radius)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(canvas, (0, 0), mask)
    return out


def main() -> int:
    if not SRC.exists():
        print(f"[err] 源图不存在：{SRC}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    # favicon.ico：16/32/48 多尺寸打包（浏览器按需取最合适的一档）
    ico_sizes = [(16, 16), (32, 32), (48, 48)]
    ico_images = [render(s) for s, _ in ico_sizes]
    (OUT / "favicon.ico").write_bytes(b"")  # 占位，确保路径可写
    ico_images[0].save(
        OUT / "favicon.ico",
        format="ICO",
        sizes=ico_sizes,
    )

    # apple-touch-icon：iOS 会自己圆角，但仍加 padding 避免顶满
    render(180).save(OUT / "apple-touch-icon.png", format="PNG")

    # 通用 32 备用
    render(32).save(OUT / "favicon-32.png", format="PNG")

    print(f"[ok] 生成完成 → {OUT}")
    for f in ["favicon.ico", "apple-touch-icon.png", "favicon-32.png"]:
        p = OUT / f
        print(f"  {f}  {p.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
