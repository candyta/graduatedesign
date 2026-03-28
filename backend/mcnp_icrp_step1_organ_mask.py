#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCNP ICRP-110 验证 — 第一步：生成器官掩膜
============================================
从 AM.zip 读取体模数据，生成降采样的器官掩膜数组，
为后续 MCNP5 输入生成和剂量分析提供基础。

输出:
  organ_mask_127x63x111.npy   — 器官ID掩膜（uint8，降采样后）
  organ_mask_meta.json        — 器官组定义 + 密度映射 + 体素尺寸

运行方式:
  python mcnp_icrp_step1_organ_mask.py
  python mcnp_icrp_step1_organ_mask.py --data-zip "P110 data V1.2/AM.zip" --out-dir ./icrp_validation
"""

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

import numpy as np

# Windows GBK 控制台无法编码 Unicode 字符（如 ³），强制使用 UTF-8 输出
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ──────────────────────────────────────────────
# AM 体模物理参数（ICRP 110, Table A.1 脚注）
# ──────────────────────────────────────────────
AM_DIMS = {
    'columns': 254,          # X方向体素数（左右）
    'rows':    127,          # Y方向体素数（前后/AP方向）
    'slices':  222,          # Z方向体素数（头脚）
    'voxel_mm': (2.137, 2.137, 8.0),   # 体素尺寸 mm (X, Y, Z)
}

AF_DIMS = {
    'columns': 299,
    'rows':    137,
    'slices':  348,
    'voxel_mm': (1.775, 1.775, 4.84),
}

# 降采样目标尺寸（与现有 MCNP 工作流保持一致）
DOWNSAMPLE_TARGET = (127, 63, 111)   # (nx, ny, nz)

# ──────────────────────────────────────────────
# 器官分组：解剖名称 → AM organ_id 列表
# 来源: ICRP 110 AM_organs.dat
# ──────────────────────────────────────────────
ORGAN_GROUPS_AM = {
    'Adrenals':             [1, 2],
    'Brain':                [61],
    'Colon wall':           [76, 78, 80, 82, 84, 86],
    'Oesophagus':           [110],
    'Eye lenses':           [66, 68],
    'Gallbladder wall':     [70],
    'Heart muscle':         [87],
    'Kidneys':              [89, 90, 91, 92, 93, 94],
    'Liver':                [95],
    'Lungs':                [96, 97, 98, 99],
    'Pancreas':             [113],
    'Prostate':             [115],
    'Salivary glands':      [120, 121],
    'Skin':                 [122, 123, 124, 125],
    'Spinal cord':          [126],
    'Spleen':               [127],
    'Stomach wall':         [72],
    'Testes':               [129, 130],
    'Thymus':               [131],
    'Thyroid':              [132],
    'Urinary bladder wall': [137],
    # ICRP 116 剂量计算还需要这两项（用组织平均近似）
    'Red bone marrow':      [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
                             16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
                             27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37,
                             38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48,
                             49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60],
    'Bone surface':         [3],   # 皮质骨/骨骼表面近似
}


def parse_organs_dat(lines):
    """
    解析 AM_organs.dat，返回 {organ_id: {'tissue': int, 'density': float, 'name': str}}
    格式: <id>  <name>  <tissue_num>  <density g/cm³>
    """
    organs = {}
    for line in lines:
        line = line.strip()
        m = re.match(r'^\s*(\d+)\s+(.+?)\s{2,}(\d+)\s+([\d.]+)\s*$', line)
        if m:
            oid       = int(m.group(1))
            name      = m.group(2).strip()
            tissue    = int(m.group(3))
            density   = float(m.group(4))
            organs[oid] = {'tissue': tissue, 'density': density, 'name': name}
    return organs


def load_voxel_data_from_zip(zip_path: str, phantom: str = 'AM') -> tuple:
    """
    从 AM.zip 或 AF.zip 读取体素数据和器官定义。

    Parameters
    ----------
    zip_path : str
        路径指向 AM.zip 或 AF.zip
    phantom : str
        'AM' 或 'AF'

    Returns
    -------
    voxel : np.ndarray  shape (ncol, nrow, nslice) = (X, Y, Z)
    organs : dict  {organ_id: {...}}
    """
    if phantom == 'AF':
        dims = AF_DIMS
        dat_entry    = 'AF/AF.dat'
        organs_entry = 'AF/AF_organs.dat'
    else:
        dims = AM_DIMS
        dat_entry    = 'AM/AM.dat'
        organs_entry = 'AM/AM_organs.dat'

    ncol, nrow, nslice = dims['columns'], dims['rows'], dims['slices']
    total = ncol * nrow * nslice

    print(f"[步骤1] 打开 {zip_path} (phantom={phantom}) ...")
    with zipfile.ZipFile(zip_path, 'r') as z:
        # 读器官定义
        with z.open(organs_entry) as f:
            organ_lines = f.read().decode('utf-8', errors='replace').splitlines()
        organs = parse_organs_dat(organ_lines)
        print(f"  解析器官定义: {len(organs)} 个 organ_id")

        # 读体素数据
        print(f"  读取 {dat_entry} ({ncol}×{nrow}×{nslice} = {total:,} 体素) ...")
        with z.open(dat_entry) as f:
            raw_text = f.read().decode('utf-8', errors='replace')

    all_numbers = np.fromiter(
        (int(x) for x in raw_text.split()),
        dtype=np.int16,
        count=total
    )
    # 存储顺序: 外层 slice → row → col (Z慢 → Y → X快)
    voxel = all_numbers.reshape((nslice, nrow, ncol))
    # 转置为 (col, row, slice) = (X, Y, Z) 便于后续按空间方向处理
    voxel = voxel.transpose(2, 1, 0)  # shape: (ncol, nrow, nslice)
    print(f"  体素数组 shape={voxel.shape}, 非零={np.count_nonzero(voxel):,}")
    return voxel, organs


def downsample_voxel(voxel: np.ndarray, target: tuple) -> np.ndarray:
    """
    最近邻降采样：(254,127,222) → target=(127,63,111)
    保持 organ_id 值（不做平均，取众数近似为中心体素）

    Parameters
    ----------
    voxel  : np.ndarray shape (ncol, nrow, nslice)
    target : (tx, ty, tz)

    Returns
    -------
    np.ndarray shape target
    """
    src_shape = np.array(voxel.shape)   # (254, 127, 222)
    tgt_shape = np.array(target)        # (127,  63, 111)

    # 目标格点在源空间中的对应位置（中心采样）
    xi = np.floor((np.arange(tgt_shape[0]) + 0.5) * src_shape[0] / tgt_shape[0]).astype(int)
    yi = np.floor((np.arange(tgt_shape[1]) + 0.5) * src_shape[1] / tgt_shape[1]).astype(int)
    zi = np.floor((np.arange(tgt_shape[2]) + 0.5) * src_shape[2] / tgt_shape[2]).astype(int)

    xi = np.clip(xi, 0, src_shape[0] - 1)
    yi = np.clip(yi, 0, src_shape[1] - 1)
    zi = np.clip(zi, 0, src_shape[2] - 1)

    # 三维索引
    mask = voxel[np.ix_(xi, yi, zi)]   # shape (127, 63, 111)
    return mask.astype(np.uint8)


def build_organ_mask(voxel_ds: np.ndarray, organs: dict) -> tuple:
    """
    基于降采样体素，统计每个器官组的体素数 + 平均密度。

    Returns
    -------
    organ_stats : dict  {organ_name: {'voxel_ids': [...], 'voxel_count': int,
                                      'mean_density': float, 'indices': ndarray}}
    """
    organ_stats = {}
    for name, id_list in ORGAN_GROUPS_AM.items():
        # 找属于该器官组的所有体素位置
        mask = np.zeros(voxel_ds.shape, dtype=bool)
        for oid in id_list:
            mask |= (voxel_ds == oid)

        count = int(np.sum(mask))
        # 加权平均密度
        total_d = 0.0
        total_n = 0
        for oid in id_list:
            n = int(np.sum(voxel_ds == oid))
            d = organs.get(oid, {}).get('density', 1.0)
            total_d += d * n
            total_n += n
        mean_dens = total_d / max(total_n, 1)

        organ_stats[name] = {
            'organ_ids':    id_list,
            'voxel_count':  count,
            'mean_density': round(mean_dens, 4),
        }
    return organ_stats


def main():
    parser = argparse.ArgumentParser(description='ICRP-110 验证 Step1: 生成器官掩膜')
    parser.add_argument('--data-zip', default='../P110 data V1.2/AM.zip',
                        help='AM.zip 或 AF.zip 路径')
    parser.add_argument('--out-dir', default='./icrp_validation',
                        help='输出目录')
    parser.add_argument('--phantom', default='AM', choices=['AM', 'AF'],
                        help='体模类型: AM (成年男性) 或 AF (成年女性)')
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    phantom = args.phantom

    # ── 1. 加载原始体素数据 ──
    voxel_full, organs = load_voxel_data_from_zip(args.data_zip, phantom=phantom)

    # ── 2. 降采样 ──
    print(f"\n[步骤2] 降采样 {voxel_full.shape} → {DOWNSAMPLE_TARGET} ...")
    voxel_ds = downsample_voxel(voxel_full, DOWNSAMPLE_TARGET)
    print(f"  降采样后 shape={voxel_ds.shape}, 非零={np.count_nonzero(voxel_ds):,}")

    # 计算降采样后的体素尺寸 (cm)
    dims = AF_DIMS if phantom == 'AF' else AM_DIMS
    vox_mm = dims['voxel_mm']
    src = dims['columns'], dims['rows'], dims['slices']
    tgt = DOWNSAMPLE_TARGET
    ds_vox_cm = (
        vox_mm[0] * src[0] / tgt[0] / 10.0,  # X
        vox_mm[1] * src[1] / tgt[1] / 10.0,  # Y
        vox_mm[2] * src[2] / tgt[2] / 10.0,  # Z
    )
    phantom_size_cm = tuple(round(ds_vox_cm[i] * tgt[i], 3) for i in range(3))
    print(f"  降采样体素尺寸 (cm): {tuple(round(v,4) for v in ds_vox_cm)}")
    print(f"  体模总尺寸 (cm): X={phantom_size_cm[0]}, Y={phantom_size_cm[1]}, Z={phantom_size_cm[2]}")

    # ── 3. 保存掩膜 ──
    if phantom == 'AF':
        mask_fname = 'organ_mask_127x63x111_AF.npy'
    else:
        mask_fname = 'organ_mask_127x63x111.npy'
    mask_path = out_dir / mask_fname
    np.save(mask_path, voxel_ds)
    print(f"\n[保存] 器官掩膜 → {mask_path}")

    # ── 4. 统计各器官 ──
    print("\n[步骤3] 统计各器官体素...")
    organ_stats = build_organ_mask(voxel_ds, organs)

    print(f"\n{'器官名':<25} {'体素数':>8} {'平均密度(g/cm³)':>16}")
    print('-' * 52)
    for name, s in organ_stats.items():
        print(f"{name:<25} {s['voxel_count']:>8,} {s['mean_density']:>16.4f}")

    # ── 5. 保存元数据 JSON ──
    meta = {
        'phantom':       phantom,
        'source_shape':  [dims['columns'], dims['rows'], dims['slices']],
        'ds_shape':      list(DOWNSAMPLE_TARGET),
        'ds_voxel_cm':   [round(v, 6) for v in ds_vox_cm],
        'phantom_cm':    list(phantom_size_cm),
        'organ_groups':  {k: v['organ_ids'] for k, v in organ_stats.items()},
        'organ_stats':   organ_stats,
        # 密度映射 organ_id → density
        'density_map':   {str(k): v['density'] for k, v in organs.items()},
    }
    meta_fname = f'organ_mask_meta_{phantom}.json' if phantom == 'AF' else 'organ_mask_meta.json'
    meta_path = out_dir / meta_fname
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"\n[保存] 元数据    → {meta_path}")
    print(f"\nOK 第一步完成 (phantom={phantom})，可运行第二步生成 MCNP5 输入文件。")


if __name__ == '__main__':
    main()
