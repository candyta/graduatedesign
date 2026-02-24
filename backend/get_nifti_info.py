# get_nifti_info.py
import nibabel as nib
import sys
import json

def get_nifti_info(nii_path):
    img = nib.load(nii_path)
    affine = img.affine  # 方向矩阵
    spacing = img.header.get_zooms()  # 分辨率（spacing）
    origin = affine[:3, 3]  # 原点（origin）
    direction = affine[:3, :3]  # 方向矩阵（direction）
    
    return {
        'spacing': spacing,
        'origin': origin.tolist(),
        'direction': direction.tolist()
    }

if __name__ == '__main__':
    nii_path = sys.argv[1]  # 从命令行获取 NIfTI 文件路径
    nifti_info = get_nifti_info(nii_path)
    print(json.dumps(nifti_info))  # 返回空间信息为 JSON 格式
