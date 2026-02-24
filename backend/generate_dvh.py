# generate_dvh.py
# -*- coding: utf-8 -*-
import os
import argparse
import numpy as np
import nibabel as nib
import matplotlib.pyplot as plt  # Import matplotlib for plotting
from scipy.ndimage import zoom
from scipy.stats import gaussian_kde
def load_npy_dose(npy_path):
    """加载剂量数据 (.npy 文件)"""
    dose = np.load(npy_path)
    print(f'[INFO] Loaded dose with shape: {dose.shape}')  # 打印剂量数据的尺寸
    return dose

def load_nii_mask(nii_path, dose_shape=None):
    """加载 NIfTI 掩膜数据 (.nii 或 .nii.gz 文件)，并根据剂量数据的形状调整掩膜"""
    nii = nib.load(nii_path)
    mask_data = nii.get_fdata()
    spacing = nii.header.get_zooms()  # 获取体素间距
    print(f'[INFO] Loaded mask {nii_path} with shape: {mask_data.shape} and spacing: {spacing}')  # 打印掩膜数据的尺寸和体素间距
    
    if dose_shape is not None:
        mask_data = resize_mask_to_dose(mask_data, dose_shape)  # 根据剂量数据的形状调整掩膜的尺寸
    
    return mask_data, spacing

def resize_mask_to_dose(mask, dose_shape):
    """根据剂量数据的形状调整掩膜数据的尺寸"""
    mask_resized = zoom(mask, (dose_shape[0] / mask.shape[0], 
                               dose_shape[1] / mask.shape[1], 
                               dose_shape[2] / mask.shape[2]), order=1)
    print(f'[INFO] Resized mask to shape: {mask_resized.shape}')  # 打印调整后的掩膜数据尺寸
    return mask_resized

def generate_dvh_image(dose, masks, spacing, out_path):
    """生成DVH图像，并为每个结构绘制单独的DVH"""
    # 设置绘图
    fig, ax = plt.subplots(figsize=(6, 4))

    # 为每个掩膜文件生成对应结构的DVH
    for structure_name, (mask, _) in masks.items():
        structure_mask = (mask > 0)  # 提取该结构的掩膜
        structure_dose = dose[structure_mask]  # 获取该结构的剂量
        ax.hist(structure_dose, bins=200, histtype='step', label=structure_name)  # 增加 bins 数量

    # 绘制总的DVH： 这里只需要将所有结构掩膜合并
    combined_mask = np.zeros_like(dose, dtype=bool)
    for mask, _ in masks.values():
        combined_mask = np.logical_or(combined_mask, mask > 0)

    total_dose = dose[combined_mask]  # 获取所有掩膜区域的剂量
    ax.hist(total_dose, bins=200, color='C0', histtype='step', label='Total Dose')  # 增加 bins 数量

    # 设置x轴范围为 0-10 Gy（放大显示剂量集中区）
    ax.set_xlim(0, 10)  # 调整 x 轴范围为 0 到 10 Gy

    ax.set_xlabel('剂量 (Gy)')
    ax.set_ylabel('频率')
    ax.set_title('DVH for Different Structures')

    ax.legend()  # 显示图例

    # 保存DVH图像
    plt.savefig(out_path)
    plt.close(fig)
    print(f'[INFO] Saved DVH plot: {out_path}')





def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dose', required=True, help='Path to .npy dose file')
    parser.add_argument('--masks', required=True, help='Comma-separated list of mask files (e.g., Esophagus.nii.gz,GTV.nii.gz,...)')
    parser.add_argument('--outdir', required=True, help='Directory to save DVH plots')
    args = parser.parse_args()

    dose = load_npy_dose(args.dose)  # 加载剂量数据
    os.makedirs(args.outdir, exist_ok=True)  # 创建输出目录

    # 解析掩膜文件路径
    mask_files = args.masks.split(',')
    masks = {}

    # 加载掩膜并为每个结构命名
    for mask_file in mask_files:
        mask, spacing = load_nii_mask(mask_file, dose.shape)  # 加载每个掩膜文件并调整大小
        structure_name = os.path.basename(mask_file).split('.')[0]  # 从文件名提取结构名称
        masks[structure_name] = (mask, structure_name)

    # 生成DVH图像并保存
    dvh_out_path = os.path.join(args.outdir, 'dvh.png')
    generate_dvh_image(dose, masks, spacing, dvh_out_path)
    print(f'[INFO] DVH图像已保存：{dvh_out_path}')

if __name__ == '__main__':
    main()
