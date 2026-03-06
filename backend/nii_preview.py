# nii_preview.py
# -*- coding: utf-8 -*-
import nibabel as nib
import numpy as np
import os
import sys
from scipy.ndimage import zoom as ndimage_zoom
from PIL import Image

print("[PYTHON] nii_preview.py 启动")
print("[PYTHON] 参数：", sys.argv)

def generate_slices(nii_path, output_dir):
    img = nib.load(nii_path)
    data = img.get_fdata()
    os.makedirs(output_dir, exist_ok=True)

    # 从NIfTI头获取体素间距(sp_x, sp_y, sp_z)，单位mm
    zooms = img.header.get_zooms()
    sp_x = float(zooms[0]) if zooms[0] > 0 else 1.0
    sp_y = float(zooms[1]) if zooms[1] > 0 else 1.0
    sp_z = float(zooms[2]) if zooms[2] > 0 else 1.0
    print(f"[PYTHON] 体素间距: sp_x={sp_x:.3f}mm, sp_y={sp_y:.3f}mm, sp_z={sp_z:.3f}mm")

    # nibabel读取NIfTI后数组形状为(X, Y, Z)
    views = {
        'axial':    data.shape[2],
        'coronal':  data.shape[1],
        'sagittal': data.shape[0]
    }

    # 全局归一化：基于整个数据集的1~99百分位，保证各切片亮度一致
    flat = data.ravel()
    global_min = float(np.percentile(flat, 1))
    global_max = float(np.percentile(flat, 99))
    if global_max <= global_min:
        global_max = global_min + 1.0

    def to_uint8(arr):
        """将浮点切片归一化到0-255 uint8。"""
        clipped = np.clip(arr, global_min, global_max)
        normed = (clipped - global_min) / (global_max - global_min) * 255.0
        return normed.astype(np.uint8)

    for view_name, max_slice in views.items():
        view_dir = os.path.join(output_dir, view_name)
        os.makedirs(view_dir, exist_ok=True)

        for i in range(max_slice):
            if view_name == 'axial':
                # XY平面 → shape (Y, X)，行方向=Y(sp_y)，列方向=X(sp_x)
                slice_data = data[:, :, i].T
                zoom_factors = (sp_y / sp_x, 1.0)
            elif view_name == 'coronal':
                # XZ平面 → shape (Z, X)，行方向=Z(sp_z)，列方向=X(sp_x)
                slice_data = data[:, i, :].T
                zoom_factors = (sp_z / sp_x, 1.0)
            else:  # sagittal
                # YZ平面 → shape (Z, Y)，行方向=Z(sp_z)，列方向=Y(sp_y)
                slice_data = data[i, :, :].T
                zoom_factors = (sp_z / sp_y, 1.0)

            # 双线性插值重采样到物理等比尺寸（仅在两方向间距差异 >1% 时插值）
            needs_zoom = any(abs(z - 1.0) > 0.01 for z in zoom_factors)
            if needs_zoom:
                slice_data = ndimage_zoom(slice_data, zoom_factors, order=1)

            # 归一化输出尺寸：确保最长边 >= OUTPUT_SIZE，防止浏览器粗糙放大导致像素块
            OUTPUT_SIZE = 512
            h, w = slice_data.shape
            max_dim = max(h, w)
            if max_dim < OUTPUT_SIZE:
                scale = OUTPUT_SIZE / max_dim
                new_h = max(1, round(h * scale))
                new_w = max(1, round(w * scale))
                slice_data = ndimage_zoom(slice_data, (new_h / h, new_w / w), order=1)

            # 转为uint8，垂直翻转（origin='lower'），用PIL直接保存原生分辨率
            pixel_array = to_uint8(slice_data)[::-1]   # 上下翻转
            pil_img = Image.fromarray(pixel_array, mode='L')

            output_path = os.path.join(view_dir, f'{view_name}_{i:03d}.png')
            pil_img.save(output_path)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python nii_preview.py <nii_path> <output_dir>")
        sys.exit(1)

    nii_path, output_dir = sys.argv[1:]
    generate_slices(nii_path, output_dir)
