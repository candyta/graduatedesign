#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ICRP-110 Organ/Tissue → MCNP Material Mapping

Reads the official ICRP-110 phantom data files (AM/AF) to build
organ-to-material mappings and material compositions for MCNP.

Data files required (from ICRP-110 CD):
  - {phantom}_organs.dat   : organ ID → tissue number + density
  - {phantom}_media.dat    : tissue number → elemental composition (% by mass)

Material numbering in MCNP:
  0       = external air/vacuum (imp:n=0)
  1-53    = tissue types from media.dat (faithful to ICRP-110)
  900     = tumor tissue (B-10 loaded soft tissue, for CT-replacement regions)

Nuclear data library: ENDF/B-VI (.66c)

Author: BNCT Team
Date: 2026-02
"""

import os
import re
import numpy as np
from typing import Dict, Tuple, Optional


# ============================================================
# Element Z → MCNP ZAID mapping for ENDF/B-VI (.66c)
# ============================================================

# media.dat header lists elements by Z number:
# 1(H) 6(C) 7(N) 8(O) 11(Na) 12(Mg) 15(P) 16(S) 17(Cl) 19(K) 20(Ca) 26(Fe) 53(I)
ELEMENT_Z_ORDER = [1, 6, 7, 8, 11, 12, 15, 16, 17, 19, 20, 26, 53]

ZAID_MAP = {
    1:  '1001.66c',
    6:  '6000.66c',
    7:  '7014.66c',
    8:  '8016.66c',
    11: '11023.66c',
    12: '12000.66c',
    15: '15031.66c',
    16: '16032.66c',
    17: '17000.66c',
    19: '19000.66c',
    20: '20000.66c',
    26: '26056.66c',   # Fe-56 (91.7% natural); 26000.66c missing in some MCNP5 xsdir
    53: '53127.66c',
}


# ============================================================
# Data file parsers
# ============================================================

def parse_organs_dat(filepath: str) -> Dict[int, Tuple[int, float, str]]:
    """
    Parse ICRP-110 organs.dat file.

    Returns
    -------
    dict : {organ_id: (tissue_number, density, organ_name)}
    """
    organs = {}
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip('\r\n')
        # Match lines starting with an organ ID number
        # Format: "1     Adrenal, left                                    43    1.030"
        m = re.match(r'^\s*(\d+)\s+(.+?)\s{2,}(\d+)\s+([\d.]+)\s*$', line)
        if m:
            organ_id = int(m.group(1))
            organ_name = m.group(2).strip()
            tissue_num = int(m.group(3))
            density = float(m.group(4))
            organs[organ_id] = (tissue_num, density, organ_name)

    return organs


def parse_media_dat(filepath: str) -> Dict[int, Tuple[str, Dict[int, float]]]:
    """
    Parse ICRP-110 media.dat file.

    Returns
    -------
    dict : {tissue_number: (tissue_name, {element_Z: mass_fraction})}
           Mass fractions are in [0, 1] (converted from percentage).
    """
    media = {}
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip('\r\n')
        # Match lines starting with tissue number
        # Data columns are right-aligned, tissue number is left-most
        m = re.match(r'^\s*(\d+)\s+(.+?)\s{2,}([\d.]+(?:\s+[\d.]+)*)\s*$', line)
        if m:
            tissue_num = int(m.group(1))
            tissue_name = m.group(2).strip()
            values_str = m.group(3).strip()
            values = [float(v) for v in values_str.split()]

            if len(values) != len(ELEMENT_Z_ORDER):
                continue

            # Convert from percentage to fraction
            composition = {}
            for z, pct in zip(ELEMENT_Z_ORDER, values):
                frac = pct / 100.0
                if frac > 0.0:
                    composition[z] = frac

            media[tissue_num] = (tissue_name, composition)

    return media


# ============================================================
# Main data structure builder
# ============================================================

class ICRP110Materials:
    """
    Manages organ → material mapping and material definitions for a
    specific ICRP-110 phantom (AM or AF).

    Usage
    -----
    >>> mat = ICRP110Materials('AF', data_dir='/path/to/AF/')
    >>> mat_id = mat.get_material_id(organ_id=61)   # Brain → tissue 32
    >>> mat.write_mcnp_material_cards(fh, used_ids={32, 29, 50})
    """

    # Tumor material ID (reserved)
    TUMOR_MAT_ID = 900
    TUMOR_ORGAN_ID = 999

    def __init__(self, phantom: str = 'AF', data_dir: Optional[str] = None):
        """
        Parameters
        ----------
        phantom : str
            'AM' (Adult Male) or 'AF' (Adult Female)
        data_dir : str, optional
            Directory containing the phantom data files.
            If None, looks in ./{phantom}/
        """
        self.phantom = phantom.upper()
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(__file__), self.phantom)
        self.data_dir = data_dir

        organs_file = os.path.join(data_dir, f'{self.phantom}_organs.dat')
        media_file = os.path.join(data_dir, f'{self.phantom}_media.dat')

        if not os.path.isfile(organs_file):
            raise FileNotFoundError(f"Organs file not found: {organs_file}")
        if not os.path.isfile(media_file):
            raise FileNotFoundError(f"Media file not found: {media_file}")

        # Parse data files
        self.organs = parse_organs_dat(organs_file)
        self.media = parse_media_dat(media_file)

        # Build organ_id → tissue_number lookup
        # (tissue_number is the MCNP material number)
        self._organ_to_tissue = {}
        self._organ_to_density = {}
        for organ_id, (tissue_num, density, name) in self.organs.items():
            self._organ_to_tissue[organ_id] = tissue_num
            self._organ_to_density[organ_id] = density

        # Build tissue_number → density lookup (from organs.dat, first occurrence)
        self._tissue_density = {}
        for organ_id, (tissue_num, density, name) in self.organs.items():
            if tissue_num not in self._tissue_density:
                self._tissue_density[tissue_num] = density

        # Add tumor material definition (soft tissue + B-10)
        self._build_tumor_material()

    def _build_tumor_material(self):
        """Create tumor material: soft tissue (media 29) + 60 ppm B-10."""
        if 29 in self.media:
            base_name, base_comp = self.media[29]
            tumor_comp = dict(base_comp)
            # Add ~60 ppm B-10, slightly reduce C to compensate
            b10_frac = 0.00006
            if 6 in tumor_comp:
                tumor_comp[6] = max(0, tumor_comp[6] - b10_frac)
            tumor_comp[5] = b10_frac  # Z=5 is Boron (B-10)
            self.media[self.TUMOR_MAT_ID] = ('Tumor Tissue (B-10 loaded)', tumor_comp)
            self._tissue_density[self.TUMOR_MAT_ID] = 1.04

    def get_material_id(self, organ_id: int) -> int:
        """
        Map ICRP-110 organ ID to MCNP material number (= tissue number).

        Parameters
        ----------
        organ_id : int
            ICRP-110 organ ID (1-140), 0 for external, 999 for tumor

        Returns
        -------
        int
            MCNP material number. 0 = external void.
        """
        if organ_id <= 0:
            return 0
        if organ_id == self.TUMOR_ORGAN_ID:
            return self.TUMOR_MAT_ID
        return self._organ_to_tissue.get(organ_id, 0)

    def get_density(self, organ_id: int) -> float:
        """
        Get density for an organ ID.

        Returns
        -------
        float
            Density in g/cm3. 0.0 for external.
        """
        if organ_id <= 0:
            return 0.0
        if organ_id == self.TUMOR_ORGAN_ID:
            return self._tissue_density[self.TUMOR_MAT_ID]
        return self._organ_to_density.get(organ_id, 0.0)

    def get_tissue_density(self, tissue_num: int) -> float:
        """Get density for a tissue/material number."""
        return self._tissue_density.get(tissue_num, 0.0)

    def build_material_volume(self, phantom_data: np.ndarray) -> np.ndarray:
        """
        Convert organ ID array to material number array.

        Parameters
        ----------
        phantom_data : np.ndarray
            Organ ID array (any shape)

        Returns
        -------
        np.ndarray
            Material number array, same shape, dtype=int16
            (int16 to accommodate material IDs up to 900)
        """
        vectorized_map = np.vectorize(self.get_material_id)
        return vectorized_map(phantom_data).astype(np.int16)

    def build_density_volume(self, phantom_data: np.ndarray) -> np.ndarray:
        """
        Convert organ ID array to density array.

        Parameters
        ----------
        phantom_data : np.ndarray
            Organ ID array (any shape)

        Returns
        -------
        np.ndarray
            Density array in g/cm3, same shape, dtype=float32
        """
        vectorized_map = np.vectorize(self.get_density)
        return vectorized_map(phantom_data).astype(np.float32)

    def get_used_materials(self, phantom_data: np.ndarray) -> set:
        """Get set of material IDs actually present in the phantom data."""
        mat_vol = self.build_material_volume(phantom_data)
        return set(np.unique(mat_vol)) - {0}

    def write_mcnp_material_cards(self, file_handle, material_ids_used: set):
        """
        Write MCNP material cards for all used materials.

        Parameters
        ----------
        file_handle : file
            Open file handle for writing
        material_ids_used : set
            Set of material IDs to write (excluding 0)
        """
        file_handle.write("c\n")
        file_handle.write(f"c  Material definitions from ICRP-110 {self.phantom} phantom\n")
        file_handle.write("c  Nuclear data: ENDF/B-VI (.66c)\n")
        file_handle.write("c\n")

        for mat_id in sorted(material_ids_used):
            if mat_id == 0 or mat_id not in self.media:
                continue

            tissue_name, composition = self.media[mat_id]
            density = self._tissue_density.get(mat_id, 1.0)

            file_handle.write(f"c  M{mat_id}: {tissue_name}, rho={density:.3f} g/cm3\n")
            file_handle.write(f"m{mat_id}\n")

            for z in sorted(composition.keys()):
                frac = composition[z]
                if frac <= 0:
                    continue
                # Special case: B-10 for tumor
                if z == 5:
                    zaid = '5010.66c'
                else:
                    zaid = ZAID_MAP.get(z)
                    if zaid is None:
                        continue
                file_handle.write(f"     {zaid}  {-frac:.6f}\n")

            file_handle.write("c\n")

    def get_organ_info(self, organ_id: int) -> Optional[Tuple[str, int, float]]:
        """
        Get information about an organ.

        Returns
        -------
        tuple or None
            (organ_name, tissue_number, density) or None if not found
        """
        if organ_id in self.organs:
            tissue_num, density, name = self.organs[organ_id]
            return (name, tissue_num, density)
        return None

    def summary(self) -> str:
        """Print a summary of the phantom materials."""
        lines = [f"ICRP-110 {self.phantom} Phantom Material Summary",
                 f"  Organs defined: {len(self.organs)}",
                 f"  Tissue types:   {len(self.media)}",
                 "",
                 "  Tissue # | Density | Name"]
        for tid in sorted(self.media.keys()):
            name, comp = self.media[tid]
            density = self._tissue_density.get(tid, 0.0)
            lines.append(f"  {tid:>6d}   | {density:.3f}   | {name}")
        return '\n'.join(lines)


# ============================================================
# Convenience functions (backward-compatible interface)
# ============================================================

# Default singleton instances (lazy-loaded)
_instances: Dict[str, ICRP110Materials] = {}


def get_instance(phantom: str = 'AF', data_dir: Optional[str] = None) -> ICRP110Materials:
    """Get or create a singleton ICRP110Materials instance."""
    key = f"{phantom.upper()}:{data_dir or 'default'}"
    if key not in _instances:
        _instances[key] = ICRP110Materials(phantom, data_dir)
    return _instances[key]


def get_material_id(organ_id: int, phantom: str = 'AF',
                    data_dir: Optional[str] = None) -> int:
    """
    Convenience function: map organ ID to MCNP material number.

    Parameters
    ----------
    organ_id : int
        ICRP-110 organ ID
    phantom : str
        'AM' or 'AF'

    Returns
    -------
    int
        MCNP material number (0 = external)
    """
    return get_instance(phantom, data_dir).get_material_id(organ_id)


def build_material_volume(phantom_data: np.ndarray, phantom: str = 'AF',
                          data_dir: Optional[str] = None) -> np.ndarray:
    """
    Convenience function: convert organ ID array to material number array.
    """
    return get_instance(phantom, data_dir).build_material_volume(phantom_data)


def write_mcnp_material_cards(file_handle, material_ids_used: set,
                              phantom: str = 'AF',
                              data_dir: Optional[str] = None):
    """
    Convenience function: write MCNP material cards.
    """
    get_instance(phantom, data_dir).write_mcnp_material_cards(
        file_handle, material_ids_used)


# ============================================================
# Self-test
# ============================================================

if __name__ == '__main__':

    # Try to find data directories
    script_dir = os.path.dirname(os.path.abspath(__file__))

    for phantom in ['AF', 'AM']:
        data_dir = os.path.join(script_dir, phantom)
        if not os.path.isdir(data_dir):
            print(f"[SKIP] {phantom} data directory not found at {data_dir}")
            continue

        print(f"\n{'='*60}")
        mat = ICRP110Materials(phantom, data_dir)
        print(mat.summary())

        # Test a few organs
        test_organs = [0, 1, 13, 26, 61, 72, 95, 97, 122, 140, 999]
        print("\n  Test organ → material mapping:")
        for oid in test_organs:
            mid = mat.get_material_id(oid)
            density = mat.get_density(oid)
            info = mat.get_organ_info(oid)
            name = info[0] if info else ('External' if oid <= 0 else 'Tumor' if oid == 999 else '?')
            print(f"    Organ {oid:>4d} → Mat {mid:>3d}, rho={density:.3f}  ({name})")

        # Write test material cards
        test_file = os.path.join(script_dir, f'test_materials_{phantom}.txt')
        with open(test_file, 'w') as f:
            mat.write_mcnp_material_cards(f, {1, 2, 27, 28, 29, 32, 50, 53, 900})
        print(f"\n  Test material cards written to: {test_file}")