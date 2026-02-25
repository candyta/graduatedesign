#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CT-体模融合算法

核心方法:
1. simple_fusion(): sigmoid 过渡带融合 (Kollitz et al., PMB 2022)
   - Z方向: 10 cm sigmoid 消除 CT in-field 上下端硬边界
   - XY方向: 2 cm sigmoid 消除体表轮廓不匹配环状伪影
2. generate_mcnp_input_enhanced(): 多材料体素 lattice 几何
3. 降采样策略: 2x2x2 合并 -> ~90万体素

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
# 3. Sigmoid 过渡带融合 (Kollitz et al., PMB 2022)
# =====================================================================

def _sigmoid(x):
    """数值稳定的 sigmoid 函数"""
    return np.where(x >= 0,
                    1.0 / (1.0 + np.exp(-x)),
                    np.exp(x) / (1.0 + np.exp(x)))


def simple_fusion(ct_data, phantom_data, registration,
                  transition_cm=10.0,
                  ct_spacing=(1.0, 1.0, 1.0),
                  phantom_spacing=(2.137, 2.137, 8.0)):
    """
    将CT数据重采样到体模体素网格后插入体模。

    参考 Kollitz et al. (PMB 2022, Sec 2.1.3):
    在CT in-field 的 Z方向末端使用 sigmoid 函数，
    以预设距离 (默认10 cm) 平滑衰减替换权重至零，
    消除 CT/phantom 材料边界处的硬跳变。

    XY 方向同样使用 sigmoid 从体表边缘向内过渡，
    避免轮廓不匹配导致的环状伪影。

    Parameters
    ----------
    transition_cm : float
        Sigmoid 过渡带物理宽度 (cm)。默认10 cm (Kollitz et al.)
    """
    print("\n[执行融合 — Sigmoid 过渡带, Kollitz et al.]")
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

    # -- 3. HU -> 材料 (体内/体外分离) --
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
    ct_materials[interior_air] = 81                              # 肺/体内空气
    ct_materials[(ct_region >= -500) & (ct_region < 100)] = 107  # 软组织
    ct_materials[ct_region >= 100] = 46                          # 骨骼
    # exterior_air 保持 0

    ct_body_mask = (ct_materials > 0)
    nx, ny, nz = ct_materials.shape

    # -- 4. 构建 sigmoid 权重场 (Kollitz Sec 2.1.3) --
    #
    #   sigmoid(d) 从 ~0 过渡到 ~1:
    #     d=0 (边缘)   -> ~0.05
    #     d=half       -> 0.50
    #     d=full width -> ~0.95
    #
    #   Z 方向: 10 cm 过渡距离
    #   XY方向: 2 cm 过渡距离 (体表内缩方向)

    # ---- Z 方向 sigmoid ----
    trans_vox_z = transition_cm * 10.0 / phantom_spacing[2]   # cm->mm->voxels
    half_z = trans_vox_z / 2.0
    k_z = 6.0 / max(trans_vox_z, 1.0)   # 6/width 让 sigmoid 在 [0,width] 内跨越 ~5%--95%

    z_weight = np.ones(nz, dtype=np.float32)
    for k in range(nz):
        dist_to_z_edge = float(min(k, nz - 1 - k))
        z_weight[k] = _sigmoid((dist_to_z_edge - half_z) * k_z)

    # ---- XY 方向 sigmoid (逐层 2D 距离变换) ----
    xy_trans_cm = 2.0                                           # 2 cm XY 过渡
    xy_trans_vox = xy_trans_cm * 10.0 / phantom_spacing[0]
    half_xy = xy_trans_vox / 2.0
    k_xy = 6.0 / max(xy_trans_vox, 1.0)

    weight_3d = np.zeros((nx, ny, nz), dtype=np.float32)
    for k in range(nz):
        slice_mask = ct_body_mask[:, :, k]
        if not np.any(slice_mask):
            continue
        dist_2d = ndimage.distance_transform_edt(slice_mask).astype(np.float32)
        xy_w = _sigmoid((dist_2d - half_xy) * k_xy)
        weight_3d[:, :, k] = z_weight[k] * xy_w

    print(f"  [Sigmoid] Z过渡: {trans_vox_z:.1f} 层 ({transition_cm} cm), "
          f"XY过渡: {xy_trans_vox:.1f} 体素 ({xy_trans_cm} cm)")

    # -- 5. 用 sigmoid 权重决定替换区域 --
    #   weight > 0.5 的等值面即为 sigmoid 的中点,
    #   其形状是圆润的曲面 (不再是矩形硬边界)
    phantom_region = fusion_result[
        start_pos[0]:end_pos[0],
        start_pos[1]:end_pos[1],
        start_pos[2]:end_pos[2]
    ].copy()

    # 替换条件: CT有体 & 权重超过中点 & 体模也有体(避免CT扩展到体外)
    replace_mask = ct_body_mask & (weight_3d > 0.5) & (phantom_region > 0)
    phantom_region[replace_mask] = ct_materials[replace_mask]

    fusion_result[
        start_pos[0]:end_pos[0],
        start_pos[1]:end_pos[1],
        start_pos[2]:end_pos[2]
    ] = phantom_region

    replaced = int(np.sum(replace_mask))
    print(f"  融合完成: 替换体素 {replaced:,} "
          f"({replaced / phantom_data.size * 100:.2f}%)")
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

    # 4. 融合 (Sigmoid过渡带, Kollitz et al. PMB 2022)
    print("\n[步骤4] 融合（Sigmoid过渡带）")
    fusion_result = simple_fusion(
        ct_data, phantom_data, registration,
        transition_cm=10.0,
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
        'version': '5.0_sigmoid_transition',
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