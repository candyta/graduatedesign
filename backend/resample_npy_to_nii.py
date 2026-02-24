# -*- coding: utf-8 -*-
# resample_npy_to_nii.py
import numpy as np
import SimpleITK as sitk
import sys
print("[PYTHON] resample_npy_to_nii.py 启动")
print("[PYTHON] 参数：", sys.argv)
def resample_npy_to_nii(npy_path, reference_nii_path, output_nii_path):
    # 读取剂量数据（形状为 nz, ny, nx —— MCNP体模体素空间）
    dose_array = np.load(npy_path)
    print(f"[INFO] 剂量数组形状: {dose_array.shape}")

    # 读取参考CT图像
    ref_image = sitk.ReadImage(reference_nii_path)
    ref_size    = ref_image.GetSize()       # (W, H, D) 像素数
    ref_spacing = ref_image.GetSpacing()    # mm/像素
    ref_origin  = ref_image.GetOrigin()
    ref_dir     = ref_image.GetDirection()
    print(f"[INFO] CT size={ref_size}, spacing={ref_spacing}, origin={ref_origin}")

    # ---- 剂量图自身的物理尺寸 ----
    # 剂量数组 (nz, ny, nx)，每个体素对应 ICRP-110 体模体素间距（默认2.137 mm）
    # 用参考CT的物理范围来估计合适的剂量体素尺寸，使总体尺寸匹配
    nz, ny, nx = dose_array.shape
    ct_physical = [ref_size[i] * ref_spacing[i] for i in range(3)]  # mm
    # 剂量网格spacing：让剂量覆盖范围 ≈ CT物理范围
    dose_spacing = (
        ct_physical[0] / nx,
        ct_physical[1] / ny,
        ct_physical[2] / nz,
    )
    print(f"[INFO] 估算剂量体素间距: {dose_spacing} mm")

    # 创建剂量 SimpleITK 图像，使用与CT相同的origin/direction，但自己的spacing
    dose_image = sitk.GetImageFromArray(dose_array.astype(np.float32))
    dose_image.SetSpacing(dose_spacing)
    dose_image.SetOrigin(ref_origin)
    dose_image.SetDirection(ref_dir)

    # 重采样到CT网格（尺寸、spacing、origin、direction 完全对齐）
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(ref_image)
    resampler.SetInterpolator(sitk.sitkLinear)
    resampler.SetDefaultPixelValue(0)
    aligned_dose_image = resampler.Execute(dose_image)

    # 保存为 .nii
    sitk.WriteImage(aligned_dose_image, output_nii_path)
    print(f"[INFO] 剂量图已保存为: {output_nii_path}")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("用法: python resample_npy_to_nii.py <dose.npy> <ref_image.nii> <output_dose.nii>")
        sys.exit(1)

    npy_path, ref_path, out_path = sys.argv[1:]
    resample_npy_to_nii(npy_path, ref_path, out_path)