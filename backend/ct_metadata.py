#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ct_metadata.py
Extract CT volume metadata from a NIfTI file.
Returns JSON with shape, voxel size, physical dimensions, and center coordinates.
"""
import nibabel as nib
import numpy as np
import sys
import json


def get_ct_metadata(nii_path):
    img = nib.load(nii_path)
    shape = list(map(int, img.shape[:3]))
    zooms = img.header.get_zooms()[:3]
    voxel_size_mm = [float(z) if float(z) > 0 else 1.0 for z in zooms]

    # Physical volume size in mm and cm
    phys_size_mm = [shape[i] * voxel_size_mm[i] for i in range(3)]
    phys_size_cm = [s / 10.0 for s in phys_size_mm]

    # Center voxel indices (integer)
    center_voxel = [s // 2 for s in shape]

    # Physical center of the CT volume (from affine if available, else simple estimate)
    affine = img.affine
    center_vox_arr = np.array([s / 2.0 for s in shape[:3]])
    center_phys = affine[:3, :3] @ center_vox_arr + affine[:3, 3]
    center_phys_cm = [float(c) / 10.0 for c in center_phys]

    # Fallback: half of physical size (always available)
    center_simple_cm = [s / 2.0 for s in phys_size_cm]

    return {
        "shape": shape,
        "voxel_size_mm": voxel_size_mm,
        "phys_size_mm": phys_size_mm,
        "phys_size_cm": phys_size_cm,
        "center_voxel": center_voxel,
        "center_phys_cm": center_phys_cm,
        "center_simple_cm": center_simple_cm
    }


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: ct_metadata.py <nii_path>"}))
        sys.exit(1)
    try:
        result = get_ct_metadata(sys.argv[1])
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
