# -*- coding: utf-8 -*-
"""像素级截图比对（自实现，避免引入 pytest-playwright）。

- 比对策略：逐像素 RGB 差，单像素阈值 ``pixel_tol``；累计差异像素占比 ``ratio_tol``。
- 不一致时落盘 diff 图（红色高亮差异区域），方便人工 review。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops


@dataclass
class DiffResult:
    ok: bool
    diff_pixels: int
    total_pixels: int
    diff_ratio: float
    detail: str
    diff_path: Path | None = None


def compare(
    baseline: Path,
    current: Path,
    diff_path: Path,
    pixel_tol: int = 8,
    ratio_tol: float = 0.005,
) -> DiffResult:
    if not baseline.exists():
        return DiffResult(False, 0, 0, 0.0, f"baseline missing: {baseline}")
    a = Image.open(baseline).convert("RGB")
    b = Image.open(current).convert("RGB")
    if a.size != b.size:
        return DiffResult(
            False, 0, 0, 0.0,
            f"size mismatch baseline={a.size} current={b.size}",
        )
    delta = ImageChops.difference(a, b)
    bbox = delta.getbbox()
    if bbox is None:
        return DiffResult(True, 0, a.size[0] * a.size[1], 0.0, "identical")

    px_a = a.load()
    px_b = b.load()
    diff_count = 0
    width, height = a.size
    diff_img = Image.new("RGB", a.size)
    diff_px = diff_img.load()
    for y in range(height):
        for x in range(width):
            r1, g1, b1 = px_a[x, y]
            r2, g2, b2 = px_b[x, y]
            if (
                abs(r1 - r2) > pixel_tol
                or abs(g1 - g2) > pixel_tol
                or abs(b1 - b2) > pixel_tol
            ):
                diff_count += 1
                diff_px[x, y] = (255, 0, 0)
            else:
                avg = (r1 + g1 + b1) // 3
                gray = avg // 2 + 64
                diff_px[x, y] = (gray, gray, gray)

    total = width * height
    ratio = diff_count / total
    ok = ratio <= ratio_tol
    if not ok:
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_img.save(diff_path)
        detail = (
            f"diff ratio={ratio:.4%} (>{ratio_tol:.4%}) "
            f"pixels={diff_count}/{total} diff_img={diff_path}"
        )
        return DiffResult(False, diff_count, total, ratio, detail, diff_path)
    return DiffResult(
        True, diff_count, total, ratio,
        f"within tolerance ({ratio:.4%} <= {ratio_tol:.4%})",
    )