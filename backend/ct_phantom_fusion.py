#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CT-体模融合算法（改造版）

核心改动:
1. simple_fusion() 添加 distance_transform 过渡带平滑
2. generate_mcnp_input_enhanced() 完全重写为多材料体素lattice几何
3. 降采样策略: 2×2×2合并 → ~90万体素 (平衡精度与MCNP可行性)

Author: BNCT Team
Date: 2026-02
"""

# 修复Windows系统编码问题
import sys
import os
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    os.environ['PYTHONIOENCODING'] = 'utf-8'

import numpy as np
import nibabel as nib
from pathlib import Path
from scipy import ndimage
import json

# ---- 同目录模块 ----
try:
    from icrp110_material_map import ICRP110Materials
except ImportError:
    import importlib.util
    _here = Path(__file__).parent
    _spec = importlib.util.spec_from_file_location(
        "icrp110_material_map", _here / "icrp110_material_map.py")
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    ICRP110Materials = _mod.ICRP110Materials


# =====================================================================
# 1. 加载ICRP-110体模
# =====================================================================

def load_icrp110_phantom(phantom_type: str = 'AM') -> np.ndarray:
    """
    加载真实 ICRP-110 体模数据

    数据存储顺序（ICRP-110 README）：
      最外层循环: slice (Z), 中间: row (Y), 最内层: col (X)
    填充到 voxel_data[X, Y, Z]

    Returns
    -------
    np.ndarray  shape=(ncol, nrow, nslice) dtype=int16
    """
    PHANTOM_DIMS = {
        'AM': {'columns': 254, 'rows': 127, 'slices': 222,
               'voxel_size': (2.137, 2.137, 8.0)},
        'AF': {'columns': 299, 'rows': 137, 'slices': 348,
               'voxel_size': (1.775, 1.775, 4.84)},
    }
    pt = phantom_type.upper()
    if pt not in PHANTOM_DIMS:
        raise ValueError(f"未知体模类型: {phantom_type}，支持 AM / AF")

    dims = PHANTOM_DIMS[pt]
    ncol, nrow, nsli = dims['columns'], dims['rows'], dims['slices']

    script_dir = Path(__file__).parent
    candidates = [
        script_dir / pt / f"{pt}.dat",
        script_dir / "phantom_data" / pt / f"{pt}.dat",
        script_dir / f"{pt}.dat",
    ]
    dat_file = None
    for c in candidates:
        if c.exists():
            dat_file = c
            break

    if dat_file is None:
        paths_tried = '\n  '.join(str(c) for c in candidates)
        raise FileNotFoundError(
            f"未找到 ICRP-110 {pt} 体模数据文件。\n"
            f"请将 {pt}.dat 放置在以下任一位置：\n  {paths_tried}"
        )

    print(f"  加载体模文件: {dat_file}")
    print(f"  体模尺寸: {ncol}x{nrow}x{nsli}, 体素间距: {dims['voxel_size']} mm")

    with open(dat_file, 'r', encoding='utf-8', errors='ignore') as f:
        all_numbers = []
        for line in f:
            all_numbers.extend(int(x) for x in line.split())

    expected = ncol * nrow * nsli
    if len(all_numbers) < expected:
        raise ValueError(f"数据不足: 期望 {expected}，实际 {len(all_numbers)}")

    voxel_data = np.zeros((ncol, nrow, nsli), dtype=np.int16)
    idx = 0
    for nsl in range(nsli):
        for nr in range(nrow):
            for nc in range(ncol):
                voxel_data[nc, nr, nsl] = all_numbers[idx]
                idx += 1

    non_zero = np.count_nonzero(voxel_data)
    print(f"  OK 加载完成: 非零体素 {non_zero:,} ({non_zero / voxel_data.size * 100:.1f}%)")
    return voxel_data


def _build_fallback_phantom() -> np.ndarray:
    """当ICRP-110数据不存在时的简单fallback"""
    print("  [Fallback] 生成均匀软组织体模")
    phantom = np.zeros((254, 127, 222), dtype=np.int16)
    phantom[30:224, 10:117, 5:217] = 107   # 软组织
    return phantom


# =====================================================================
# 2. 解剖区域识别与配准
# =====================================================================

def detect_anatomical_region(ct_data: np.ndarray, ct_affine=None) -> str:
    """自动识别CT中的解剖区域"""
    print("\n[自动识别解剖区域]")
    shape = ct_data.shape
    print(f"  CT尺寸: {shape}")

    bone_ratio = np.sum(ct_data > 200) / ct_data.size
    air_ratio = np.sum(ct_data < -500) / ct_data.size
    z_slices = shape[2]

    if z_slices < 50:
        if bone_ratio > 0.15:
            region = 'brain'
        elif air_ratio > 0.3:
            region = 'chest'
        else:
            region = 'abdomen'
    elif z_slices < 150:
        region = 'chest' if air_ratio > 0.2 else 'abdomen'
    else:
        region = 'wholebody'

    print(f"  OK 识别结果: {region}")
    return region


# 区域参数表
ANATOMICAL_REGIONS = {
    'brain':       {'z_range': (0.75, 0.95), 'center_offset': (0, 0, 0),    'description': '头部/脑部',   'description_en': 'Head/Brain'},
    'nasopharynx': {'z_range': (0.70, 0.80), 'center_offset': (0, -0.1, 0), 'description': '鼻咽部',     'description_en': 'Nasopharynx'},
    'chest':       {'z_range': (0.50, 0.70), 'center_offset': (0, 0, 0),    'description': '胸部',       'description_en': 'Chest'},
    'abdomen':     {'z_range': (0.40, 0.60), 'center_offset': (0, 0, 0),    'description': '腹部',       'description_en': 'Abdomen'},
    'liver':       {'z_range': (0.45, 0.60), 'center_offset': (0.05, 0, 0), 'description': '肝脏区域',   'description_en': 'Liver'},
    'pelvis':      {'z_range': (0.25, 0.45), 'center_offset': (0, 0, 0),    'description': '骨盆',       'description_en': 'Pelvis'},
    'legs':        {'z_range': (0.00, 0.30), 'center_offset': (0, 0, 0),    'description': '腿部',       'description_en': 'Legs'},
    'wholebody':   {'z_range': (0.10, 0.90), 'center_offset': (0, 0, 0),    'description': '全身',       'description_en': 'Whole body'},
}


def smart_registration(ct_data, phantom_data, phantom_voxel_size, force_region=None):
    """智能配准: 识别CT区域并计算其在体模中的位置"""
    region = force_region if force_region else detect_anatomical_region(ct_data)
    rp = ANATOMICAL_REGIONS.get(region, ANATOMICAL_REGIONS['wholebody'])

    ps = phantom_data.shape
    z_start = int(ps[2] * rp['z_range'][0])
    z_end   = int(ps[2] * rp['z_range'][1])

    target_center = np.array([
        ps[0] // 2 + rp['center_offset'][0] * ps[0],
        ps[1] // 2 + rp['center_offset'][1] * ps[1],
        (z_start + z_end) // 2 + rp['center_offset'][2] * ps[2],
    ])

    ct_center = np.array(ct_data.shape) / 2.0
    ct_spacing = np.array([1.0, 1.0, 1.0])
    phantom_spacing = np.array(phantom_voxel_size)
    scaling = ct_spacing / phantom_spacing

    registration = {
        'translation': (target_center - ct_center).tolist(),
        'rotation': [0, 0, 0],
        'scaling': scaling.tolist(),
        'target_center': target_center.tolist(),
        'ct_center': ct_center.tolist(),
        'anatomical_region': region,
        'region_description': rp['description'],
        'region_description_en': rp.get('description_en', region),
        'z_range': [z_start, z_end],
        'auto_detected': force_region is None,
    }
    print(f"  OK 配准完成: {rp['description']}, Z={z_start}-{z_end}")
    return registration


# =====================================================================
# 3. 横截面轮廓测量与自适应缩放
# =====================================================================

def _measure_body_extent(slice_2d, threshold=0):
    """
    测量单个2D切片(X,Y)中身体区域的X/Y范围。

    Parameters
    ----------
    slice_2d : np.ndarray  shape=(nx, ny)
        器官ID切片 (>0表示体内)
    threshold : int
        体内阈值

    Returns
    -------
    dict  {'x_min','x_max','x_width','y_min','y_max','y_width','cx','cy'}
          如果无身体区域则返回 None
    """
    body = slice_2d > threshold
    if not np.any(body):
        return None
    xs, ys = np.where(body)
    return {
        'x_min': int(xs.min()), 'x_max': int(xs.max()),
        'x_width': int(xs.max() - xs.min() + 1),
        'y_min': int(ys.min()), 'y_max': int(ys.max()),
        'y_width': int(ys.max() - ys.min() + 1),
        'cx': float(xs.mean()), 'cy': float(ys.mean()),
    }


def _adaptive_xy_scale_ct(ct_materials, phantom_region, blend_slices=8):
    """
    计算CT在每个Z切片上相对体模的自适应XY缩放因子,
    然后对CT材料数组逐层应用缩放,使边界处轮廓对齐。

    策略:
    - 在CT的上/下边界各取若干层,测量CT身体宽度与体模身体宽度之比
    - 用线性插值得到中间各层的缩放因子
    - 对每层做 ndimage.zoom + 居中裁剪/填充

    Parameters
    ----------
    ct_materials : np.ndarray  (nx_ct, ny_ct, nz_ct)  int16
    phantom_region : np.ndarray  同shape  int16
    blend_slices : int
        边界处用来测量平均宽度的层数

    Returns
    -------
    np.ndarray  缩放后的ct_materials (同shape)
    """
    nz = ct_materials.shape[2]
    if nz < 4:
        return ct_materials

    # -- 逐层测量CT和体模的X/Y宽度 --
    ct_xw = np.zeros(nz)
    ct_yw = np.zeros(nz)
    ph_xw = np.zeros(nz)
    ph_yw = np.zeros(nz)

    for k in range(nz):
        ct_ext = _measure_body_extent(ct_materials[:, :, k])
        ph_ext = _measure_body_extent(phantom_region[:, :, k])
        if ct_ext:
            ct_xw[k] = ct_ext['x_width']
            ct_yw[k] = ct_ext['y_width']
        if ph_ext:
            ph_xw[k] = ph_ext['x_width']
            ph_yw[k] = ph_ext['y_width']

    # -- 计算边界处的平均缩放比 --
    bs = min(blend_slices, nz // 4, 3)
    bs = max(bs, 1)

    def _avg_ratio(ct_w, ph_w, slices_idx):
        """安全地计算平均缩放比"""
        ratios = []
        for i in slices_idx:
            if ct_w[i] > 5 and ph_w[i] > 5:
                ratios.append(ph_w[i] / ct_w[i])
        return np.mean(ratios) if ratios else 1.0

    # 底部边界 (Z小端)
    bottom_idx = list(range(0, bs))
    sx_bottom = _avg_ratio(ct_xw, ph_xw, bottom_idx)
    sy_bottom = _avg_ratio(ct_yw, ph_yw, bottom_idx)

    # 顶部边界 (Z大端)
    top_idx = list(range(nz - bs, nz))
    sx_top = _avg_ratio(ct_xw, ph_xw, top_idx)
    sy_top = _avg_ratio(ct_yw, ph_yw, top_idx)

    # 如果缩放比接近1, 无需处理
    if (abs(sx_bottom - 1.0) < 0.05 and abs(sx_top - 1.0) < 0.05 and
            abs(sy_bottom - 1.0) < 0.05 and abs(sy_top - 1.0) < 0.05):
        print(f"  [轮廓匹配] 边界处CT与体模宽度差异<5%, 无需自适应缩放")
        return ct_materials

    print(f"  [轮廓匹配] 底部缩放比 X={sx_bottom:.3f} Y={sy_bottom:.3f}")
    print(f"  [轮廓匹配] 顶部缩放比 X={sx_top:.3f} Y={sy_top:.3f}")

    # -- 逐层线性插值缩放因子 + 缩放 --
    result = ct_materials.copy()
    nx, ny, _ = ct_materials.shape

    # 定义过渡区域: 边界处应用完整缩放, 中心区域逐渐过渡到1.0
    # 使用cosine衰减: 边界→缩放, 中心→不缩放(保留CT原始精度)
    mid = nz / 2.0
    for k in range(nz):
        # t: 0在底部, 1在顶部
        t = k / max(nz - 1, 1)
        # 边界权重: 靠近边界时为1, 靠近中心时为0
        dist_to_edge = min(k, nz - 1 - k)
        fade_zone = nz * 0.3  # 30%深度处完全过渡到1.0
        if fade_zone < 1:
            fade_zone = 1
        edge_weight = max(0.0, 1.0 - dist_to_edge / fade_zone)

        # 插值得到当前层的缩放比
        sx_boundary = sx_bottom * (1.0 - t) + sx_top * t
        sy_boundary = sy_bottom * (1.0 - t) + sy_top * t

        # 用edge_weight混合: 边界处用boundary缩放, 中心处用1.0
        sx = 1.0 + edge_weight * (sx_boundary - 1.0)
        sy = 1.0 + edge_weight * (sy_boundary - 1.0)

        # 如果缩放比足够接近1,跳过
        if abs(sx - 1.0) < 0.02 and abs(sy - 1.0) < 0.02:
            continue

        # 对该层进行缩放
        layer = ct_materials[:, :, k].astype(np.float32)
        scaled_layer = ndimage.zoom(layer, (sx, sy), order=0)

        # 居中放回原尺寸
        snx, sny = scaled_layer.shape
        out_layer = np.zeros((nx, ny), dtype=np.int16)

        # 源裁剪范围
        src_x0 = max(0, (snx - nx) // 2)
        src_y0 = max(0, (sny - ny) // 2)
        src_x1 = src_x0 + min(snx, nx)
        src_y1 = src_y0 + min(sny, ny)
        if src_x1 > snx:
            src_x1 = snx
        if src_y1 > sny:
            src_y1 = sny

        # 目标放置范围
        dst_x0 = max(0, (nx - snx) // 2)
        dst_y0 = max(0, (ny - sny) // 2)

        copy_w = min(src_x1 - src_x0, nx - dst_x0)
        copy_h = min(src_y1 - src_y0, ny - dst_y0)

        out_layer[dst_x0:dst_x0 + copy_w,
                  dst_y0:dst_y0 + copy_h] = scaled_layer[
            src_x0:src_x0 + copy_w,
            src_y0:src_y0 + copy_h].astype(np.int16)

        result[:, :, k] = out_layer

    print(f"  [轮廓匹配] 自适应缩放完成")
    return result


# =====================================================================
# 4. 融合 (带轮廓匹配 + 过渡带平滑)
# =====================================================================

def simple_fusion(ct_data, phantom_data, registration,
                  transition_width=5,
                  ct_spacing=(1.0, 1.0, 1.0),
                  phantom_spacing=(2.137, 2.137, 8.0)):
    """
    将CT数据重采样到体模体素网格后插入体模。
    含横截面轮廓自适应匹配 + 过渡带平滑。
    """
    print("\n[执行融合]")
    fusion_result = phantom_data.copy()

    # -- 1. 重采样CT到体模分辨率 --
    scale_factors = np.array([
        ct_spacing[0] / phantom_spacing[0],
        ct_spacing[1] / phantom_spacing[1],
        ct_spacing[2] / phantom_spacing[2],
    ])
    print(f"  体素间距缩放因子: {scale_factors}")

    ct_resampled = ndimage.zoom(ct_data, scale_factors, order=1)
    print(f"  CT重采样后shape: {ct_resampled.shape}")

    # -- 2. 计算插入位置 --
    target_center = np.array(registration['target_center']).astype(int)
    ct_center = np.array(ct_resampled.shape) // 2
    translation = target_center - ct_center

    ct_shape = np.array(ct_resampled.shape)
    start_pos = np.maximum(0, translation).astype(int)
    end_pos = np.minimum(np.array(phantom_data.shape),
                         (translation + ct_shape).astype(int))
    ct_start = np.maximum(0, -translation).astype(int)
    ct_end = ct_start + (end_pos - start_pos)

    print(f"  插入位置: {start_pos} -> {end_pos}")

    # -- 3. HU → 材料 (体内/体外分离) --
    ct_region = ct_resampled[ct_start[0]:ct_end[0],
                             ct_start[1]:ct_end[1],
                             ct_start[2]:ct_end[2]]

    # flood-fill 标记体外空气
    is_air = ct_region < -500
    air_label, _ = ndimage.label(is_air)
    border_labels = set()
    for axis in range(3):
        for side in [0, -1]:
            slc = [slice(None)] * 3
            slc[axis] = side
            border_labels.update(np.unique(air_label[tuple(slc)]))
    border_labels.discard(0)
    exterior_air = np.zeros_like(is_air)
    for lbl in border_labels:
        exterior_air |= (air_label == lbl)
    interior_air = is_air & (~exterior_air)

    ct_materials = np.zeros_like(ct_region, dtype=np.int16)
    ct_materials[interior_air] = 81                          # 肺/体内空气 → ICRP lung id
    ct_materials[(ct_region >= -500) & (ct_region < 100)] = 107  # 软组织
    ct_materials[ct_region >= 100] = 46                       # 骨骼 (cortical bone id)
    # exterior_air 保持 0

    # -- 4. ★ 横截面轮廓自适应匹配 ★ --
    phantom_region_orig = fusion_result[
        start_pos[0]:end_pos[0],
        start_pos[1]:end_pos[1],
        start_pos[2]:end_pos[2]
    ].copy()

    print("  [轮廓匹配] 对CT进行自适应XY缩放以匹配体模轮廓...")
    ct_materials = _adaptive_xy_scale_ct(ct_materials, phantom_region_orig)

    # -- 5. 过渡带平滑 --
    ct_body_mask = (ct_materials > 0)

    if transition_width > 0 and np.any(ct_body_mask):
        # 计算CT体内区域到边界的距离
        dist_outside = ndimage.distance_transform_edt(~ct_body_mask)

        # 过渡带: CT边界外侧 1~transition_width 体素
        trans_mask = (dist_outside > 0) & (dist_outside <= transition_width)

        # 权重: 1.0 在边界, 0.0 在过渡带外缘
        weights = np.zeros_like(dist_outside, dtype=np.float32)
        weights[trans_mask] = 1.0 - dist_outside[trans_mask] / transition_width

        # 在过渡带内，用权重在CT材料和体模之间混合
        transition_zone = trans_mask & (phantom_region_orig > 0)
        # 高权重(靠近CT) → 用CT, 低权重 → 用体模
        use_ct = transition_zone & (weights > 0.5) & (ct_materials > 0)
        phantom_region_orig[use_ct] = ct_materials[use_ct]

        print(f"  过渡带体素: {np.sum(transition_zone):,}")

    # -- 6. 核心区域直接替换 --
    replace_mask = ct_body_mask
    phantom_region_orig[replace_mask] = ct_materials[replace_mask]

    fusion_result[
        start_pos[0]:end_pos[0],
        start_pos[1]:end_pos[1],
        start_pos[2]:end_pos[2]
    ] = phantom_region_orig

    replaced = np.sum(fusion_result != phantom_data)
    print(f"  OK 融合完成: 替换体素 {replaced:,} ({replaced / phantom_data.size * 100:.2f}%)")
    return fusion_result


# =====================================================================
# 4. 生成MCNP5多材料体素lattice输入文件  ★ 核心改造 ★
# =====================================================================

def _downsample_phantom(data: np.ndarray, factor: int = 2) -> np.ndarray:
    """
    对体模进行降采样（最近邻取众数）。
    factor=2 → 254×127×222 → 127×63×111
    """
    nx, ny, nz = data.shape
    nx2 = nx // factor
    ny2 = ny // factor
    nz2 = nz // factor
    # 裁剪到整除尺寸
    trimmed = data[:nx2 * factor, :ny2 * factor, :nz2 * factor]
    # reshape → 取每个block的第一个体素(近似众数,快速)
    ds = trimmed.reshape(nx2, factor, ny2, factor, nz2, factor)
    # 取 (0,0,0) 位置的值 = 最近邻
    return ds[:, 0, :, 0, :, 0].copy()


def generate_mcnp_input_enhanced(phantom_data: np.ndarray,
                                 output_path: str,
                                 registration: dict,
                                 phantom_type: str = 'AM') -> None:
    """
    生成MCNP5兼容的多材料体素lattice输入文件。

    体模(254×127×222)先降采样2×,变为127×63×111(约89万体素)。
    将器官ID映射为材料ID,然后写入MCNP lattice fill array。
    包含: FMESH14全身网格tally + 多材料定义 + BNCT中子源。
    """
    print("\n[生成MCNP多材料体素输入文件]")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    region = registration['anatomical_region']

    # ---- 初始化ICRP-110材料映射 ----
    icrp_mat = ICRP110Materials(phantom_type)

    # ---- 降采样 ----
    DS_FACTOR = 2
    ds_phantom = _downsample_phantom(phantom_data, DS_FACTOR)
    nx, ny, nz = ds_phantom.shape
    print(f"  降采样: {phantom_data.shape} -> {ds_phantom.shape}")

    # ---- 器官ID → 材料ID (tissue number) ----
    mat_vol = icrp_mat.build_material_volume(ds_phantom)
    unique_mats = set(np.unique(mat_vol)) - {0}
    print(f"  唯一材料: {len(unique_mats)}种, ID范围: {min(unique_mats)}-{max(unique_mats)}")

    # ---- 物理尺寸 (cm, MCNP单位) ----
    PHANTOM_VOXEL_SIZES = {
        'AM': (2.137, 2.137, 8.0),
        'AF': (1.775, 1.775, 4.84),
    }
    VX_MM, VY_MM, VZ_MM = PHANTOM_VOXEL_SIZES.get(phantom_type, (2.137, 2.137, 8.0))
    dx_cm = VX_MM * DS_FACTOR / 10.0   # 单个降采样体素的物理尺寸 cm
    dy_cm = VY_MM * DS_FACTOR / 10.0
    dz_cm = VZ_MM * DS_FACTOR / 10.0

    x_max = nx * dx_cm
    y_max = ny * dy_cm
    z_max = nz * dz_cm

    # ---- 源位置 ----
    x_src = x_max / 2.0
    y_src = y_max / 2.0
    z_mid_vox = (registration['z_range'][0] + registration['z_range'][1]) // 2
    z_src = z_mid_vox * VZ_MM / 10.0

    # ---- FMESH bins (与降采样后的体素网格对齐) ----
    n_bins_x, n_bins_y, n_bins_z = nx, ny, nz

    # ---- 写入文件 ----
    with open(output_path, 'w', encoding='ascii') as f:
        # 标题
        f.write("BNCT Whole-body Voxel Phantom\n")
        f.write("c ================================================\n")
        f.write("c  Multi-material voxel lattice geometry\n")
        f.write(f"c  Region: {registration.get('region_description_en', registration['anatomical_region'])}\n")
        f.write(f"c  Phantom grid: {nx}x{ny}x{nz} voxels\n")
        f.write(f"c  Voxel size: {dx_cm:.4f}x{dy_cm:.4f}x{dz_cm:.4f} cm\n")
        f.write(f"c  Physical size: {x_max:.2f}x{y_max:.2f}x{z_max:.2f} cm\n")
        f.write(f"c  Materials: {sorted(unique_mats)}\n")
        f.write("c ================================================\n")

        # ==== Cell Cards ====
        f.write("c --- Cell Cards ---\n")

        # Universe cells: 每种材料(tissue number)对应一个universe
        # 体外/空气: universe=100, void
        for mat_id in sorted(unique_mats):
            tissue_name, _ = icrp_mat.media.get(mat_id, (f'Tissue {mat_id}', {}))
            density = icrp_mat.get_tissue_density(mat_id)
            f.write(f"{mat_id} {mat_id} -{density:.4f} -10  "
                    f"u={mat_id}  imp:n=1  $ {tissue_name}\n")
        # 体外空气 universe
        f.write("100 0  -10  u=100  imp:n=0  $ External air\n")

        # Lattice cell
        f.write("c\nc  Lattice cell\n")
        f.write("200 0  -10  lat=1  u=200  imp:n=1\n")

        # fill array: 遍历 Z(最外) → Y → X(最内)
        f.write(f"      fill=0:{nx - 1}  0:{ny - 1}  0:{nz - 1}\n")

        # 写 fill array — 按 MCNP lattice 填充顺序:
        # k(Z) 最外循环, j(Y) 中间, i(X) 最内
        count = 0
        for k in range(nz):
            for j in range(ny):
                row_vals = []
                for i in range(nx):
                    m = int(mat_vol[i, j, k])
                    u = m if m > 0 else 100
                    row_vals.append(str(u))
                # MCNP每行不超过80字符，分批写
                line = '      ' + ' '.join(row_vals)
                while len(line) > 78:
                    cut = line.rfind(' ', 0, 78)
                    if cut <= 6:
                        cut = 78
                    f.write(line[:cut] + '\n')
                    line = '      ' + line[cut:].lstrip()
                f.write(line + '\n')
                count += nx
        print(f"  fill array写入: {count:,} 体素")

        # Container cell (包裹lattice)
        f.write("c\nc  Container\n")
        f.write("300 0  -20  fill=200  imp:n=1  $ Phantom container\n")
        f.write("999 0   20  imp:n=0  $ Outside world\n")

        # blank line separator
        f.write("\n")

        # ==== Surface Cards ====
        f.write("c --- Surface Cards ---\n")
        # 单位体素 RPP (用于universe cell 和 lattice)
        f.write(f"10 RPP 0 {dx_cm:.6f}  0 {dy_cm:.6f}  0 {dz_cm:.6f}\n")
        # 容器 RPP
        f.write(f"20 RPP 0 {x_max:.4f}  0 {y_max:.4f}  0 {z_max:.4f}\n")
        f.write("\n")

        # ==== Data Cards ====
        f.write("c --- Data Cards ---\n")
        f.write("mode n\n")
        f.write("c\n")

        # Source
        f.write("c  BNCT epithermal neutron source\n")
        f.write(f"sdef pos={x_src:.3f} {y_src:.3f} {z_src:.3f} "
                f"axs=0 0 -1 ext=0 rad=d1 erg=0.025e-3 par=1\n")
        f.write("si1 0 5\n")
        f.write("sp1 -21 1\n")
        f.write("c\n")

        # Materials
        icrp_mat.write_mcnp_material_cards(f, unique_mats)

        # FMESH (全身网格tally)
        f.write("c  Mesh Tally - whole body dose distribution\n")
        f.write("FMESH14:n GEOM=xyz\n")
        f.write("      ORIGIN=0 0 0\n")
        f.write(f"      IMESH={x_max:.4f}  IINTS={n_bins_x}\n")
        f.write(f"      JMESH={y_max:.4f}  JINTS={n_bins_y}\n")
        f.write(f"      KMESH={z_max:.4f}  KINTS={n_bins_z}\n")
        f.write("c\n")

        # F4 cell tally (container)
        f.write("f4:n 300\n")
        f.write("c\n")

        # Run parameters
        f.write("c  Run parameters\n")
        f.write("nps 100000\n")
        f.write("print\n")

    file_size = output_path.stat().st_size
    print(f"  OK MCNP输入文件: {output_path}")
    print(f"  文件大小: {file_size / 1024:.1f} KB")
    print(f"  网格: {nx}x{ny}x{nz}, 材料: {len(unique_mats)}种")


# =====================================================================
# 5. 主工作流
# =====================================================================

def main_workflow_enhanced(ct_path: str, output_dir: str,
                          force_region: str = None,
                          gender: str = 'male',
                          patient_height: float = None,
                          patient_weight: float = None):
    """
    增强版主工作流程

    Parameters
    ----------
    ct_path : str
        CT NIfTI文件路径
    output_dir : str
        输出目录
    force_region : str, optional
        强制指定解剖区域
    gender : str
        'male' → AM体模, 'female' → AF体模
    patient_height : float, optional
        患者身高(cm), 提供则启用体模整体缩放
    patient_weight : float, optional
        患者体重(kg), 提供则启用体模整体缩放
    """
    print("=" * 60)
    print("全身体模构建工作流程（多材料体素版）")
    print("=" * 60)
    print(f"输入CT: {ct_path}")
    print(f"输出目录: {output_dir}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 加载CT
    print("\n[步骤1] 加载CT影像")
    try:
        nii = nib.load(ct_path)
        ct_data = nii.get_fdata()
        ct_voxel_sizes = nib.affines.voxel_sizes(nii.affine)
        ct_spacing = tuple(ct_voxel_sizes.tolist())
        print(f"  OK CT: {ct_data.shape}, 间距: {ct_spacing} mm")

        # 交叉验证pixdim
        try:
            pixdim = nii.header['pixdim'][1:4]
            if all(abs(s - 1.0) < 0.01 for s in ct_spacing) and \
               not all(abs(p - 1.0) < 0.01 for p in pixdim) and \
               all(p > 0 for p in pixdim):
                ct_spacing = tuple(float(p) for p in pixdim)
                print(f"  [修正] 使用pixdim: {ct_spacing} mm")
        except Exception:
            pass
    except Exception as e:
        print(f"  CT加载失败: {e}, 使用示例数据")
        ct_data = np.random.randn(100, 100, 100) * 100
        ct_spacing = (1.0, 1.0, 1.0)

    # 2. 加载体模
    print("\n[步骤2] 加载ICRP-110体模")
    phantom_type = 'AM' if gender.lower() in ('male', 'm', 'am') else 'AF'
    voxel_size = (2.137, 2.137, 8.0) if phantom_type == 'AM' else (1.775, 1.775, 4.84)
    try:
        phantom_data = load_icrp110_phantom(phantom_type)
    except FileNotFoundError as e:
        print(f"  [警告] {e}")
        phantom_data = _build_fallback_phantom()
    print(f"  体模尺寸: {phantom_data.shape}")

    # 2.5. 根据患者身高体重缩放体模 (如提供)
    if patient_height and patient_weight:
        print("\n[步骤2.5] 根据患者身高体重缩放体模")
        try:
            from phantom_scaling import PhantomScaler
            scaler = PhantomScaler(phantom_type)
            scaling_factors = scaler.calculate_scaling_factors(
                patient_height, patient_weight)
            phantom_data, scale_params = scaler.scale_voxel_phantom(
                phantom_data, scaling_factors)
            # 更新体素尺寸以反映缩放
            voxel_size = (
                voxel_size[0] * scaling_factors['x'],
                voxel_size[1] * scaling_factors['y'],
                voxel_size[2] * scaling_factors['z'],
            )
            print(f"  缩放后体模尺寸: {phantom_data.shape}")
            print(f"  缩放后体素间距: {voxel_size} mm")
        except Exception as e:
            print(f"  [警告] 体模缩放失败: {e}, 使用原始体模")
    else:
        print("  [提示] 未提供患者身高体重, 使用标准ICRP参考体模")

    # 3. 配准
    print("\n[步骤3] 配准")
    registration = smart_registration(
        ct_data, phantom_data,
        phantom_voxel_size=voxel_size,
        force_region=force_region,
    )

    # 4. 融合(含轮廓匹配+过渡带)
    print("\n[步骤4] 融合（含横截面轮廓匹配）")
    fusion_result = simple_fusion(
        ct_data, phantom_data, registration,
        transition_width=5,
        ct_spacing=ct_spacing,
        phantom_spacing=voxel_size,
    )

    # 5. 保存融合体模
    print("\n[步骤5] 保存融合体模")
    fusion_nii_path = output_dir / 'fused_phantom.nii.gz'
    affine = np.diag([voxel_size[0], voxel_size[1], voxel_size[2], 1])
    nii_out = nib.Nifti1Image(fusion_result.astype(np.int16), affine)
    nib.save(nii_out, fusion_nii_path)
    print(f"  OK 融合体模: {fusion_nii_path}")

    # 6. 生成MCNP输入(多材料lattice)
    print("\n[步骤6] 生成MCNP输入文件（多材料体素lattice）")
    mcnp_input_path = output_dir / 'wholebody_mcnp.inp'
    generate_mcnp_input_enhanced(fusion_result, str(mcnp_input_path),
                                 registration, phantom_type=phantom_type)

    # 7. 元数据
    metadata = {
        'ct_path': ct_path,
        'ct_shape': list(ct_data.shape),
        'phantom_shape': list(phantom_data.shape),
        'fusion_shape': list(fusion_result.shape),
        'registration': registration,
        'gender': gender,
        'phantom_type': phantom_type,
        'patient_height': patient_height,
        'patient_weight': patient_weight,
        'voxel_size_mm': list(voxel_size),
        'version': '4.0_contour_matched',
    }
    metadata_path = output_dir / 'fusion_metadata.json'
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("OK 全身体模构建完成!")
    print("=" * 60)
    print(f"  MCNP输入: {mcnp_input_path}")
    print(f"  融合体模: {fusion_nii_path}")
    print(f"  元数据:   {metadata_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='CT-体模融合与MCNP输入生成')
    parser.add_argument('ct_path', help='CT NIfTI文件路径')
    parser.add_argument('output_dir', help='输出目录')
    parser.add_argument('--region', default=None, help='强制指定解剖区域')
    parser.add_argument('--gender', default='male', help='性别 male/female')
    parser.add_argument('--height', type=float, default=None,
                        help='患者身高(cm), 提供后启用体模缩放')
    parser.add_argument('--weight', type=float, default=None,
                        help='患者体重(kg), 提供后启用体模缩放')
    args = parser.parse_args()

    main_workflow_enhanced(args.ct_path, args.output_dir,
                          force_region=args.region,
                          gender=args.gender,
                          patient_height=args.height,
                          patient_weight=args.weight)