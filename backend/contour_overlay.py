# -*- coding: utf-8 -*-
"""
contour_overlay.py
为每个CT切片（axial/coronal/sagittal）叠加半透明器官填充 + 亮色边框，输出RGB PNG。
"""
import sys, os, argparse, json
import numpy as np
import nibabel as nib
from scipy.ndimage import zoom as ndimage_zoom, binary_erosion
from PIL import Image

# 每个器官的填充颜色（RGB），与前端 contourColors 顺序一致
COLORS = [
    (230, 200,  50),   # 金黄  - 肝脏
    (220, 100, 100),   # 粉红  - 心脏
    ( 60,  60, 220),   # 深蓝  - 肺
    (100, 200,  80),   # 草绿  - 脾脏
    (200,  80, 200),   # 紫    - 肾
    ( 50, 200, 200),   # 青    - 胰腺
    (220, 130,  50),   # 橙    - 胃
    (150,  80, 220),   # 蓝紫  - 膀胱
    (240,  80,  80),   # 红    - 食管
    ( 80, 220, 160),   # 薄荷绿 - 结肠
    (200, 200,  80),   # 亮黄
    ( 80, 150, 220),   # 天蓝
]

FILL_ALPHA   = 0.45   # 填充区域透明度（0=全透明, 1=全不透明）
BORDER_ALPHA = 0.95   # 边框不透明度
OUTPUT_SIZE  = 512    # 短边最小输出像素


def get_contour(binary_slice):
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
    print(f"[INFO] Masks ({len(mask_paths)})")

    ct_img = nib.load(ct_nii_path)
    ct_data = ct_img.get_fdata()
    zooms = ct_img.header.get_zooms()
    sp = [float(z) if z > 0 else 1.0 for z in zooms[:3]]

    masks_data = []
    for mp in mask_paths:
        m = nib.load(mp).get_fdata()
        masks_data.append((m > 0.5).astype(np.uint8))

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
            # CT 底图（灰度→RGB float）
            if view_name == 'axial':
                ct_sl = ct_data[:, :, i].T
            elif view_name == 'coronal':
                ct_sl = ct_data[:, i, :].T
            else:
                ct_sl = ct_data[i, :, :].T

            ct_sl = smart_zoom(ct_sl, zf, order=3)
            ct_sl = upscale_to_min(ct_sl, order=3)
            ct_gray = to_uint8(ct_sl, gmin, gmax)[::-1]
            H, W = ct_gray.shape
            rgb = np.stack([ct_gray, ct_gray, ct_gray], axis=-1).astype(float)

            # 叠加每个器官
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
                m_bin = (m_sl > 0.5)[::-1]
                if not m_bin.any():
                    continue

                # ── 半透明填充 ──────────────────────────────────
                fill = m_bin
                rgb[fill, 0] = rgb[fill, 0] * (1 - FILL_ALPHA) + color[0] * FILL_ALPHA
                rgb[fill, 1] = rgb[fill, 1] * (1 - FILL_ALPHA) + color[1] * FILL_ALPHA
                rgb[fill, 2] = rgb[fill, 2] * (1 - FILL_ALPHA) + color[2] * FILL_ALPHA

                # ── 亮色边框（实线）───────────────────────────
                border = get_contour(m_bin)
                if border.any():
                    # 边框颜色比填充更亮（加白色混合）
                    bc = tuple(min(255, int(c * 1.3 + 50)) for c in color)
                    rgb[border, 0] = rgb[border, 0] * (1 - BORDER_ALPHA) + bc[0] * BORDER_ALPHA
                    rgb[border, 1] = rgb[border, 1] * (1 - BORDER_ALPHA) + bc[1] * BORDER_ALPHA
                    rgb[border, 2] = rgb[border, 2] * (1 - BORDER_ALPHA) + bc[2] * BORDER_ALPHA

            out_path = os.path.join(view_dir, f'overlay_{i:03d}.png')
            Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode='RGB').save(out_path)

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


