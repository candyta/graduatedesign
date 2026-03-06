# nii_preview.py
# -*- coding: utf-8 -*-
import nibabel as nib
import matplotlib.pyplot as plt
import numpy as np
import os
import sys
from scipy.ndimage import zoom as ndimage_zoom

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

    for view_name, max_slice in views.items():
        view_dir = os.path.join(output_dir, view_name)
        os.makedirs(view_dir, exist_ok=True)

        for i in range(max_slice):
            if view_name == 'axial':
                slice_data = data[:, :, i].T    # (Y, X)
                # XY平面通常各向同性，若不同则重采样
                zoom_factors = (sp_y / sp_x, 1.0) if abs(sp_y - sp_x) > 0.01 else None
            elif view_name == 'coronal':
                slice_data = data[:, i, :].T    # (Z, X)
                # Z方向需按 sp_z/sp_x 倍插值，使每个输出像素对应相同物理尺寸
                zoom_factors = (sp_z / sp_x, 1.0) if abs(sp_z - sp_x) > 0.01 else None
            else:  # sagittal
                slice_data = data[i, :, :].T    # (Z, Y)
                zoom_factors = (sp_z / sp_y, 1.0) if abs(sp_z - sp_y) > 0.01 else None

            # 用双线性插值重采样到物理等比尺寸，消除像素块感
            if zoom_factors is not None:
                slice_data = ndimage_zoom(slice_data, zoom_factors, order=1)

            rows, cols = slice_data.shape
            fig_w = 6.0
            fig_h = fig_w * rows / cols if cols > 0 else 6.0

            plt.figure(figsize=(fig_w, fig_h))
            plt.imshow(slice_data, cmap='gray', origin='lower', aspect='equal')
            plt.axis('off')
            output_path = os.path.join(view_dir, f'{view_name}_{i:03d}.png')
            plt.savefig(output_path, bbox_inches='tight', pad_inches=0)
            plt.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python nii_preview.py <nii_path> <output_dir>")
        sys.exit(1)

    nii_path, output_dir = sys.argv[1:]
    generate_slices(nii_path, output_dir)
