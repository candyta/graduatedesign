#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
改进的全身剂量分布可视化程序

功能：
1. 从3D剂量数组生成三个方向（轴位、冠状、矢状）的切片
2. 将剂量图叠加在CT图像上
3. 支持多切片输出
4. 自动处理空间配准和重采样

Author: BNCT Team
Date: 2026-02-13
"""

import sys
import numpy as np
import SimpleITK as sitk
import matplotlib.pyplot as plt
from pathlib import Path


def normalize_array(array, percentile_clip=99.5):
    """
    归一化数组到0-1范围，可选percentile裁剪
    
    Parameters:
    -----------
    array : np.ndarray
        输入数组
    percentile_clip : float
        百分位裁剪阈值，用于去除极值
        
    Returns:
    --------
    np.ndarray: 归一化后的数组
    """
    if array.max() == array.min():
        return np.zeros_like(array)
    
    # 使用percentile裁剪去除极值
    if percentile_clip > 0:
        lower = np.percentile(array, 100 - percentile_clip)
        upper = np.percentile(array, percentile_clip)
        array = np.clip(array, lower, upper)
    
    # 归一化到0-1
    array_min = array.min()
    array_max = array.max()
    
    if array_max > array_min:
        normalized = (array - array_min) / (array_max - array_min)
    else:
        normalized = np.zeros_like(array)
    
    return normalized


def make_transparent_dose_cmap(base_cmap_name='hot', dose_alpha=0.5, threshold=0.05):
    """
    构建带透明度的剂量色图：
    低于阈值完全透明，超过阈值 alpha 线性升至 dose_alpha，确保CT底图始终可见。
    """
    import matplotlib.colors as mcolors
    base = plt.get_cmap(base_cmap_name)
    colors = base(np.linspace(0, 1, 256))
    # alpha 通道
    alphas = np.linspace(0, 1, 256)
    alphas[alphas < threshold] = 0.0
    colors[:, 3] = np.clip(alphas, 0, 1) * dose_alpha
    return mcolors.ListedColormap(colors)


def save_overlay_slices(dose_data, ct_data, output_dir, view_name,
                        dose_alpha=0.5, dose_threshold=0.01,
                        slice_interval=1, colormap='jet',
                        figsize=None, body_mask=None,
                        pixel_spacing_hw=(1.0, 1.0),
                        organ_data=None):
    """
    保存全身剂量分布切片（参考BNCT文献的彩色全身热力图风格）。

    - 体内有剂量：jet彩色（红=高，黄/绿=中，蓝=低）
    - 体内无剂量：深色填充（显示人体轮廓）
    - 体外：完全透明
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
        dose_slice[mask == 0] = 0.0

        # 体内有剂量区域 → jet彩色
        has_dose = (dose_slice > dose_threshold) & (mask == 1)

        if np.any(has_dose):
            # 对数缩放扩展低剂量颜色区分度
            dose_log = np.zeros_like(dose_slice)
            log_range = np.log10(1.0 / max(dose_threshold, 1e-10))
            dose_log[has_dose] = np.log10(
                dose_slice[has_dose] / dose_threshold
            ) / log_range
            dose_log = np.clip(dose_log, 0, 1)

            idx = (dose_log * 255).astype(np.uint8)
            colors = lut[idx]

            out_rgba[has_dose, 0] = colors[has_dose, 0]
            out_rgba[has_dose, 1] = colors[has_dose, 1]
            out_rgba[has_dose, 2] = colors[has_dose, 2]
            out_rgba[has_dose, 3] = int(dose_alpha * 255)

        # 体内无剂量区域 → 可见的深色填充（显示全身体模轮廓）
        # 参考文献中用深蓝绿色，在黑色背景上清晰可辨
        no_dose = (mask == 1) & (~has_dose)
        out_rgba[no_dose, 0] = 25    # R
        out_rgba[no_dose, 1] = 60    # G
        out_rgba[no_dose, 2] = 80    # B (深蓝绿色)
        out_rgba[no_dose, 3] = 255   # 完全不透明

        # 体外 → 全透明 (已经是0)

        img = Image.fromarray(out_rgba, mode='RGBA')
        
        # 按物理尺寸比例缩放图片
        # pixel_spacing_hw = (H方向mm/pixel, W方向mm/pixel)
        # 如果H和W的间距不同，需要缩放使像素反映真实物理比例
        sp_h, sp_w = pixel_spacing_hw
        if abs(sp_h - sp_w) > 0.01:  # 间距不等，需要缩放
            # 物理尺寸: phys_h = h * sp_h, phys_w = w * sp_w
            # 以W方向为基准，缩放H方向
            scale_h = sp_h / sp_w  # H方向每像素对应的物理长度 / W方向的
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
        剂量显示阈值（0-1，归一化后）
        
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
    print(f"剂量阈值: {dose_threshold}")
    
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

    # 如果是全身融合体模（器官ID 0~139），不需要转HU灰度
    # 我们只需要 body_mask 和 organ ID 来确定体内/体外
    is_wholebody_phantom = 'fused_phantom' in str(ref_nii_path)
    if is_wholebody_phantom:
        print("  [全身体模模式] 剂量图不使用CT灰度，仅使用body mask")
        ct_normalized = np.zeros_like(ref_array, dtype=np.float32)  # 占位，不实际使用
    else:
        # 真实CT：percentile归一化（备用）
        ct_normalized = normalize_array(ref_array, percentile_clip=99.5)
    
    # ==================== 2. 读取剂量数据 ====================
    print("\n[步骤2] 读取剂量数据")
    dose_array = np.load(npy_path)
    
    print(f"  原始剂量 shape: {dose_array.shape}")
    print(f"  原始剂量范围: {dose_array.min():.2e} ~ {dose_array.max():.2e}")
    
    # 统计有效剂量
    non_zero = np.count_nonzero(dose_array)
    valid_dose = np.sum((dose_array > 0) & (dose_array < 1e20))
    print(f"  非零值: {non_zero} ({non_zero/dose_array.size*100:.1f}%)")
    print(f"  有效剂量值: {valid_dose} ({valid_dose/dose_array.size*100:.1f}%)")
    
    # ==================== 3. 空间配准 ====================
    print("\n[步骤3] 空间配准和重采样")

    nz_d, ny_d, nx_d = dose_array.shape

    # 判断参考图是否为全身融合体模
    is_wholebody_phantom = 'fused_phantom' in str(ref_nii_path)

    if is_wholebody_phantom:
        # 参考图是全身体模 (254×127×222 体素)
        # ICRP-110 体模已知体素尺寸：X/Y = 2.137 mm，Z = 8.0 mm
        # MCNP FMESH网格与降采样后的体素对齐
        # 降采样因子 = 体模shape / 剂量shape (每个方向)
        PHANTOM_VX_MM, PHANTOM_VY_MM, PHANTOM_VZ_MM = 2.137, 2.137, 8.0
        dose_spacing_mm = (
            PHANTOM_VX_MM * (ref_array.shape[2] / nx_d),  # X方向
            PHANTOM_VY_MM * (ref_array.shape[1] / ny_d),  # Y方向
            PHANTOM_VZ_MM * (ref_array.shape[0] / nz_d),  # Z方向
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
        # 参考图是局部CT，根据CT物理范围反推剂量体素间距
        ref_size = ref_img.GetSize()      # (W, H, D) in pixels
        ref_sp   = ref_img.GetSpacing()   # mm/pixel
        ct_phys  = [ref_size[i] * ref_sp[i] for i in range(3)]  # 物理尺寸 mm
        dose_spacing_mm = (ct_phys[0] / nx_d, ct_phys[1] / ny_d, ct_phys[2] / nz_d)
        print(f"  [局部CT模式] CT物理范围: {ct_phys} mm")
        print(f"  估算剂量体素间距: {dose_spacing_mm} mm")
        dose_img = sitk.GetImageFromArray(dose_array.astype(np.float32))
        dose_img.SetSpacing(dose_spacing_mm)
        dose_img.SetOrigin(ref_img.GetOrigin())
        dose_img.SetDirection(ref_img.GetDirection())

    # 重采样到参考图空间（spacing/origin/direction/size 完全对齐）
    print("  执行重采样，对齐到参考图空间...")
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(ref_img)
    resampler.SetInterpolator(sitk.sitkLinear)
    resampler.SetDefaultPixelValue(0)
    dose_img_resampled = resampler.Execute(dose_img)
    dose_array_resampled = sitk.GetArrayFromImage(dose_img_resampled)
    print(f"  重采样后 shape: {dose_array_resampled.shape}")
    
    # 归一化剂量到0-1
    dose_normalized = normalize_array(dose_array_resampled, percentile_clip=99.9)
    
    print(f"  归一化后剂量范围: {dose_normalized.min():.3f} ~ {dose_normalized.max():.3f}")

    # ==================== 4. 构建体内mask ====================
    # 体内mask：organ ID != 0（对于全身体模）；对于真实CT，使用HU阈值
    print("\n[步骤4a] 构建体内mask（用于剔除体外区域）")
    if is_wholebody_phantom:
        # 全身体模：organ ID=0 是体外/真空，其余均为体内器官
        body_mask_3d = (ref_array != 0)  # (Z, Y, X) bool
    else:
        # 真实CT：HU < -900 视为体外空气
        raw_hu = ref_array.astype(np.float32)
        body_mask_3d = (raw_hu > -900)
    
    non_zero_voxels = np.sum(body_mask_3d)
    total_voxels = body_mask_3d.size
    print(f"  体内体素: {non_zero_voxels} / {total_voxels} ({non_zero_voxels/total_voxels*100:.1f}%)")

    # ==================== 5. 生成三视图 ====================
    print("\n[步骤5] 生成三视图切片")
    
    # 准备器官ID数组（用于边界检测）
    # ref_array 对于全身体模就是器官ID (0~140)
    organ_3d = ref_array if is_wholebody_phantom else None

    # 定义三个标准视图
    sp = ref_img.GetSpacing()  # (sp_x, sp_y, sp_z) mm
    sp_x, sp_y, sp_z = sp[0], sp[1], sp[2]
    print(f"  参考图体素间距: X={sp_x:.3f}mm, Y={sp_y:.3f}mm, Z={sp_z:.3f}mm")

    views = {}
    
    # 轴位面 (Axial) - 水平切片，沿Z轴
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
        dose_threshold=dose_threshold,
        slice_interval=slice_interval,
        body_mask=body_mask_3d,
        pixel_spacing_hw=(sp_y, sp_x),
        organ_data=organ_3d
    )
    
    # 冠状面 (Coronal) - 前后切片
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
        dose_threshold=dose_threshold,
        slice_interval=slice_interval,
        body_mask=body_mask_coronal,
        pixel_spacing_hw=(sp_z, sp_x),
        organ_data=organ_coronal
    )
    
    # 矢状面 (Sagittal) - 左右切片
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
        dose_threshold=dose_threshold,
        slice_interval=slice_interval,
        body_mask=body_mask_sagittal,
        pixel_spacing_hw=(sp_z, sp_y),
        organ_data=organ_sagittal
    )
    
    # ==================== 6. 生成汇总信息 ====================
    print("\n" + "="*60)
    print("✓ 全身剂量分布可视化完成！")
    print("="*60)
    print(f"输出目录: {output_dir}")
    print(f"  - 轴位面: {axial_count} 张切片")
    print(f"  - 冠状面: {coronal_count} 张切片")
    print(f"  - 矢状面: {sagittal_count} 张切片")
    print(f"  总计: {axial_count + coronal_count + sagittal_count} 张图像")
    
    # 返回文件路径
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
        print("用法: python dose_to_png_improved.py <dose.npy> <output_dir> <ref_ct.nii> [slice_interval] [dose_threshold]")
        print("\n参数说明:")
        print("  dose.npy        - 剂量数据文件（3D numpy数组）")
        print("  output_dir      - 输出目录")
        print("  ref_ct.nii      - 参考CT的NIfTI文件")
        print("  slice_interval  - 切片间隔，默认2（可选）")
        print("  dose_threshold  - 剂量显示阈值(0-1)，默认0.001（可选）")
        print("\n示例:")
        print("  python dose_to_png_improved.py dose_1.npy ./output CT.nii 2 0.05")
        sys.exit(1)
    
    npy_path = sys.argv[1]
    output_dir = sys.argv[2]
    ref_nii_path = sys.argv[3]
    slice_interval = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    dose_threshold = float(sys.argv[5]) if len(sys.argv) > 5 else 0.001
    
    try:
        result = process_dose_3d(
            npy_path,
            output_dir,
            ref_nii_path,
            slice_interval=slice_interval,
            dose_threshold=dose_threshold
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