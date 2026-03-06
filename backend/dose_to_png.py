"""
dose_to_png.py  —  全身剂量分布 3D 可视化
======================================================
用法:
    python dose_to_png.py <dose.npy> <output_dir> [reference.nii.gz]
                          [--interval N]

修复说明 (v2):
  * 全身体模模式下，背景使用器官ID→近似HU值映射，正确显示
    肺、骨骼、软组织等解剖结构，而非单一体内mask。
  * 剂量热图以透明度叠加在解剖背景上，方形空白区域消失。
"""

import sys
import os
import argparse
import numpy as np
import nibabel as nib
from scipy.ndimage import zoom, gaussian_filter
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

# ============================================================
# ICRP-110 器官 ID → 组织密度 (g/cm³)
# 来源: AM_organs.dat  (organID, density)
# ============================================================
ORGAN_DENSITY = {
    0:   0.001,  # 体外/空气
    1:   1.030,  2:   1.030,  3:   1.030,  4:   1.030,
    5:   1.050,  6:   1.050,  7:   1.030,  8:   1.030,
    9:   1.060, 10:   1.060, 11:   1.060, 12:   1.060,
    13:  1.920, 14:  1.205, 15:   0.980,  # Humeri upper: cortical/spongiosa/medullary
    16:  1.920, 17:  1.108, 18:   0.980,  # Humeri lower
    19:  1.920, 20:  1.108, 21:   0.980,  # Ulnae/radii
    22:  1.920, 23:  1.108,              # Wrist/hand
    24:  1.920, 25:  1.151,              # Clavicles
    26:  1.920, 27:  1.157,              # Cranium
    28:  1.920, 29:  1.124, 30:   0.980, # Femora upper
    31:  1.920, 32:  1.108, 33:   0.980, # Femora lower
    34:  1.920, 35:  1.108, 36:   0.980, # Tibiae
    37:  1.920, 38:  1.108,              # Foot bones
    39:  1.920, 40:  1.228,              # Mandible
    41:  1.920, 42:  1.123,              # Pelvis
    43:  1.920, 44:  1.165,              # Ribs
    45:  1.920, 46:  1.183,              # Scapulae
    47:  1.920, 48:  1.050,              # Cervical spine
    49:  1.920, 50:  1.074,              # Thoracic spine
    51:  1.920, 52:  1.112,              # Lumbar spine
    53:  1.920, 54:  1.031,              # Sacrum
    55:  1.920, 56:  1.041,              # Sternum
    57:  1.100, 58:  1.100, 59:  1.100, 60:  1.100,  # Cartilage
    61:  1.050,                          # Brain
    62:  0.950, 63:  1.020, 64:  0.950, 65:  1.020,  # Breast
    66:  1.050, 67:  1.050, 68:  1.050, 69:  1.050,  # Eyes
    70:  1.030, 71:  1.030,              # Gall bladder
    72:  1.040, 73:  1.040,              # Stomach
    74:  1.040, 75:  1.040,              # Small intestine
    76:  1.040, 77:  1.040,              # Ascending colon
    78:  1.040, 79:  1.040,              # Transverse colon right
    80:  1.040, 81:  1.040,              # Transverse colon left
    82:  1.040, 83:  1.040,              # Descending colon
    84:  1.040, 85:  1.040,              # Sigmoid colon
    86:  1.040,                          # Rectum
    87:  1.050, 88:  1.060,              # Heart wall / blood
    89:  1.050, 90:  1.050, 91:  1.050, # Kidney left
    92:  1.050, 93:  1.050, 94:  1.050, # Kidney right
    95:  1.050,                          # Liver
    96:  1.060, 97:  0.382,              # Lung left (blood / tissue)
    98:  1.060, 99:  0.382,              # Lung right (blood / tissue)
    100: 1.030, 101: 1.030,             # Lymph nodes extrathoracic/thoracic
    102: 1.030, 103: 1.030, 104: 1.030, 105: 1.030,  # Lymph nodes
    106: 1.050, 107: 1.050, 108: 1.050, 109: 1.050,  # Muscle
    110: 1.030,                          # Oesophagus
    111: 1.040, 112: 1.040,              # Ovary
    113: 1.050,                          # Pancreas
    114: 1.030,                          # Pituitary
    115: 1.030,                          # Prostate
    116: 0.950, 117: 0.950, 118: 0.950, 119: 0.950,  # Residual tissue (adipose)
    120: 1.030, 121: 1.030,              # Salivary glands
    122: 1.090, 123: 1.090, 124: 1.090, 125: 1.090,  # Skin
    126: 1.030,                          # Spinal cord
    127: 1.040,                          # Spleen
    128: 2.750,                          # Teeth
    129: 1.040, 130: 1.040,              # Testes
    131: 1.030,                          # Thymus
    132: 1.040,                          # Thyroid
    133: 1.050,                          # Tongue
    134: 1.030,                          # Tonsils
    135: 1.030, 136: 1.030,              # Ureters
    137: 1.040,                          # Urinary bladder wall
    138: 1.040,                          # Urinary bladder contents
    139: 1.030, 140: 1.030,              # Miscellaneous
}


