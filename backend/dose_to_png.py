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
from scipy.ndimage import distance_transform_edt


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


def fill_zero_dose_by_distance(dose_array, body_mask, decay_length=20.0):
    """
    用距离衰减填充体内零值区域，确保全身每个体素都有非零剂量。

    对体内零值体素，计算到最近有剂量体素的距离，
    赋值 = boundary_dose * exp(-distance / decay_length)

    Parameters:
    -----------
    dose_array : np.ndarray
        剂量数组（可能有大量零值）
    body_mask : np.ndarray (bool)
        体内mask
    decay_length : float
        衰减常数（体素单位），越大衰减越慢，剂量传播越远

    Returns:
    --------
    np.ndarray: 填充后的剂量数组（体内无零值）
    """
    result = dose_array.copy().astype(np.float64)

    has_dose = result > 0
    body_no_dose = body_mask & (~has_dose)

    if not np.any(body_no_dose):
        return result

    # 获取有剂量区域边缘的低值作为衰减起始值
    positive_vals = result[has_dose]
    boundary_dose = np.percentile(positive_vals, 5)
    if boundary_dose <= 0:
        boundary_dose = positive_vals.min()
    if boundary_dose <= 0:
        boundary_dose = 1e-10

    # 计算每个零值体素到最近有剂量体素的欧氏距离
    dist = distance_transform_edt(~has_dose).astype(np.float64)

    # 指数衰减: dose = boundary_dose * exp(-dist / decay_length)
    fill_values = boundary_dose * np.exp(-dist / decay_length)

    # 只填充体内零值区域
    result[body_no_dose] = fill_values[body_no_dose]

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

    # colormap LUT
    try:
        cmap_fn = plt.colormaps[colormap]
    except (AttributeError, KeyError):
        cmap_fn = plt.get_cmap(colormap)
    lut = (cmap_fn(np.linspace(0, 1, 256)) * 255).astype(np.uint8)

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
            # 直接线性映射到LUT（已经做过对数归一化了）
            idx = (np.clip(dose_slice, 0, 1) * 255).astype(np.uint8)
            colors = lut[idx]

            out_rgba[in_body, 0] = colors[in_body, 0]
            out_rgba[in_body, 1] = colors[in_body, 1]
            out_rgba[in_body, 2] = colors[in_body, 2]
            out_rgba[in_body, 3] = int(dose_alpha * 255)

        # 体外 → 全透明 (已经是0)

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
        print("  [全身体模模式] 剂量图不使用CT灰度，仅使用body mask")
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
            dose_array_resampled, body_mask_3d, decay_length=25.0
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

    # ==================== 7. 生成三视图 ====================
    print("\n[步骤7] 生成三视图切片")

    organ_3d = ref_array if is_wholebody_phantom else None

    sp = ref_img.GetSpacing()
    sp_x, sp_y, sp_z = sp[0], sp[1], sp[2]
    print(f"  参考图体素间距: X={sp_x:.3f}mm, Y={sp_y:.3f}mm, Z={sp_z:.3f}mm")

    views = {}

    # 轴位面 (Axial)
    print("\n  生成轴位面 (Axial)...")
    views['axial'] = {
        'dose': dose_normalized,
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
        'dose': np.transpose(dose_normalized, (1, 0, 2)),
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
        'dose': np.transpose(dose_normalized, (2, 0, 1)),
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
