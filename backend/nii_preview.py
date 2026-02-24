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
            plt.figure(figsize=(6, 6))
            if view_name == 'axial':
                slice_data = data[:, :, i].T    # 沿Z轴，显示XY平面
            elif view_name == 'coronal':
                slice_data = data[:, i, :].T    # 沿Y轴，显示XZ平面
            else:
                slice_data = data[i, :, :].T    # 沿X轴，显示YZ平面

            plt.imshow(slice_data, cmap='gray', origin='lower')
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