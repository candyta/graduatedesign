# -*- coding: utf-8 -*-
"""
contour_overlay.py
为每个CT切片（axial/coronal/sagittal）叠加器官轮廓，输出RGB PNG。

用法:
  python contour_overlay.py \
    --ct  <ct.nii> \
    --masks  <organ1.nii>,<organ2.nii> \
    --names  Brain,GTV \
    --outdir <output_dir>
"""
import sys, os, argparse, json
import numpy as np
import nibabel as nib
from scipy.ndimage import zoom as ndimage_zoom, binary_erosion
from PIL import Image

# 预定义轮廓颜色（RGB），与前端 CONTOUR_COLORS 顺序一致
COLORS = [
    (255,   0,   0),   # 红
    (  0, 255,   0),   # 绿
    (  0, 150, 255),   # 蓝
    (255, 255,   0),   # 黄
    (255,   0, 255),   # 品红
    (  0, 255, 255),   # 青
    (255, 128,   0),   # 橙
    (128,   0, 255),   # 紫
]

OUTPUT_SIZE = 512   # 短边最小输出像素


def get_contour(binary_slice):
    """二值切片 → 轮廓（边界像素）布尔数组。"""
    if not binary_slice.any():
        return np.zeros_like(binary_slice, dtype=bool)
    return binary_slice & ~binary_erosion(binary_slice)


def smart_zoom(arr, zoom_factors, order=1):
    if any(abs(z - 1.0) > 0.01 for z in zoom_factors):
        arr = ndimage_zoom(arr.astype(float), zoom_factors, order=order)
    return arr


def upscale_to_min(arr, order=1):
    h, w = arr.shape
    if max(h, w) < OUTPUT_SIZE:
        scale = OUTPUT_SIZE / max(h, w)
        arr = ndimage_zoom(arr.astype(float), (scale, scale), order=order)
    return arr


def to_uint8(slice_2d, gmin, gmax):
    clipped = np.clip(slice_2d, gmin, gmax)
    return ((clipped - gmin) / (gmax - gmin) * 255).astype(np.uint8)


def generate_overlays(ct_nii_path, mask_paths, mask_names, output_dir):
    print(f"[INFO] CT: {ct_nii_path}")
    print(f"[INFO] Masks ({len(mask_paths)}): {mask_paths}")

    ct_img = nib.load(ct_nii_path)
    ct_data = ct_img.get_fdata()
    zooms = ct_img.header.get_zooms()
    sp = [float(z) if z > 0 else 1.0 for z in zooms[:3]]   # sp_x, sp_y, sp_z

    masks_data = []
    for mp in mask_paths:
        m = nib.load(mp).get_fdata()
        masks_data.append((m > 0.5).astype(np.uint8))

    # 全局归一化
    flat = ct_data.ravel()
    gmin = float(np.percentile(flat, 1))
    gmax = float(np.percentile(flat, 99))
    if gmax <= gmin:
        gmax = gmin + 1.0

    VIEW_CONFIG = {
        'axial':    {'n': ct_data.shape[2], 'zoom': (sp[1] / sp[0], 1.0)},
        'coronal':  {'n': ct_data.shape[1], 'zoom': (sp[2] / sp[0], 1.0)},
        'sagittal': {'n': ct_data.shape[0], 'zoom': (sp[2] / sp[1], 1.0)},
    }

    for view_name, cfg in VIEW_CONFIG.items():
        view_dir = os.path.join(output_dir, view_name)
        os.makedirs(view_dir, exist_ok=True)
        n = cfg['n']
        zf = cfg['zoom']

        for i in range(n):
            # --- 取CT切片 ---
            if view_name == 'axial':
                ct_sl = ct_data[:, :, i].T
            elif view_name == 'coronal':
                ct_sl = ct_data[:, i, :].T
            else:
                ct_sl = ct_data[i, :, :].T

            ct_sl = smart_zoom(ct_sl, zf, order=3)
            ct_sl = upscale_to_min(ct_sl, order=3)
            ct_gray = to_uint8(ct_sl, gmin, gmax)[::-1]   # 翻转
            H, W = ct_gray.shape
            rgb = np.stack([ct_gray, ct_gray, ct_gray], axis=-1)

            # --- 叠加轮廓 ---
            for mi, mask_data in enumerate(masks_data):
                color = COLORS[mi % len(COLORS)]
                max_idx = {
                    'axial':    mask_data.shape[2] - 1,
                    'coronal':  mask_data.shape[1] - 1,
                    'sagittal': mask_data.shape[0] - 1,
                }
                if i > max_idx[view_name]:
                    continue

                if view_name == 'axial':
                    m_sl = mask_data[:, :, i].T
                elif view_name == 'coronal':
                    m_sl = mask_data[:, i, :].T
                else:
                    m_sl = mask_data[i, :, :].T

                m_sl = smart_zoom(m_sl.astype(float), zf, order=0)
                m_sl = upscale_to_min(m_sl, order=0)
                m_bin = (m_sl > 0.5)[::-1]   # 翻转
                contour = get_contour(m_bin)
                if not contour.any():
                    continue

                ys, xs = np.where(contour)
                # 限制坐标在图像范围内
                mask_y = (ys < H)
                mask_x = (xs < W)
                valid = mask_y & mask_x
                rgb[ys[valid], xs[valid]] = color

            out_path = os.path.join(view_dir, f'overlay_{i:03d}.png')
            Image.fromarray(rgb.astype(np.uint8), mode='RGB').save(out_path)

    result = {
        'success': True,
        'outdir': output_dir,
        'views': {v: cfg['n'] for v, cfg in VIEW_CONFIG.items()}
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ct',         required=True)
    parser.add_argument('--masks',      default='',  help='逗号分隔的mask NIfTI路径（少量mask时使用）')
    parser.add_argument('--masks-file', default='',  help='每行一条mask路径的文本文件（避免命令行过长）')
    parser.add_argument('--names',      default='',  help='逗号分隔的器官名称（与masks顺序对应）')
    parser.add_argument('--names-file', default='',  help='每行一个器官名称的文本文件')
    parser.add_argument('--outdir',     required=True)
    args = parser.parse_args()

    # 支持文件方式传入（避免Windows命令行8191字符限制）
    if args.masks_file:
        with open(args.masks_file, 'r', encoding='utf-8') as f:
            mask_paths = [l.strip() for l in f if l.strip()]
    else:
        mask_paths = [p.strip() for p in args.masks.split(',') if p.strip()]

    if args.names_file:
        with open(args.names_file, 'r', encoding='utf-8') as f:
            mask_names = [l.strip() for l in f if l.strip()]
    elif args.names:
        mask_names = [n.strip() for n in args.names.split(',') if n.strip()]
    else:
        mask_names = [f'Organ{i+1}' for i in range(len(mask_paths))]

    generate_overlays(args.ct, mask_paths, mask_names, args.outdir)

