#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inject_tumor_to_inp.py

将球形肿瘤区域（材料900，含60ppm B-10的软组织）注入已有的MCNP5全身
体素 lattice 输入文件。

肿瘤球内的所有非空体素替换为 universe 900（肿瘤材料，高硼浓度），
同时在输入文件中补充 universe 900 单元卡和材料卡 m900。

用法:
    python inject_tumor_to_inp.py <inp_file> \
        --tx <x_cm> --ty <y_cm> --tz <z_cm> \
        --radius <r_cm> [--phantom-type AM|AF]

坐标以体模中心为原点（cm），与前端 dsPhantom.tumor_position 约定一致。
"""

import sys
import re
import json
import argparse
from pathlib import Path

import numpy as np

# ─────────────────────────────────────────────
# 肿瘤材料常数
# ─────────────────────────────────────────────
TUMOR_MAT_ID  = 900
TUMOR_DENSITY = 1.04   # g/cm³

# 单元卡（universe 900）
TUMOR_CELL_LINE = (
    f"{TUMOR_MAT_ID} {TUMOR_MAT_ID} -{TUMOR_DENSITY:.2f} -10  "
    f"u={TUMOR_MAT_ID}  imp:n=1  $ Tumor Tissue (B-10 loaded)\n"
)

# 材料卡 m900：ICRU-44 软组织基础 + 60 ppm B-10
# 组成与 icrp110_material_map._build_tumor_material() 保持一致
TUMOR_MAT_CARD = (
    f"c  M{TUMOR_MAT_ID}: Tumor Tissue (B-10 loaded), rho={TUMOR_DENSITY:.3f} g/cm3\n"
    f"m{TUMOR_MAT_ID}\n"
    "     1001.66c  -0.101940\n"   # H
    "     6000.66c  -0.142940\n"   # C（减去 60 ppm 以补偿 B-10 增加）
    "     7014.66c  -0.034968\n"   # N
    "     8016.66c  -0.708052\n"   # O
    "     5010.66c  -0.000060\n"   # B-10 (60 ppm)
    "     11023.66c -0.002000\n"   # Na
    "     15031.66c -0.003000\n"   # P
    "     16032.66c -0.003000\n"   # S
    "     17000.66c -0.002000\n"   # Cl (natural, consistent with ZAID_MAP)
    "     19000.66c -0.003000\n"   # K  (natural, consistent with ZAID_MAP)
    "c\n"
)


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────

def _parse_rpp(content: str, surface_num: int):
    """解析 'N RPP 0 xmax  0 ymax  0 zmax' 返回 (xmax, ymax, zmax)。"""
    pat = rf'{surface_num}\s+RPP\s+0\s+([\d.]+)\s+0\s+([\d.]+)\s+0\s+([\d.]+)'
    m = re.search(pat, content)
    if not m:
        raise ValueError(f"未找到曲面卡 {surface_num} RPP，请检查 .inp 文件格式")
    return float(m.group(1)), float(m.group(2)), float(m.group(3))


def _rebuild_fill_rows(fill: np.ndarray, nx: int, ny: int, nz: int) -> str:
    """
    将 fill 数组（shape = nz×ny×nx，Z 最外循环）重建为 MCNP lattice
    fill array 文本（每行 ≤78 字符，6 空格缩进）。
    """
    lines = []
    for k in range(nz):
        for j in range(ny):
            row_vals = [str(int(fill[k * ny * nx + j * nx + i])) for i in range(nx)]
            line = "      " + " ".join(row_vals)
            while len(line) > 78:
                cut = line.rfind(" ", 0, 78)
                if cut <= 6:
                    cut = 78
                lines.append(line[:cut])
                line = "      " + line[cut:].lstrip()
            lines.append(line)
    return "\n".join(lines)


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────

def inject_tumor(inp_path: str,
                 tx_rel: float, ty_rel: float, tz_rel: float,
                 radius: float,
                 phantom_type: str = 'AM') -> dict:
    """
    向 MCNP 输入文件注入肿瘤区域。

    Parameters
    ----------
    inp_path    : .inp 文件路径
    tx_rel, ty_rel, tz_rel : 肿瘤中心相对体模几何中心的坐标 (cm)
    radius      : 肿瘤等效球半径 (cm)
    phantom_type: 'AM' 或 'AF'

    Returns
    -------
    dict 包含 success, tumor_voxels_injected, tumor_center_abs
    """
    p = Path(inp_path)
    if not p.exists():
        raise FileNotFoundError(f"输入文件不存在: {inp_path}")

    content = p.read_text(encoding="ascii", errors="replace")

    # ---- 解析体素几何 ----
    dx, dy, dz      = _parse_rpp(content, 10)   # 单体素 RPP
    x_max, y_max, z_max = _parse_rpp(content, 20)  # 容器 RPP

    nx = round(x_max / dx)
    ny = round(y_max / dy)
    nz = round(z_max / dz)

    print(f"[肿瘤注入] 网格: {nx}×{ny}×{nz}, "
          f"体素: {dx:.4f}×{dy:.4f}×{dz:.4f} cm, "
          f"体模: {x_max:.2f}×{y_max:.2f}×{z_max:.2f} cm")

    # ---- 定位 fill array ----
    # 起始：fill=0:NX-1  0:NY-1  0:NZ-1\n
    # 结束：\nc\nc  Container
    fill_header_pat = re.compile(r"fill=0:\d+\s+0:\d+\s+0:\d+\n")
    fill_end_pat    = re.compile(r"\nc\nc\s+Container")

    fh_m = fill_header_pat.search(content)
    fe_m = fill_end_pat.search(content)

    if not fh_m or not fe_m:
        raise ValueError("无法在 .inp 文件中定位 fill array，请检查文件格式")

    fill_start = fh_m.end()
    fill_end   = fe_m.start()
    fill_text  = content[fill_start:fill_end]

    # ---- 解析 fill 值 ----
    vals     = list(map(int, fill_text.split()))
    expected = nx * ny * nz
    if len(vals) != expected:
        print(f"[警告] 期望 {expected} 个 fill 值，实际 {len(vals)} 个", file=sys.stderr)
        if len(vals) == 0:
            raise ValueError("fill array 为空")

    fill = np.array(vals, dtype=np.int32)

    # ---- 计算肿瘤中心绝对坐标 ----
    cx, cy, cz = x_max / 2.0, y_max / 2.0, z_max / 2.0
    tx_abs = cx + tx_rel
    ty_abs = cy + ty_rel
    tz_abs = cz + tz_rel
    r2     = radius * radius

    print(f"[肿瘤注入] 相对坐标: ({tx_rel}, {ty_rel}, {tz_rel}) cm")
    print(f"[肿瘤注入] 绝对坐标: ({tx_abs:.3f}, {ty_abs:.3f}, {tz_abs:.3f}) cm, "
          f"半径: {radius} cm")

    # ---- 遍历体素，标记肿瘤球内的非空体素 ----
    i_lo = max(0, int((tx_abs - radius) / dx))
    i_hi = min(nx - 1, int((tx_abs + radius) / dx) + 1)
    j_lo = max(0, int((ty_abs - radius) / dy))
    j_hi = min(ny - 1, int((ty_abs + radius) / dy) + 1)
    k_lo = max(0, int((tz_abs - radius) / dz))
    k_hi = min(nz - 1, int((tz_abs + radius) / dz) + 1)

    count = 0
    for k in range(k_lo, k_hi + 1):
        for j in range(j_lo, j_hi + 1):
            for i in range(i_lo, i_hi + 1):
                vx = (i + 0.5) * dx
                vy = (j + 0.5) * dy
                vz = (k + 0.5) * dz
                d2 = (vx - tx_abs)**2 + (vy - ty_abs)**2 + (vz - tz_abs)**2
                if d2 <= r2:
                    idx = k * ny * nx + j * nx + i
                    if 0 <= idx < len(fill) and fill[idx] > 0:  # 仅替换体内体素
                        fill[idx] = TUMOR_MAT_ID
                        count += 1

    print(f"[肿瘤注入] 注入了 {count} 个肿瘤体素 (材料 {TUMOR_MAT_ID})")

    if count == 0:
        print("[警告] 未注入任何肿瘤体素，请检查肿瘤位置是否在体模内", file=sys.stderr)
        # 仍继续，保证材料/单元卡的添加

    # ---- 重建 fill 文本 ----
    new_fill_text = _rebuild_fill_rows(fill, nx, ny, nz)

    # ---- 替换 fill array ----
    new_content = content[:fill_start] + new_fill_text + content[fill_end:]

    # ---- 添加 tumor universe 单元卡（若不存在）----
    if f"u={TUMOR_MAT_ID}" not in new_content:
        new_content = new_content.replace(
            "c\nc  Lattice cell\n",
            TUMOR_CELL_LINE + "c\nc  Lattice cell\n"
        )

    # ---- 添加材料卡 m900（若不存在）----
    if (f"m{TUMOR_MAT_ID}" not in new_content and
            f"M{TUMOR_MAT_ID}" not in new_content):
        # 插入到 nps 卡之前
        nps_m = re.search(r"^nps\s", new_content, re.MULTILINE)
        if nps_m:
            new_content = (
                new_content[:nps_m.start()] +
                TUMOR_MAT_CARD +
                new_content[nps_m.start():]
            )

    # ---- 写回文件 ----
    p.write_text(new_content, encoding="ascii")
    print(f"[肿瘤注入] 已写入修改后的输入文件: {inp_path}")

    return {
        "success": True,
        "tumor_voxels_injected": count,
        "tumor_center_abs": [tx_abs, ty_abs, tz_abs],
    }


# ─────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="向 MCNP5 全身体素 lattice 输入文件注入肿瘤区域（材料 900，含 B-10）"
    )
    parser.add_argument("inp_file", help="MCNP .inp 文件路径")
    parser.add_argument("--tx",     type=float, required=True,
                        help="肿瘤中心 X（cm，相对体模几何中心）")
    parser.add_argument("--ty",     type=float, required=True,
                        help="肿瘤中心 Y（cm，相对体模几何中心）")
    parser.add_argument("--tz",     type=float, required=True,
                        help="肿瘤中心 Z（cm，相对体模几何中心）")
    parser.add_argument("--radius", type=float, required=True,
                        help="肿瘤等效球半径（cm）")
    parser.add_argument("--phantom-type", default="AM", choices=["AM", "AF"])
    args = parser.parse_args()

    try:
        result = inject_tumor(
            args.inp_file,
            tx_rel=args.tx, ty_rel=args.ty, tz_rel=args.tz,
            radius=args.radius,
            phantom_type=args.phantom_type,
        )
        # 最后一行输出 JSON 供 Node.js 解析
        print(json.dumps(result))
        sys.exit(0)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)
