#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
改进的全身剂量分布可视化程序

功能：
1. 从3D剂量数组生成三个方向（轴位、冠状、矢状）的切片
2. 将剂量图叠加在CT图像上
3. 支持多切片输出
4. 自动处理空间配准和重采样
5. 对零值区域做距离衰减填充，确保全身均有剂量分布显示

Author: BNCT Team
Date: 2026-02-13
"""

import sys
import numpy as np
import SimpleITK as sitk
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.ndimage import gaussian_filter, binary_erosion, binary_closing

# ─── 器官勾画参数（全身体模，与局部CT contour_overlay.py 风格一致）────────
ORGAN_FILL_ALPHA   = 0.30   # 器官填充透明度（低于局部CT的0.45，避免遮挡剂量信息）
ORGAN_BORDER_ALPHA = 0.88   # 器官边框不透明度

# 颜色循环列表（12种，与前端 contourColors 顺序一致）
ORGAN_PALETTE = [
    (230, 200,  50),   # 金黄  - 肝脏
    (220, 100, 100),   # 粉红  - 心脏
    ( 60,  60, 220),   # 深蓝  - 肺
    (100, 200,  80),   # 草绿  - 脾脏
    (200,  80, 200),   # 紫    - 肾
    ( 50, 200, 200),   # 青    - 胰腺
    (220, 130,  50),   # 橙    - 胃
    (150,  80, 220),   # 蓝紫  - 膀胱
    (240,  80,  80),   # 红    - 食管
    ( 80, 220, 160),   # 薄荷绿 - 结肠
    (200, 200,  80),   # 亮黄
    ( 80, 150, 220),   # 天蓝
]

# 器官名称关键词 → 固定颜色（提升临床识别度）
_ORGAN_NAME_COLOR_KEYWORDS = {
    'liver':       (230, 200,  50),
    'heart':       (220, 100, 100),
    'lung':        ( 60,  60, 220),
    'spleen':      (100, 200,  80),
    'kidney':      (200,  80, 200),
    'pancreas':    ( 50, 200, 200),
    'stomach':     (220, 130,  50),
    'bladder':     (150,  80, 220),
    'brain':       (240, 200, 160),
    'cerebellum':  (240, 200, 160),
    'cerebrum':    (240, 200, 160),
    'esophagus':   (240,  80,  80),
    'colon':       ( 80, 220, 160),
    'intestine':   ( 80, 150, 220),
    'thyroid':     (200, 200,  80),
    'thymus':      (220, 160, 220),
    'prostate':    ( 80, 150, 220),
    'testes':      (200, 160,  80),
    'ovary':       (220, 120, 160),
    'uterus':      (240, 160, 180),
    'adrenal':     (100, 200, 200),
    'gallbladder': (160, 220,  80),
    'spinal cord': (200, 160,  80),
}

# 缓存
_ORGAN_COLOR_LUT = None


def _build_organ_color_lut(max_id: int = 1024) -> dict:
    """
    构建 organ_id → (R, G, B) 颜色查找表，用于全身体模器官勾画。

    策略：
    1. 优先从 ICRP-110 材质文件读取器官名称，按关键词分配临床颜色；
       密度 ≥ 1.4 g/cm³（骨骼）的器官跳过，避免视觉混乱。
    2. 材质文件不可用时，根据解剖灰度 LUT 自动判断：
       - 骨骼（灰度 ≥ 160）跳过
       - 气腔（灰度 ≤ 30） → 统一深蓝色
       - 软组织 → 按 ID 循环分配 ORGAN_PALETTE 颜色
    """
    global _ORGAN_COLOR_LUT
    if _ORGAN_COLOR_LUT is not None:
        return _ORGAN_COLOR_LUT

    color_lut = {}

    # ── 1. 尝试从 ICRP-110 材质文件加载 ────────────────────────────────
    loaded = False
    try:
        from icrp110_material_map import ICRP110Materials
        for pt in ['AM', 'AF']:
            try:
                mat = ICRP110Materials(pt)
                for organ_id, (tissue_num, density, name) in mat.organs.items():
                    if organ_id <= 0 or organ_id >= max_id:
                        continue
                    if density >= 1.4:    # 骨骼/高密度 → 跳过
                        continue
                    if density < 0.35:    # 气腔 → 跳过
                        continue
                    name_lower = name.lower()
                    color = None
                    for keyword, c in _ORGAN_NAME_COLOR_KEYWORDS.items():
                        if keyword in name_lower:
                            color = c
                            break
                    if color is None:
                        color = ORGAN_PALETTE[organ_id % len(ORGAN_PALETTE)]
                    color_lut[organ_id] = color
                print(f"  [器官勾画] 从 ICRP-110 {pt} 加载 {len(color_lut)} 种软组织器官颜色")
                loaded = True
                break
            except FileNotFoundError:
                continue
    except Exception:
        pass

    # ── 2. 回落方案：基于解剖灰度 LUT 自动判断 ──────────────────────────
    if not loaded:
        gray_lut = _get_phantom_gray_lut()
        for oid in range(1, max_id):
            g = int(gray_lut[oid])
            if g == 0:          # 体外空气
                continue
            if g >= 160:        # 骨骼（高密度）→ 跳过
                continue
            if g <= 30:         # 肺/气腔（低密度）→ 统一蓝色
                color_lut[oid] = (60, 60, 220)
                continue
            # 软组织：按 ID 循环分配颜色
            color_lut[oid] = ORGAN_PALETTE[oid % len(ORGAN_PALETTE)]
        print(f"  [器官勾画] 使用回落方案，共 {len(color_lut)} 种软组织器官")

    _ORGAN_COLOR_LUT = color_lut
    return color_lut


def _draw_phantom_organ_contours(out_rgba: np.ndarray,
                                  organ_slice: np.ndarray,
                                  body_mask_slice: np.ndarray,
                                  color_lut: dict) -> np.ndarray:
    """
    在已合成的 RGBA 切片上叠加全身体模器官轮廓（半透明填充 + 亮色边框）。

    Parameters
    ----------
    out_rgba : np.ndarray  shape (H, W, 4) uint8
    organ_slice : np.ndarray  shape (H, W) int，器官 ID
    body_mask_slice : np.ndarray  shape (H, W) bool，体内 mask
    color_lut : dict  {organ_id: (R, G, B)}

    Returns
    -------
    out_rgba : np.ndarray  shape (H, W, 4) uint8（原地修改）
    """
    rgb = out_rgba[:, :, :3].astype(np.float32)

    unique_ids = np.unique(organ_slice)
    for raw_oid in unique_ids:
        oid = int(raw_oid)
        if oid not in color_lut:
            continue
        color = color_lut[oid]

        organ_bin = (organ_slice == oid) & body_mask_slice
        if np.sum(organ_bin) < 30:      # 过小的区域（噪声/边界碎片）跳过
            continue

        # ── 半透明填充 ───────────────────────────────────────────────────
        rgb[organ_bin, 0] = (rgb[organ_bin, 0] * (1 - ORGAN_FILL_ALPHA)
                             + color[0] * ORGAN_FILL_ALPHA)
        rgb[organ_bin, 1] = (rgb[organ_bin, 1] * (1 - ORGAN_FILL_ALPHA)
                             + color[1] * ORGAN_FILL_ALPHA)
        rgb[organ_bin, 2] = (rgb[organ_bin, 2] * (1 - ORGAN_FILL_ALPHA)
                             + color[2] * ORGAN_FILL_ALPHA)

        # ── 亮色边框 ─────────────────────────────────────────────────────
        border = organ_bin & ~binary_erosion(organ_bin)
        if border.any():
            bc = tuple(min(255, int(c * 1.3 + 50)) for c in color)
            rgb[border, 0] = (rgb[border, 0] * (1 - ORGAN_BORDER_ALPHA)
                              + bc[0] * ORGAN_BORDER_ALPHA)
            rgb[border, 1] = (rgb[border, 1] * (1 - ORGAN_BORDER_ALPHA)
                              + bc[1] * ORGAN_BORDER_ALPHA)
            rgb[border, 2] = (rgb[border, 2] * (1 - ORGAN_BORDER_ALPHA)
                              + bc[2] * ORGAN_BORDER_ALPHA)

    out_rgba[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return out_rgba


# ─── 体模解剖灰度 LUT（缓存）────────────────────────────────────────────
_PHANTOM_GRAY_LUT = None

def _density_to_gray(density: float) -> int:
    """将组织密度(g/cm³)映射为灰度值，模拟CT HU显示。"""
    if density < 0.5:                   # 肺/气腔 → 暗灰
        return int(np.clip(density * 60, 8, 35))
    elif density < 1.1:                 # 软组织 → 中灰
        return 85
    elif density < 1.5:                 # 软骨/骨髓 → 浅灰白
        return int(np.clip(110 + (density - 1.1) * 150, 110, 170))
    else:                               # 皮质骨 → 亮白
        return int(np.clip(180 + (density - 1.5) * 90, 180, 245))


def _get_phantom_gray_lut() -> np.ndarray:
    """
    构建 organ_id → 灰度值(0-255) 查找表，用于渲染解剖背景。

    优先从 ICRP-110 材质文件（AM_organs.dat / AM_media.dat）加载精确密度映射。
    若文件不存在，回落至合成解剖灰度表。

    CT 融合替换码 (46=骨, 81=肺, 107=软组织) 始终直接映射。
    """
    global _PHANTOM_GRAY_LUT
    if _PHANTOM_GRAY_LUT is not None:
        return _PHANTOM_GRAY_LUT

    lut = np.full(1024, 88, dtype=np.uint8)   # 默认：软组织中灰
    lut[0] = 0                                  # 体外空气 → 黑

    # CT 融合替换码（来自 ct_phantom_fusion.simple_fusion）
    lut[46]  = 215   # CT 骨骼 (HU ≥ 100) → 亮白
    lut[81]  = 25    # CT 肺/体内气腔     → 暗灰
    lut[107] = 88    # CT 软组织          → 中灰
    lut[900] = 88    # 肿瘤软组织 (B-10)  → 中灰

    # ── 从 ICRP-110 材质文件加载精确密度映射 ──────────────────────────
    icrp_loaded = False
    try:
        from icrp110_material_map import ICRP110Materials
        for pt in ['AM', 'AF']:
            try:
                mat = ICRP110Materials(pt)   # 自动在 backend/{pt}/ 下查找
                for organ_id, (_, density, _) in mat.organs.items():
                    if 0 <= organ_id < 1024:
                        lut[organ_id] = _density_to_gray(density)
                print(f"  [anatomy] 已加载 ICRP-110 {pt} 材质密度映射 "
                      f"({len(mat.organs)} 种器官)")
                icrp_loaded = True
                break
            except FileNotFoundError:
                continue
    except Exception as e:
        pass

    # ── 回落：合成解剖灰度表（无需 ICRP 数据文件）────────────────────
    if not icrp_loaded:
        print("  [anatomy] ICRP-110 材质文件不可用，使用合成解剖灰度表")
        # 按已知 ICRP-110 AM 体模器官密度范围批量设置：
        # 器官 ID 1-13: 脊椎各节段 → 骨骼高密度
        for i in range(1, 14):
            lut[i] = 210
        # 器官 ID 14-20: 颅骨/锁骨/肩胛/胸骨/肱骨/尺桡骨 → 骨骼
        for i in range(14, 21):
            lut[i] = 205
        # 器官 ID 21-30: 股骨/胫腓骨/髌骨/手足骨 → 骨骼
        for i in range(21, 31):
            lut[i] = 200
        # 器官 ID 31-40: 肋骨/骨盆 → 骨骼
        for i in range(31, 41):
            lut[i] = 195
        # 器官 ID 50-55: 肺 → 暗灰（低密度）
        for i in range(50, 56):
            lut[i] = 22
        # 器官 ID 60-65: 软骨 → 中等灰白
        for i in range(60, 66):
            lut[i] = 130
        # 其余保持默认软组织灰度 88

    _PHANTOM_GRAY_LUT = lut
    return lut


def normalize_array(array, percentile_clip=99.5):
    """
    归一化数组到0-1范围，可选percentile裁剪
    """
    if array.max() == array.min():
        return np.zeros_like(array)

    if percentile_clip > 0:
        lower = np.percentile(array, 100 - percentile_clip)
        upper = np.percentile(array, percentile_clip)
        array = np.clip(array, lower, upper)

    array_min = array.min()
    array_max = array.max()

    if array_max > array_min:
        normalized = (array - array_min) / (array_max - array_min)
    else:
        normalized = np.zeros_like(array)

    return normalized


def fill_zero_dose_by_distance(dose_array, body_mask, n_iterations=15,
                                sigma=6.0):
    """
    使用迭代高斯扩散填充体内零剂量区域。

    等效于在 Dirichlet 边界条件下求解稳态热传导方程:
      每次迭代: 高斯模糊全场 -> 恢复已知剂量值 -> 体外置零
    经过足够迭代后，剂量从已知区域自然蔓延到全身，
    边界处无硬跳变，过渡天然平滑。

    相比旧版 (normalized Gaussian + cosine taper) 的优势:
    - 无归一化除零问题 (旧版 smoothed_mask -> 0 导致 spread_dose 不稳定)
    - 无二值阈值跳变 (旧版 weights > 0.5 导致硬切换)
    - 参数更少更鲁棒

    Parameters:
    -----------
    dose_array : np.ndarray
        剂量数组（可能有大量零值）
    body_mask : np.ndarray (bool)
        体内mask
    n_iterations : int
        迭代次数，默认15 (sigma=6时有效扩散半径 ~15*18=270体素，足够覆盖全身)
    sigma : float
        高斯核标准差（体素单位），默认6.0

    Returns:
    --------
    np.ndarray: 填充后的剂量数组（体内无零值，边界无缝过渡）
    """
    original = dose_array.copy().astype(np.float64)

    has_dose = original > 0
    body_no_dose = body_mask & (~has_dose)

    if not np.any(body_no_dose):
        return original

    known_dose = original.copy()
    result = original.copy()

    body_has = int(np.sum(has_dose & body_mask))
    body_total = int(np.sum(body_mask))
    print(f"  [迭代扩散] 体内有剂量: {body_has}/{body_total} "
          f"({body_has / max(body_total, 1) * 100:.1f}%)")
    print(f"  [迭代扩散] 参数: {n_iterations}次迭代, sigma={sigma}")

    for _ in range(n_iterations):
        result = gaussian_filter(result, sigma=sigma)
        result[has_dose] = known_dose[has_dose]   # Dirichlet: 恢复已知值
        result[~body_mask] = 0.0                   # 体外置零

    result = np.maximum(result, 0.0)

    filled_count = int(np.sum(body_mask & (result > 0))) - body_has
    print(f"  [迭代扩散] 新填充体素: {filled_count:,}")

    return result


def log_normalize(dose_array, body_mask, log_orders=7):
    """
    对数归一化：将剂量映射到0-1，使用对数色标跨越多个数量级。
    参考BNCT文献的色标: 1e-7 ~ 10 Gy (约8个数量级)

    Parameters:
    -----------
    dose_array : np.ndarray
        剂量数组（体内应无零值）
    body_mask : np.ndarray (bool)
        体内mask
    log_orders : int
        对数跨越的数量级数（默认7, 即最大值/10^7 为最小值）

    Returns:
    --------
    np.ndarray: 对数归一化后的数组 (0~1)
    """
    result = np.zeros_like(dose_array, dtype=np.float32)

    body_vals = dose_array[body_mask]
    if len(body_vals) == 0 or body_vals.max() <= 0:
        return result

    dose_max = np.percentile(body_vals, 99.9)
    if dose_max <= 0:
        dose_max = body_vals.max()

    dose_min = dose_max / (10.0 ** log_orders)

    # 裁剪到 [dose_min, dose_max]
    clipped = np.clip(dose_array, dose_min, dose_max)

    # log10 归一化到 0~1
    log_val = np.log10(clipped / dose_min)
    log_max = np.log10(dose_max / dose_min)

    if log_max > 0:
        result = (log_val / log_max).astype(np.float32)

    # 体外置零
    result[~body_mask] = 0.0

    return result


def save_overlay_slices(dose_data, ct_data, output_dir, view_name,
                        dose_alpha=0.85, slice_interval=1, colormap='jet',
                        figsize=None, body_mask=None,
                        pixel_spacing_hw=(1.0, 1.0),
                        organ_data=None):
    """
    保存全身剂量分布切片（参考BNCT文献的彩色全身热力图风格）。

    体内所有体素都用jet彩色（红=高，黄/绿=中，蓝=低），
    体外完全透明。
    """
    from PIL import Image

    view_dir = Path(output_dir) / view_name
    view_dir.mkdir(parents=True, exist_ok=True)

    num_slices = dose_data.shape[0]
    h, w = dose_data.shape[1], dose_data.shape[2]

    print(f"\n[保存 {view_name} 切片] — 全身彩色剂量热力图")
    print(f"  总切片数: {num_slices}, 切片尺寸: {w}×{h}")
    print(f"  色图: {colormap}, 剂量alpha: {dose_alpha}")

    # 构建器官颜色查找表（仅在全身体模模式下一次性构建）
    organ_color_lut = {}
    if organ_data is not None:
        organ_color_lut = _build_organ_color_lut()

    # colormap LUT
    try:
        cmap_fn = plt.colormaps[colormap]
    except (AttributeError, KeyError):
        cmap_fn = plt.get_cmap(colormap)
    lut = (cmap_fn(np.linspace(0, 1, 256)) * 255).astype(np.uint8)

    # 解剖背景 LUT（当 organ_data 存在时启用）
    gray_lut = _get_phantom_gray_lut() if organ_data is not None else None
    # 剂量叠加参数：使用动态 alpha，剂量高→颜色主导，剂量低→解剖清晰可见
    # MIN_DOSE_ALPHA: 零剂量时的最小透明度（解剖背景始终可见）
    # MAX_DOSE_ALPHA: 满剂量时的最大透明度
    MIN_DOSE_ALPHA = 0.30   # 低剂量区域（全身远端）：70%解剖背景，30%蓝色剂量
    MAX_DOSE_ALPHA = 0.72   # 高剂量区域（源照射区）：28%解剖背景，72%剂量颜色

    saved_count = 0
    for i in range(0, num_slices, slice_interval):

        # mask
        if body_mask is not None:
            mask = body_mask[i].astype(np.uint8)
        else:
            mask = np.ones((h, w), dtype=np.uint8)

        out_rgba = np.zeros((h, w, 4), dtype=np.uint8)

        dose_slice = dose_data[i].copy()

        # 体内区域全部用jet着色（dose_data已经是0~1对数归一化值）
        in_body = (mask == 1)

        if np.any(in_body):
            # 剂量颜色（jet LUT）
            idx = (np.clip(dose_slice, 0, 1) * 255).astype(np.uint8)
            colors = lut[idx]   # shape (h, w, 4)

            if gray_lut is not None:
                # ── 有解剖背景：动态 alpha 透明叠加 ─────────────────────────
                # 步骤1: 解剖灰度背景（来自ICRP体模器官ID）
                organ_sl = organ_data[i]
                organ_ids = np.clip(organ_sl, 0, 1023).astype(np.int32)
                gray_bg = gray_lut[organ_ids].astype(np.float32)   # (h, w) 0-255

                # 步骤2: 基于剂量值计算动态透明度
                #   低剂量区（骨骼/肺等远离源区）→ 解剖结构清晰可见
                #   高剂量区（源照射区）→ 剂量颜色主导
                dose_vals = np.clip(dose_slice, 0.0, 1.0)
                alpha_map = (MIN_DOSE_ALPHA +
                             (MAX_DOSE_ALPHA - MIN_DOSE_ALPHA) * dose_vals)  # (h,w)
                inv_alpha = 1.0 - alpha_map

                # 步骤3: alpha 合成 = 剂量颜色 × alpha + 解剖灰度 × (1-alpha)
                d_r = colors[:, :, 0].astype(np.float32)
                d_g = colors[:, :, 1].astype(np.float32)
                d_b = colors[:, :, 2].astype(np.float32)

                r = np.clip(d_r * alpha_map + gray_bg * inv_alpha, 0, 255).astype(np.uint8)
                g = np.clip(d_g * alpha_map + gray_bg * inv_alpha, 0, 255).astype(np.uint8)
                b = np.clip(d_b * alpha_map + gray_bg * inv_alpha, 0, 255).astype(np.uint8)

                out_rgba[in_body, 0] = r[in_body]
                out_rgba[in_body, 1] = g[in_body]
                out_rgba[in_body, 2] = b[in_body]
                out_rgba[in_body, 3] = 255   # 不透明：解剖+剂量已合成在像素内
            else:
                # ── 无解剖背景：原始行为（纯剂量热图）───────────────────────
                out_rgba[in_body, 0] = colors[in_body, 0]
                out_rgba[in_body, 1] = colors[in_body, 1]
                out_rgba[in_body, 2] = colors[in_body, 2]
                out_rgba[in_body, 3] = int(dose_alpha * 255)

        # 体外 → 全透明 (已经是0)

        # ── 叠加器官勾画轮廓（仅全身体模模式）─────────────────────────────
        if organ_data is not None and organ_color_lut:
            organ_sl = organ_data[i]
            _draw_phantom_organ_contours(out_rgba, organ_sl, in_body, organ_color_lut)

        # 垂直翻转，使图像符合医学影像惯例（与nii_preview.py的origin='lower'一致）
        out_rgba = out_rgba[::-1]

        img = Image.fromarray(out_rgba, mode='RGBA')

        # 按物理尺寸比例缩放图片
        sp_h, sp_w = pixel_spacing_hw
        if abs(sp_h - sp_w) > 0.01:
            scale_h = sp_h / sp_w
            new_h = int(h * scale_h)
            new_w = w
            img = img.resize((new_w, new_h), Image.LANCZOS)

        out_path = view_dir / f'{view_name}_{i:03d}.png'
        img.save(str(out_path), format='PNG')
        saved_count += 1

    print(f"  ✓ 已保存 {saved_count} 张切片到: {view_dir}")
    return saved_count


def process_dose_3d(npy_path, output_dir, ref_nii_path,
                   slice_interval=1, dose_threshold=0.001):
    """
    处理3D剂量分布并生成三视图切片

    Parameters:
    -----------
    npy_path : str
        剂量.npy文件路径
    output_dir : str
        输出目录
    ref_nii_path : str
        参考CT的NIfTI文件路径
    slice_interval : int
        切片间隔（减少文件数量）
    dose_threshold : float
        (保留参数但不再用于渲染阈值)

    Returns:
    --------
    dict: 包含各视图文件列表的字典
    """

    print("="*60)
    print("全身剂量分布3D可视化")
    print("="*60)
    print(f"剂量文件: {npy_path}")
    print(f"参考CT: {ref_nii_path}")
    print(f"输出目录: {output_dir}")
    print(f"切片间隔: {slice_interval}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ==================== 1. 读取参考CT ====================
    print("\n[步骤1] 读取参考CT图像")
    ref_img = sitk.ReadImage(ref_nii_path)
    ref_array = sitk.GetArrayFromImage(ref_img)

    print(f"  CT shape: {ref_array.shape}")
    print(f"  CT spacing: {ref_img.GetSpacing()}")
    print(f"  CT origin: {ref_img.GetOrigin()}")
    print(f"  CT 数值范围: {ref_array.min():.1f} ~ {ref_array.max():.1f}")

    is_wholebody_phantom = 'fused_phantom' in str(ref_nii_path)
    if is_wholebody_phantom:
        print("  [全身体模模式] 剂量图不使用CT灰度，使用解剖体模灰度作为背景")
        ct_normalized = np.zeros_like(ref_array, dtype=np.float32)
    else:
        ct_normalized = normalize_array(ref_array, percentile_clip=99.5)

    # ==================== 2. 读取剂量数据 ====================
    print("\n[步骤2] 读取剂量数据")
    dose_array = np.load(npy_path)

    print(f"  原始剂量 shape: {dose_array.shape}")
    print(f"  原始剂量范围: {dose_array.min():.2e} ~ {dose_array.max():.2e}")

    non_zero = np.count_nonzero(dose_array)
    valid_dose = np.sum((dose_array > 0) & (dose_array < 1e20))
    print(f"  非零值: {non_zero} ({non_zero/dose_array.size*100:.1f}%)")
    print(f"  有效剂量值: {valid_dose} ({valid_dose/dose_array.size*100:.1f}%)")

    # ==================== 3. 空间配准 ====================
    print("\n[步骤3] 空间配准和重采样")

    nz_d, ny_d, nx_d = dose_array.shape
    is_wholebody_phantom = 'fused_phantom' in str(ref_nii_path)

    if is_wholebody_phantom:
        PHANTOM_VX_MM, PHANTOM_VY_MM, PHANTOM_VZ_MM = 2.137, 2.137, 8.0
        dose_spacing_mm = (
            PHANTOM_VX_MM * (ref_array.shape[2] / nx_d),
            PHANTOM_VY_MM * (ref_array.shape[1] / ny_d),
            PHANTOM_VZ_MM * (ref_array.shape[0] / nz_d),
        )
        print("  [全身体模模式] 使用ICRP-110体模体素尺寸")
        print(f"  体模尺寸(Z,Y,X): {ref_array.shape}")
        print(f"  剂量网格(Z,Y,X): {dose_array.shape}")
        print(f"  剂量体素间距(mm): {dose_spacing_mm}")
        dose_img = sitk.GetImageFromArray(dose_array.astype(np.float32))
        dose_img.SetSpacing(dose_spacing_mm)
        dose_img.SetOrigin(ref_img.GetOrigin())
        dose_img.SetDirection(ref_img.GetDirection())
    else:
        ref_size = ref_img.GetSize()
        ref_sp   = ref_img.GetSpacing()
        ct_phys  = [ref_size[i] * ref_sp[i] for i in range(3)]
        dose_spacing_mm = (ct_phys[0] / nx_d, ct_phys[1] / ny_d, ct_phys[2] / nz_d)
        print(f"  [局部CT模式] CT物理范围: {ct_phys} mm")
        print(f"  估算剂量体素间距: {dose_spacing_mm} mm")
        dose_img = sitk.GetImageFromArray(dose_array.astype(np.float32))
        dose_img.SetSpacing(dose_spacing_mm)
        dose_img.SetOrigin(ref_img.GetOrigin())
        dose_img.SetDirection(ref_img.GetDirection())

    print("  执行重采样，对齐到参考图空间...")
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(ref_img)
    resampler.SetInterpolator(sitk.sitkLinear)
    resampler.SetDefaultPixelValue(0)
    dose_img_resampled = resampler.Execute(dose_img)
    dose_array_resampled = sitk.GetArrayFromImage(dose_img_resampled)
    print(f"  重采样后 shape: {dose_array_resampled.shape}")

    # ==================== 4. 构建体内mask ====================
    print("\n[步骤4] 构建体内mask")
    if is_wholebody_phantom:
        body_mask_3d = (ref_array != 0)
        # 闭运算填充盆骨与大腿之间的体素间隙，消除冠状/矢状视图中的横向缝线
        from numpy import ones
        body_mask_3d = binary_closing(body_mask_3d, structure=ones((3, 3, 3), dtype=bool))
    else:
        raw_hu = ref_array.astype(np.float32)
        body_mask_3d = (raw_hu > -900)

    non_zero_voxels = np.sum(body_mask_3d)
    total_voxels = body_mask_3d.size
    print(f"  体内体素: {non_zero_voxels} / {total_voxels} ({non_zero_voxels/total_voxels*100:.1f}%)")

    # ==================== 5. 全身剂量填充 ====================
    # 关键步骤：对体内零值区域用距离衰减填充，确保全身都有剂量
    print("\n[步骤5] 全身剂量填充（距离衰减）")

    has_dose = dose_array_resampled > 0
    body_zero = body_mask_3d & (~has_dose)
    body_zero_count = np.sum(body_zero)
    body_total = np.sum(body_mask_3d)
    print(f"  体内有剂量: {body_total - body_zero_count} / {body_total} "
          f"({(body_total - body_zero_count)/max(body_total,1)*100:.1f}%)")
    print(f"  体内零值（需填充）: {body_zero_count} ({body_zero_count/max(body_total,1)*100:.1f}%)")

    if body_zero_count > 0 and np.any(has_dose):
        dose_array_filled = fill_zero_dose_by_distance(
            dose_array_resampled, body_mask_3d,
            n_iterations=50, sigma=8.0
        )
        new_zero = np.sum(body_mask_3d & (dose_array_filled <= 0))
        print(f"  填充后体内零值: {new_zero}")
        print(f"  填充后范围: {dose_array_filled[body_mask_3d].min():.2e} ~ "
              f"{dose_array_filled[body_mask_3d].max():.2e}")
    else:
        dose_array_filled = dose_array_resampled.astype(np.float64)
        print("  体内无零值，跳过填充")

    # ==================== 6. 对数归一化 ====================
    print("\n[步骤6] 对数归一化（参考文献色标: 跨7个数量级）")
    dose_normalized = log_normalize(dose_array_filled, body_mask_3d, log_orders=7)

    body_vals = dose_normalized[body_mask_3d]
    if len(body_vals) > 0:
        print(f"  体内归一化值范围: {body_vals.min():.4f} ~ {body_vals.max():.4f}")
        print(f"  体内均值: {body_vals.mean():.4f}")

    # 6.1 视觉增强：为体内所有体素设置最小显示值，让全身出现剂量颜色分布
    # 填充后远端体素剂量极小（~1e-16），log归一化后截断为0，远端区域无颜色
    # 设置最小显示值（对应 jet 蓝色端），保持骨骼/肺等解剖结构可见
    BODY_DISPLAY_FLOOR = 0.04   # jet 蓝端（全身远端呈深蓝色）
    dose_display = dose_normalized.copy()
    below_floor = body_mask_3d & (dose_display < BODY_DISPLAY_FLOOR)
    floor_count = int(np.sum(below_floor))
    dose_display[below_floor] = BODY_DISPLAY_FLOOR
    print(f"  [全身显示] 设置最小显示值 {BODY_DISPLAY_FLOOR}: 影响 {floor_count:,} 体素 "
          f"({floor_count / max(1, int(body_mask_3d.sum())) * 100:.1f}%)")

    # ==================== 7. 生成三视图 ====================
    print("\n[步骤7] 生成三视图切片")

    # 优先使用原始ICRP体模（保留140种器官细节）作为解剖背景
    # 若不存在则回落到融合体模
    if is_wholebody_phantom:
        icrp_path = Path(ref_nii_path).parent / 'icrp_phantom.nii.gz'
        if icrp_path.exists():
            print(f"  [解剖背景] 加载原始ICRP体模: {icrp_path}")
            icrp_img = sitk.ReadImage(str(icrp_path))
            organ_3d = sitk.GetArrayFromImage(icrp_img)
            print(f"  ICRP体模 shape: {organ_3d.shape}, "
                  f"器官ID范围: {organ_3d.min()} ~ {organ_3d.max()}")
        else:
            print("  [解剖背景] 未找到icrp_phantom.nii.gz，使用融合体模")
            organ_3d = ref_array
    else:
        organ_3d = None

    sp = ref_img.GetSpacing()
    sp_x, sp_y, sp_z = sp[0], sp[1], sp[2]
    print(f"  参考图体素间距: X={sp_x:.3f}mm, Y={sp_y:.3f}mm, Z={sp_z:.3f}mm")

    views = {}

    # 轴位面 (Axial)
    print("\n  生成轴位面 (Axial)...")
    views['axial'] = {
        'dose': dose_display,
        'ct': ct_normalized
    }
    axial_count = save_overlay_slices(
        views['axial']['dose'],
        views['axial']['ct'],
        output_dir,
        'axial',
        dose_alpha=0.85,
        slice_interval=slice_interval,
        body_mask=body_mask_3d,
        pixel_spacing_hw=(sp_y, sp_x),
        organ_data=organ_3d
    )

    # 冠状面 (Coronal)
    print("\n  生成冠状面 (Coronal)...")
    body_mask_coronal = np.transpose(body_mask_3d, (1, 0, 2))
    organ_coronal = np.transpose(organ_3d, (1, 0, 2)) if organ_3d is not None else None
    views['coronal'] = {
        'dose': np.transpose(dose_display, (1, 0, 2)),
        'ct': np.transpose(ct_normalized, (1, 0, 2))
    }
    coronal_count = save_overlay_slices(
        views['coronal']['dose'],
        views['coronal']['ct'],
        output_dir,
        'coronal',
        dose_alpha=0.85,
        slice_interval=slice_interval,
        body_mask=body_mask_coronal,
        pixel_spacing_hw=(sp_z, sp_x),
        organ_data=organ_coronal
    )

    # 矢状面 (Sagittal)
    print("\n  生成矢状面 (Sagittal)...")
    body_mask_sagittal = np.transpose(body_mask_3d, (2, 0, 1))
    organ_sagittal = np.transpose(organ_3d, (2, 0, 1)) if organ_3d is not None else None
    views['sagittal'] = {
        'dose': np.transpose(dose_display, (2, 0, 1)),
        'ct': np.transpose(ct_normalized, (2, 0, 1))
    }
    sagittal_count = save_overlay_slices(
        views['sagittal']['dose'],
        views['sagittal']['ct'],
        output_dir,
        'sagittal',
        dose_alpha=0.85,
        slice_interval=slice_interval,
        body_mask=body_mask_sagittal,
        pixel_spacing_hw=(sp_z, sp_y),
        organ_data=organ_sagittal
    )

    # ==================== 8. 生成汇总信息 ====================
    print("\n" + "="*60)
    print("✓ 全身剂量分布可视化完成！")
    print("="*60)
    print(f"输出目录: {output_dir}")
    print(f"  - 轴位面: {axial_count} 张切片")
    print(f"  - 冠状面: {coronal_count} 张切片")
    print(f"  - 矢状面: {sagittal_count} 张切片")
    print(f"  总计: {axial_count + coronal_count + sagittal_count} 张图像")

    result = {}
    for view_name in ['axial', 'coronal', 'sagittal']:
        view_dir = output_dir / view_name
        if view_dir.exists():
            files = sorted(view_dir.glob('*.png'))
            result[view_name] = [str(f) for f in files]

    return result


def main():
    """主函数"""
    if len(sys.argv) < 4:
        print("用法: python dose_to_png.py <dose.npy> <output_dir> <ref_ct.nii> [slice_interval]")
        print("\n参数说明:")
        print("  dose.npy        - 剂量数据文件（3D numpy数组）")
        print("  output_dir      - 输出目录")
        print("  ref_ct.nii      - 参考CT的NIfTI文件")
        print("  slice_interval  - 切片间隔，默认1（可选）")
        print("\n示例:")
        print("  python dose_to_png.py dose_1.npy ./output CT.nii 2")
        sys.exit(1)

    npy_path = sys.argv[1]
    output_dir = sys.argv[2]
    ref_nii_path = sys.argv[3]
    slice_interval = int(sys.argv[4]) if len(sys.argv) > 4 else 1

    try:
        result = process_dose_3d(
            npy_path,
            output_dir,
            ref_nii_path,
            slice_interval=slice_interval
        )

        print("\n文件已生成:")
        for view, files in result.items():
            print(f"  {view}: {len(files)} 个文件")

    except Exception as e:
        print(f"\n[错误] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
