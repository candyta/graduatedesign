#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
phantom_preview.py
Generate colorized organ-segmentation slice images from the ICRP-110 full-body
phantom (or the synthetic fallback if real data are not available).

Output directory structure:
    <output_dir>/axial/axial_NNN.png
    <output_dir>/coronal/coronal_NNN.png
    <output_dir>/sagittal/sagittal_NNN.png

Usage:
    python phantom_preview.py <output_dir> [--type AM|AF]
"""
import sys
import os
import json
import argparse
import numpy as np
from pathlib import Path
from PIL import Image

# ── Color table: organ_id → RGB ───────────────────────────────────────────────
# ICRP-110 has ~140 organ IDs.  We map them to clinically-recognisable colours
# by broad tissue category.
_BONE_IDS = set(range(40, 58))          # cortical & spongiosa bone regions
_LUNG_IDS  = {81, 82}                    # left / right lung
_COLON_IDS = set(range(100, 130))       # GI tract
_BRAIN_ID  = {3}
_HEART_ID  = {10, 11}
_LIVER_ID  = {8}
_KIDNEY_ID = {6, 7}
_SKIN_ID   = {130, 131, 132}


def organ_to_rgb(oid: int) -> tuple:
    if oid == 0:
        return (8, 12, 20)              # outside body – near-black bg
    if oid in _LUNG_IDS:
        return (110, 170, 210)          # lung – sky blue
    if oid in _BONE_IDS:
        return (230, 225, 200)          # bone – cream
    if oid in _BRAIN_ID:
        return (210, 180, 160)          # brain – warm tan
    if oid in _HEART_ID:
        return (200, 80, 80)            # heart – red
    if oid in _LIVER_ID:
        return (160, 80, 60)            # liver – dark red-brown
    if oid in _KIDNEY_ID:
        return (180, 120, 90)           # kidney – brown-orange
    if oid in _SKIN_ID:
        return (220, 195, 170)          # skin – light flesh
    if oid in _COLON_IDS:
        return (140, 180, 130)          # GI – green
    # generic soft tissue
    return (185, 145, 120)


def _colorize_slice(arr2d: np.ndarray) -> np.ndarray:
    """arr2d: 2D array of organ IDs → RGB ndarray (H, W, 3) uint8."""
    h, w = arr2d.shape
    rgb = np.empty((h, w, 3), dtype=np.uint8)
    unique_ids = np.unique(arr2d)
    for oid in unique_ids:
        r, g, b = organ_to_rgb(int(oid))
        mask = arr2d == oid
        rgb[mask, 0] = r
        rgb[mask, 1] = g
        rgb[mask, 2] = b
    return rgb


def _rescale_if_needed(rgb: np.ndarray, min_size: int = 512) -> np.ndarray:
    from scipy.ndimage import zoom as ndzoom
    h, w = rgb.shape[:2]
    max_dim = max(h, w)
    if max_dim >= min_size:
        return rgb
    scale = min_size / max_dim
    new_h = max(1, round(h * scale))
    new_w = max(1, round(w * scale))
    # nearest-neighbour so organ boundaries stay sharp
    out = np.stack(
        [ndzoom(rgb[:, :, c], (new_h / h, new_w / w), order=0) for c in range(3)],
        axis=2
    )
    return out.astype(np.uint8)


def generate_phantom_preview(phantom: np.ndarray, output_dir: str) -> dict:
    """
    phantom : np.ndarray  shape (X, Y, Z)  dtype int16, organ IDs
    Returns  {'axial': N_axial, 'coronal': N_coronal, 'sagittal': N_sagittal}
    """
    X, Y, Z = phantom.shape
    views = {
        'axial':    ('z', Z),
        'coronal':  ('y', Y),
        'sagittal': ('x', X),
    }
    counts = {}
    for view_name, (axis, n_slices) in views.items():
        vdir = os.path.join(output_dir, view_name)
        os.makedirs(vdir, exist_ok=True)
        for i in range(n_slices):
            if axis == 'z':
                # transverse (XY plane)
                s = phantom[:, :, i]       # (X, Y)
                arr = s.T                   # (Y, X) – rows=Y, cols=X
            elif axis == 'y':
                # coronal (XZ plane)
                s = phantom[:, i, :]       # (X, Z)
                arr = s.T[::-1]             # (Z, X) flipped so Z=0 is at bottom
            else:
                # sagittal (YZ plane)
                s = phantom[i, :, :]       # (Y, Z)
                arr = s.T[::-1]             # (Z, Y) flipped
            rgb = _colorize_slice(arr)
            rgb = _rescale_if_needed(rgb)
            Image.fromarray(rgb, mode='RGB').save(
                os.path.join(vdir, f'{view_name}_{i:03d}.png')
            )
        counts[view_name] = n_slices
    return counts


def load_phantom(phantom_type: str = 'AM') -> np.ndarray:
    """Load ICRP-110 phantom array, falling back to synthetic phantom."""
    here = Path(__file__).parent
    sys.path.insert(0, str(here))
    from ct_phantom_fusion import load_icrp110_phantom, _build_fallback_phantom
    try:
        return load_icrp110_phantom(phantom_type)
    except FileNotFoundError:
        print(f'[phantom_preview] ICRP-110 {phantom_type} data not found, '
              'using synthetic fallback phantom.', flush=True)
        return _build_fallback_phantom()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate phantom preview slices')
    parser.add_argument('output_dir', help='Directory to write slice images')
    parser.add_argument('--type', default='AM', choices=['AM', 'AF'],
                        help='Phantom type (default: AM)')
    args = parser.parse_args()

    try:
        data = load_phantom(args.type)
        counts = generate_phantom_preview(data, args.output_dir)
        print(json.dumps({'success': True, 'slices': counts}), flush=True)
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}), flush=True)
        sys.exit(1)
