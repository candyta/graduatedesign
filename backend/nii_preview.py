# nii_preview.py
# -*- coding: utf-8 -*-
import nibabel as nib
import matplotlib.pyplot as plt
import os
import sys
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
    # 轴位(Axial)沿Z轴切→shape[2], 冠状(Coronal)沿Y轴切→shape[1], 矢状(Sagittal)沿X轴切→shape[0]
    views = {
        'axial': data.shape[2],
        'coronal': data.shape[1],
        'sagittal': data.shape[0]
    }

    for view_name, max_slice in views.items():
        view_dir = os.path.join(output_dir, view_name)
        os.makedirs(view_dir, exist_ok=True)

        for i in range(max_slice):
            if view_name == 'axial':
                # XY平面: 列方向=X(sp_x), 行方向=Y(sp_y)
                slice_data = data[:, :, i].T    # shape: (Y, X)
                aspect = sp_y / sp_x
            elif view_name == 'coronal':
                # XZ平面: 列方向=X(sp_x), 行方向=Z(sp_z)
                slice_data = data[:, i, :].T    # shape: (Z, X)
                aspect = sp_z / sp_x
            else:
                # YZ平面: 列方向=Y(sp_y), 行方向=Z(sp_z)
                slice_data = data[i, :, :].T    # shape: (Z, Y)
                aspect = sp_z / sp_y

            # 根据物理尺寸设置图像大小，保持正确的宽高比
            rows, cols = slice_data.shape
            phys_w = cols   # 列数（相对单位）
            phys_h = rows * aspect   # 行数 × 行列间距比

            fig_w = 6.0
            fig_h = fig_w * phys_h / phys_w if phys_w > 0 else 6.0

            plt.figure(figsize=(fig_w, fig_h))
            plt.imshow(slice_data, cmap='gray', origin='lower', aspect=aspect)
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
