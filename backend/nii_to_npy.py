# nii_to_npy.py
import nibabel as nib
import numpy as np
import sys
import os

def main(nii_path, output_path=None):
    img = nib.load(nii_path)
    data = img.get_fdata(dtype=np.float32)

    if output_path is None:
        output_path = nii_path.replace('.nii.gz', '.npy')

    np.save(output_path, data)
    print(f"[INFO] 已保存为: {output_path}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python nii_to_npy.py 输入.nii.gz [输出.npy]")
        sys.exit(1)

    nii_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    main(nii_path, output_path)
