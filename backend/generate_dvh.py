# generate_dvh.py
# -*- coding: utf-8 -*-
import os
import argparse
import numpy as np
import nibabel as nib
import matplotlib.pyplot as plt  # Import matplotlib for plotting
from scipy.ndimage import zoom
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

def _cumulative_dvh(dose_values, n_bins=200):
    """
    计算累积 DVH：对于每个剂量值 d，返回"至少接受 d 剂量的体积百分比"。
    返回 (bin_centers, volume_pct)，长度均为 n_bins。
    """
    if len(dose_values) == 0:
        return np.array([0.0, 0.0]), np.array([100.0, 0.0])
    max_dose = float(dose_values.max())
    if max_dose <= 0:
        return np.array([0.0, 0.0]), np.array([100.0, 0.0])
    bin_edges = np.linspace(0, max_dose * 1.05, n_bins + 1)
    counts, _ = np.histogram(dose_values, bins=bin_edges)
    # 累积：从高剂量到低剂量累加，再归一化为百分比
    cumulative = np.flip(np.cumsum(np.flip(counts)))
    volume_pct = cumulative / len(dose_values) * 100.0
    # 在 bin_centers 和 0 起点各加一个点，使曲线从 (0, 100%) 开始
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    dose_pts   = np.concatenate([[0.0], bin_centers])
    volume_pts = np.concatenate([[100.0], volume_pct])
    return dose_pts, volume_pts


def generate_dvh_image(dose, masks, spacing, out_path):
    """
    生成标准累积 DVH 图像。
    累积 DVH：X 轴 = 剂量 (Gy)，Y 轴 = 至少接受该剂量的体积百分比 (%)。
    """
    # 解决 matplotlib 中文字体问题
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False

    fig, ax = plt.subplots(figsize=(7, 5))

    # 收集所有结构的最大剂量，用于统一 X 轴
    all_max_dose = 0.0
    combined_mask = np.zeros_like(dose, dtype=bool)

    for structure_name, (mask, _) in masks.items():
        structure_mask = (mask > 0)
        structure_dose = dose[structure_mask]
        combined_mask = np.logical_or(combined_mask, structure_mask)
        if len(structure_dose) == 0:
            continue
        d, v = _cumulative_dvh(structure_dose)
        ax.plot(d, v, linewidth=1.5, label=structure_name)
        all_max_dose = max(all_max_dose, float(structure_dose.max()))

    # 绘制所有掩膜合并区域的总 DVH
    total_dose = dose[combined_mask]
    if len(total_dose) > 0:
        d, v = _cumulative_dvh(total_dose)
        ax.plot(d, v, linewidth=2.0, linestyle='--', color='black', label='Total (all structures)')
        all_max_dose = max(all_max_dose, float(total_dose.max()))

    ax.set_xlim(left=0, right=all_max_dose * 1.05 if all_max_dose > 0 else 10.0)
    ax.set_ylim(0, 105)
    ax.set_xlabel('Dose (Gy)')
    ax.set_ylabel('Volume (%)')
    ax.set_title('Cumulative DVH for Different Structures')
    ax.legend(loc='upper right', fontsize=8)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f'[INFO] Saved cumulative DVH plot: {out_path}')





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