def density_to_grayscale(density_vol):
    """
    将密度体积 (g/cm³) 转换为 8-bit 灰度图，
    模拟 CT 窗宽/窗位 (WC=300 HU, WW=3000 HU).
    HU ≈ (density - 1.0) × 1000
    window: [-1000, 2000] → [0, 255]
    """
    hu = (density_vol - 1.0) * 1000.0
    # 使用 [-1000, 2000] 窗口, 3000 HU 范围
    gray = np.clip((hu + 1000.0) / 3000.0, 0.0, 1.0)
    return gray  # float [0,1]


def organ_id_to_density(phantom_vol):
    """将器官ID体积映射为密度体积。"""
    density = np.zeros_like(phantom_vol, dtype=np.float32)
    for organ_id, dens in ORGAN_DENSITY.items():
        density[phantom_vol == organ_id] = dens
    # 处理未知ID：使用软组织默认值
    unknown_mask = (phantom_vol > 0) & (density == 0)
    if unknown_mask.any():
        density[unknown_mask] = 1.04
    return density


def safe_sigmoid(x):
    """数值稳定的 sigmoid。"""
    return np.where(x >= 0,
                    1.0 / (1.0 + np.exp(-x)),
                    np.exp(x) / (1.0 + np.exp(x)))


def main():
    parser = argparse.ArgumentParser(description='生成全身剂量分布 PNG 切片')
    parser.add_argument('dose_file', help='剂量 NPY 文件路径')
    parser.add_argument('output_dir', help='输出目录')
    parser.add_argument('reference_nii', nargs='?', default=None,
                        help='参考 NIfTI 文件 (fused_phantom.nii.gz)')
    parser.add_argument('--interval', type=int, default=1,
                        help='切片采样间隔 (默认=1, 每张都保存)')
    args = parser.parse_args()

    print('=' * 60)
    print('全身剂量分布3D可视化')
    print(f'剂量文件: {args.dose_file}')
    print(f'参考CT: {args.reference_nii}')
    print(f'输出目录: {args.output_dir}')
    print(f'切片间隔: {args.interval}')

    # ----------------------------------------------------------
    # 步骤1: 读取参考NIfTI（融合体模，含器官ID）
    # ----------------------------------------------------------
    print('[步骤1] 读取参考CT图像')
    ref_nii = nib.load(args.reference_nii)
    ref_data = ref_nii.get_fdata().astype(np.float32)
    ref_spacing = ref_nii.header.get_zooms()
    # ref_data shape: (X, Y, Z)  →  转为 (Z, Y, X) 以便切片
    # nibabel 默认读取顺序为 (i, j, k)=(x, y, z)
    ref_data = ref_data  # 保持原始顺序
    nz, ny, nx = ref_data.shape[2], ref_data.shape[1], ref_data.shape[0]
    print(f'CT shape: ({ref_data.shape[0]}, {ref_data.shape[1]}, {ref_data.shape[2]})')
    print(f'CT spacing: {ref_spacing}')
    print(f'CT origin: {ref_nii.header.get_sform()[:3, 3].tolist()}')
    ct_min, ct_max = ref_data.min(), ref_data.max()
    print(f'CT 数值范围: {ct_min:.1f} ~ {ct_max:.1f}')

    # 判断是否为全身体模（器官ID模式: 整数, 0~141）
    is_wholebody = (ct_max <= 200) and (ct_min >= 0) and \
                   np.all(ref_data == ref_data.astype(np.int16))
    if is_wholebody:
        print('[全身体模模式] 使用器官ID→密度→HU映射，显示解剖结构')
        density_vol = organ_id_to_density(ref_data.astype(np.int16))
        bg_gray = density_to_grayscale(density_vol)  # float [0,1], shape (X,Y,Z)
    else:
        print('[CT模式] 使用HU灰度作为背景')
        bg_gray = np.clip((ref_data + 1000.0) / 3000.0, 0.0, 1.0)

    # 体内 mask (所有非零体素)
    body_mask = (ref_data > 0)

    # ----------------------------------------------------------
    # 步骤2: 读取剂量数据
    # ----------------------------------------------------------
    print('[步骤2] 读取剂量数据')
    dose_raw = np.load(args.dose_file).astype(np.float64)
    print(f'原始剂量 shape: {dose_raw.shape}')
    print(f'原始剂量范围: {dose_raw.min():.2e} ~ {dose_raw.max():.2e}')
    nz_dose = np.count_nonzero(dose_raw)
    print(f'非零值: {nz_dose} ({100.0*nz_dose/dose_raw.size:.1f}%)')
    print(f'有效剂量值: {nz_dose} ({100.0*nz_dose/dose_raw.size:.1f}%)')

    # ----------------------------------------------------------
    # 步骤3: 空间配准和重采样
    # ----------------------------------------------------------
    print('[步骤3] 空间配准和重采样')
    # 参考图 shape (X, Y, Z), 剂量 shape (nz_d, ny_d, nx_d) → 需对齐
    # 约定: 剂量网格为 (nz, ny, nx), 与参考图的 (X, Y, Z) 对应关系:
    #   dose axis 0 (nz_d) ↔ ref axis 2 (Z)
    #   dose axis 1 (ny_d) ↔ ref axis 1 (Y)
    #   dose axis 2 (nx_d) ↔ ref axis 0 (X)
    if is_wholebody:
        print('[全身体模模式] 使用ICRP-110体模体素尺寸')
        rx, ry, rz = ref_data.shape  # X, Y, Z
        dz, dy, dx = dose_raw.shape
        print(f'体模尺寸(Z,Y,X): ({rz}, {ry}, {rx})')
        print(f'剂量网格(Z,Y,X): ({dz}, {dy}, {dx})')
        sp_x = ref_spacing[0]
        sp_y = ref_spacing[1]
        sp_z = ref_spacing[2]
        dose_sp_z = rz * sp_z / dz
        dose_sp_y = ry * sp_y / dy
        dose_sp_x = rx * sp_x / dx
        print(f'剂量体素间距(mm): ({dose_sp_z:.3f}, {dose_sp_y:.3f}, {dose_sp_x:.3f})')
        print('执行重采样，对齐到参考图空间...')
        zoom_z = rz / dz
        zoom_y = ry / dy
        zoom_x = rx / dx
        # 剂量 (nz_d, ny_d, nx_d) → 对应 ref (Z, Y, X)
        dose_resampled_zyx = zoom(dose_raw, (zoom_z, zoom_y, zoom_x), order=1)
        # 将 (Z,Y,X) 顺序的剂量转为 (X,Y,Z) 与 ref 对齐
        dose_vol = np.transpose(dose_resampled_zyx, (2, 1, 0))
        print(f'重采样后 shape: {dose_vol.shape}')
    else:
        print('[CT模式] 直接重采样到参考空间')
        rx, ry, rz = ref_data.shape
        dz, dy, dx = dose_raw.shape
        zoom_x = rx / dx
        zoom_y = ry / dy
        zoom_z = rz / dz
        dose_resampled_zyx = zoom(dose_raw, (zoom_z, zoom_y, zoom_x), order=1)
        dose_vol = np.transpose(dose_resampled_zyx, (2, 1, 0))
        print(f'重采样后 shape: {dose_vol.shape}')

    # ----------------------------------------------------------
    # 步骤4: 构建体内mask
    # ----------------------------------------------------------
    print('[步骤4] 构建体内mask')
    body_total = body_mask.sum()
    total = body_mask.size
    print(f'体内体素: {body_total} / {total} ({100.0*body_total/total:.1f}%)')

    # ----------------------------------------------------------
    # 步骤5: 体内零剂量填充（迭代扩散）
    # ----------------------------------------------------------
    print('[步骤5] 全身剂量填充（距离衰减）')
    dose_in_body = np.where(body_mask, dose_vol, 0.0)
    has_dose_mask = (dose_in_body > 0) & body_mask
    n_has = has_dose_mask.sum()
    n_body = body_mask.sum()
    n_zero = n_body - n_has
    print(f'体内有剂量: {n_has} / {n_body} ({100.0*n_has/n_body:.1f}%)')
    print(f'体内零值（需填充）: {n_zero} ({100.0*n_zero/n_body:.1f}%)')

    dose_filled = dose_in_body.copy()
    if n_zero > 0:
        print('[迭代扩散] 参数: 15次迭代, sigma=6.0')
        print(f'[迭代扩散] 体内有剂量: {n_has}/{n_body} ({100.0*n_has/n_body:.1f}%)')
        new_filled = 0
        for _ in range(15):
            smoothed = gaussian_filter(dose_filled.astype(np.float32), sigma=6.0)
            fill_mask = body_mask & (dose_filled == 0)
            dose_filled[fill_mask] = smoothed[fill_mask]
            new_filled = (dose_filled > 0).sum() - n_has
        print(f'[迭代扩散] 新填充体素: {new_filled:,}')
        remaining_zero = (body_mask & (dose_filled == 0)).sum()
        print(f'填充后体内零值: {remaining_zero}')
    print(f'填充后范围: {dose_filled[body_mask].min():.2e} ~ {dose_filled[body_mask].max():.2e}')

    # ----------------------------------------------------------
    # 步骤6: 对数归一化
    # ----------------------------------------------------------
    print('[步骤6] 对数归一化（参考文献色标: 跨7个数量级）')
    dose_norm = np.zeros_like(dose_filled)
    if body_mask.any() and dose_filled[body_mask].max() > 0:
        d_max = dose_filled[body_mask].max()
        d_min_nonzero = dose_filled[dose_filled > 0].min() if (dose_filled > 0).any() else 1e-20
        log_max = np.log10(d_max + 1e-20)
        log_min = log_max - 7  # 7个数量级
        log_vals = np.log10(dose_filled + 1e-20)
        dose_norm = np.clip((log_vals - log_min) / (log_max - log_min), 0.0, 1.0)
        dose_norm[~body_mask] = 0.0
    print(f'体内归一化值范围: {dose_norm[body_mask].min():.4f} ~ {dose_norm[body_mask].max():.4f}')
    print(f'体内均值: {dose_norm[body_mask].mean():.4f}')

    # ----------------------------------------------------------
    # 步骤7: 生成三视图切片
    # ----------------------------------------------------------
    print('[步骤7] 生成三视图切片')
    sp_x, sp_y, sp_z = ref_spacing[0], ref_spacing[1], ref_spacing[2]
    print(f'参考图体素间距: X={sp_x:.3f}mm, Y={sp_y:.3f}mm, Z={sp_z:.3f}mm')

    os.makedirs(args.output_dir, exist_ok=True)
    cmap_dose = plt.get_cmap('jet')

    # 加载解剖密度映射标志
    if is_wholebody:
        print('[anatomy] 已加载 ICRP-110 AM 材质密度映射 (140 种器官)')

    dose_alpha = 0.85
    bg_alpha = 1.0

    def save_slices(axis, view_name, slice_dir):
        """
        沿给定轴生成PNG切片。
        axis: 0=X (sagittal), 1=Y (coronal), 2=Z (axial) in (X,Y,Z) volume
        """
        os.makedirs(slice_dir, exist_ok=True)
        n_slices = ref_data.shape[axis]
        print(f'[保存 {view_name} 切片] — 全身彩色剂量热力图')
        print(f'总切片数: {n_slices}, 切片尺寸: ', end='')

        saved = 0
        for i in range(n_slices):
            if i % args.interval != 0:
                continue

            # 取切片 (结果形状依赖于axis)
            if axis == 2:   # axial: cut along Z, slice is (X, Y)
                bg_sl = bg_gray[:, :, i]      # (X, Y)
                dose_sl = dose_norm[:, :, i]  # (X, Y)
                mask_sl = body_mask[:, :, i]
                # 显示为 (Y, X) → transpose
                bg_sl = bg_sl.T
                dose_sl = dose_sl.T
                mask_sl = mask_sl.T
            elif axis == 1:  # coronal: cut along Y, slice is (X, Z)
                bg_sl = bg_gray[:, i, :]      # (X, Z)
                dose_sl = dose_norm[:, i, :]
                mask_sl = body_mask[:, i, :]
                # 显示为 (Z, X), 上下翻转使头朝上
                bg_sl = np.flipud(bg_sl.T)
                dose_sl = np.flipud(dose_sl.T)
                mask_sl = np.flipud(mask_sl.T)
            else:            # sagittal: cut along X, slice is (Y, Z)
                bg_sl = bg_gray[i, :, :]      # (Y, Z)
                dose_sl = dose_norm[i, :, :]
                mask_sl = body_mask[i, :, :]
                bg_sl = np.flipud(bg_sl.T)
                dose_sl = np.flipud(dose_sl.T)
                mask_sl = np.flipud(mask_sl.T)

            if saved == 0:
                print(f'{bg_sl.shape[1]}×{bg_sl.shape[0]}')
                print(f'色图: jet, 剂量alpha: {dose_alpha}')

            h, w = bg_sl.shape

            # 背景: 解剖灰度 → RGB
            bg_rgb = np.stack([bg_sl, bg_sl, bg_sl], axis=-1)  # (H, W, 3) float

            # 体外区域设为黑色背景
            outside = ~mask_sl
            bg_rgb[outside] = 0.0

            # 剂量热图颜色
            dose_rgba = cmap_dose(dose_sl)  # (H, W, 4)

            # 合成: 只在体内叠加剂量
            # alpha_blend: out = dose_rgba * alpha + bg_rgb * (1-alpha) where dose>0
            has_dose = (dose_sl > 1e-6) & mask_sl
            out_rgb = bg_rgb.copy()
            if has_dose.any():
                alpha = dose_alpha
                out_rgb[has_dose] = (
                    dose_rgba[has_dose, :3] * alpha +
                    bg_rgb[has_dose] * (1.0 - alpha)
                )

            # 体内无剂量区域: 只显示解剖背景（略微变暗以区分）
            body_no_dose = mask_sl & ~has_dose
            if body_no_dose.any():
                out_rgb[body_no_dose] = bg_rgb[body_no_dose] * 0.7

            # 转换为 uint8
            out_uint8 = (np.clip(out_rgb, 0.0, 1.0) * 255).astype(np.uint8)
            img = Image.fromarray(out_uint8, mode='RGB')
            fname = os.path.join(slice_dir, f'{view_name}_{i:04d}.png')
            img.save(fname)
            saved += 1

        print(f'✓ 已保存 {saved} 张切片到: {slice_dir}')
        return saved

    axial_dir = os.path.join(args.output_dir, 'axial')
    coronal_dir = os.path.join(args.output_dir, 'coronal')
    sagittal_dir = os.path.join(args.output_dir, 'sagittal')

    print('生成轴位面 (Axial)...')
    n_axial = save_slices(2, 'axial', axial_dir)

    print('生成冠状面 (Coronal)...')
    n_coronal = save_slices(1, 'coronal', coronal_dir)

    print('生成矢状面 (Sagittal)...')
    n_sagittal = save_slices(0, 'sagittal', sagittal_dir)

    total_saved = n_axial + n_coronal + n_sagittal
    print()
    print('✓ 全身剂量分布可视化完成！')
    print(f'输出目录: {args.output_dir}')
    print(f'* 轴位面: {n_axial} 张切片')
    print(f'* 冠状面: {n_coronal} 张切片')
    print(f'* 矢状面: {n_sagittal} 张切片')
    print(f'总计: {total_saved} 张图像')

    # 输出文件统计 (供调用者解析)
    import glob
    axial_files = glob.glob(os.path.join(axial_dir, '*.png'))
    coronal_files = glob.glob(os.path.join(coronal_dir, '*.png'))
    sagittal_files = glob.glob(os.path.join(sagittal_dir, '*.png'))
    print(f'文件已生成: axial: {len(axial_files)} 个文件')
    print(f'文件已生成: coronal: {len(coronal_files)} 个文件')
    print(f'文件已生成: sagittal: {len(sagittal_files)} 个文件')
    print(f'✓ axial视图: {len(axial_files)}张切片')
    print(f'✓ coronal视图: {len(coronal_files)}张切片')
    print(f'✓ sagittal视图: {len(sagittal_files)}张切片')
    print('✓ 全身剂量分布图生成成功，共{}张切片'.format(total_saved))


if __name__ == '__main__':
    main()
