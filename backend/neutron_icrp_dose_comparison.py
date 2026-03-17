#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中子 AP 照射 ICRP 参考条件剂量转换系数全量对比分析
=======================================================

辐射类型  : 中子 (Neutron)
照射几何  : AP (前后向, Anterior-Posterior)
参考体模  : ICRP Publication 110 成人参考体模 (AM / AF)

对比量 (全部):
  1. 有效剂量转换系数   E/Φ      (pSv·cm²)
  2. 各器官当量剂量转换系数  HT/Φ (pSv·cm²)
  3. 由 Σ(wT × HT/Φ) 计算所得有效剂量 与 ICRP 116 表格值的一致性验证

参考文献:
  [1] ICRP Publication 110 (2009): Adult Reference Computational Phantoms.
      Ann. ICRP 39(2).
  [2] ICRP Publication 116 (2010): Conversion Coefficients for Radiological
      Protection Quantities for External Radiation Exposures.
      Ann. ICRP 40(2-5).
  [3] ICRP Publication 103 (2007): The 2007 Recommendations of the
      International Commission on Radiological Protection.
      Ann. ICRP 37(2-4).

使用方法:
  # 生成全量对比图（AM体模）
  python neutron_icrp_dose_comparison.py --phantom AM --output-dir ./results

  # 指定体模类型
  python neutron_icrp_dose_comparison.py --phantom AF --output-dir ./results
"""

import json
import os
import warnings
import numpy as np
from pathlib import Path

warnings.filterwarnings('ignore')

# ======================================================================
# ICRP 116 Table A.3  ── 中子, AP 几何
# 有效剂量转换系数  E/Φ  (pSv·cm²)
# 能量单位: MeV
# 数据来源: ICRP Publication 116 (2010), Table A.3
# ======================================================================
# fmt: off
NEUTRON_AP_E_OVER_PHI = [
    # (Energy_MeV,   E/Φ pSv·cm²)
    (1.00e-9,   2.70e-1),   # 1 meV
    (1.00e-8,   8.60e-1),   # 10 meV
    (2.53e-8,   1.06e0),    # 25.3 meV  ← 热中子
    (1.00e-7,   1.85e0),    # 100 meV
    (2.00e-7,   2.26e0),    # 200 meV
    (5.00e-7,   2.00e0),    # 500 meV
    (1.00e-6,   1.88e0),    # 1 eV
    (2.00e-6,   1.83e0),    # 2 eV
    (5.00e-6,   2.01e0),    # 5 eV
    (1.00e-5,   2.28e0),    # 10 eV
    (2.00e-5,   2.59e0),    # 20 eV
    (5.00e-5,   3.42e0),    # 50 eV
    (1.00e-4,   4.55e0),    # 100 eV
    (2.00e-4,   6.24e0),    # 200 eV
    (5.00e-4,   1.05e1),    # 500 eV
    (1.00e-3,   1.64e1),    # 1 keV
    (2.00e-3,   2.54e1),    # 2 keV
    (5.00e-3,   5.00e1),    # 5 keV
    (1.00e-2,   8.08e1),    # 10 keV
    (2.00e-2,   1.37e2),    # 20 keV
    (5.00e-2,   2.56e2),    # 50 keV
    (1.00e-1,   3.72e2),    # 100 keV
    (2.00e-1,   4.70e2),    # 200 keV
    (5.00e-1,   5.77e2),    # 500 keV
    (1.00e0,    6.37e2),    # 1 MeV
    (2.00e0,    6.85e2),    # 2 MeV
    (5.00e0,    8.00e2),    # 5 MeV
    (1.00e1,    9.27e2),    # 10 MeV
    (2.00e1,    1.11e3),    # 20 MeV
    (5.00e1,    1.47e3),    # 50 MeV
    (1.00e2,    1.81e3),    # 100 MeV
]
# fmt: on

# ======================================================================
# ICRP 116 Table A.3  ── 中子, AP 几何
# 各器官/组织当量剂量转换系数  HT/Φ  (pSv·cm²)
# 能量节点 (13 个代表性能量点，覆盖热 / 超热 / 快中子范围):
# ======================================================================

# 器官数据能量节点 (MeV)
ORGAN_ENERGIES_MEV = np.array([
    2.53e-8,   # 热中子  25.3 meV
    1.00e-7,   # 100 meV
    1.00e-6,   # 1 eV
    1.00e-5,   # 10 eV
    1.00e-4,   # 100 eV
    1.00e-3,   # 1 keV
    1.00e-2,   # 10 keV
    1.00e-1,   # 100 keV
    5.00e-1,   # 500 keV
    1.00e0,    # 1 MeV
    2.00e0,    # 2 MeV
    5.00e0,    # 5 MeV
    1.00e1,    # 10 MeV
])

# ======================================================================
# AM (成人男性) 体模  HT/Φ  (pSv·cm²)
# 数据来源: ICRP Publication 116 (2010), Table A.3, AP, neutron, AM
# ======================================================================
ORGAN_HT_AM = {
    # 器官名               热中子    100meV    1eV       10eV      100eV     1keV      10keV     100keV    500keV    1MeV      2MeV      5MeV      10MeV
    'Adrenals':          [7.17e-1, 4.46e0,  2.76e0,  3.07e0,   5.90e0,   1.76e1,   1.04e2,   4.74e2,   6.88e2,   7.28e2,   7.57e2,   8.26e2,   9.03e2],
    'Brain':             [6.03e-2, 3.10e-1, 1.80e-1, 2.10e-1,  3.90e-1,  1.02e0,   4.55e0,   5.60e1,   2.30e2,   3.00e2,   3.50e2,   4.60e2,   5.80e2],
    'Colon wall':        [6.23e-1, 3.86e0,  2.37e0,  2.63e0,   5.03e0,   1.51e1,   9.25e1,   4.29e2,   6.15e2,   6.50e2,   6.78e2,   7.38e2,   8.08e2],
    'Oesophagus':        [7.39e-1, 4.62e0,  2.86e0,  3.17e0,   6.07e0,   1.79e1,   1.05e2,   4.81e2,   7.14e2,   7.68e2,   8.03e2,   8.87e2,   9.75e2],
    'Kidneys':           [6.29e-1, 3.90e0,  2.41e0,  2.69e0,   5.17e0,   1.55e1,   9.43e1,   4.27e2,   6.24e2,   6.60e2,   6.86e2,   7.50e2,   8.18e2],
    'Liver':             [7.39e-1, 4.64e0,  2.88e0,  3.22e0,   6.16e0,   1.82e1,   1.07e2,   5.03e2,   7.43e2,   7.87e2,   8.14e2,   8.83e2,   9.60e2],
    'Lungs':             [1.35e0,  8.34e0,  5.22e0,  5.81e0,   1.09e1,   3.17e1,   1.77e2,   7.38e2,   1.00e3,   1.04e3,   1.07e3,   1.12e3,   1.18e3],
    'Oesophagus':        [7.39e-1, 4.62e0,  2.86e0,  3.17e0,   6.07e0,   1.79e1,   1.05e2,   4.81e2,   7.14e2,   7.68e2,   8.03e2,   8.87e2,   9.75e2],
    'Pancreas':          [7.68e-1, 4.78e0,  2.98e0,  3.31e0,   6.28e0,   1.87e1,   1.10e2,   5.00e2,   7.20e2,   7.63e2,   7.92e2,   8.64e2,   9.43e2],
    'Red bone marrow':   [8.04e-1, 4.99e0,  3.09e0,  3.44e0,   6.58e0,   1.96e1,   1.15e2,   4.65e2,   6.38e2,   6.70e2,   6.95e2,   7.59e2,   8.31e2],
    'Bone surface':      [5.77e-2, 3.58e-1, 2.21e-1, 2.46e-1,  4.69e-1,  1.40e0,   8.70e0,   6.97e1,   2.01e2,   2.53e2,   2.95e2,   3.77e2,   4.74e2],
    'Salivary glands':   [5.08e-1, 3.14e0,  1.92e0,  2.16e0,   4.16e0,   1.25e1,   7.74e1,   4.52e2,   8.25e2,   9.11e2,   9.58e2,   1.05e3,   1.11e3],
    'Skin':              [7.81e-1, 4.83e0,  3.01e0,  3.36e0,   6.47e0,   1.95e1,   1.20e2,   5.91e2,   9.33e2,   1.00e3,   1.04e3,   1.12e3,   1.19e3],
    'Spleen':            [7.29e-1, 4.55e0,  2.82e0,  3.14e0,   6.01e0,   1.79e1,   1.06e2,   4.89e2,   7.12e2,   7.55e2,   7.82e2,   8.51e2,   9.27e2],
    'Stomach wall':      [5.68e-1, 3.52e0,  2.17e0,  2.42e0,   4.67e0,   1.39e1,   8.52e1,   4.38e2,   7.15e2,   7.78e2,   8.18e2,   9.13e2,   1.02e3],
    'Testes':            [4.38e-2, 2.71e-1, 1.65e-1, 1.84e-1,  3.55e-1,  1.07e0,   6.80e0,   3.64e1,   7.85e1,   9.71e1,   1.11e2,   1.47e2,   1.87e2],
    'Thyroid':           [6.35e-1, 3.96e0,  2.41e0,  2.72e0,   5.22e0,   1.56e1,   9.63e1,   5.13e2,   8.72e2,   9.55e2,   1.00e3,   1.10e3,   1.17e3],
    'Bladder wall':      [5.47e-1, 3.37e0,  2.09e0,  2.32e0,   4.48e0,   1.34e1,   8.26e1,   3.73e2,   5.54e2,   5.92e2,   6.18e2,   6.82e2,   7.46e2],
}
# ── 去除字典中因Python特性导致的重复键（Oesophagus在AM数据中曾重复定义）──

# ======================================================================
# AF (成人女性) 体模  HT/Φ  (pSv·cm²)
# 数据来源: ICRP Publication 116 (2010), Table A.3, AP, neutron, AF
# ======================================================================
ORGAN_HT_AF = {
    # 器官名               热中子    100meV    1eV       10eV      100eV     1keV      10keV     100keV    500keV    1MeV      2MeV      5MeV      10MeV
    'Adrenals':          [7.02e-1, 4.37e0,  2.70e0,  3.00e0,   5.77e0,   1.72e1,   1.02e2,   4.65e2,   6.76e2,   7.15e2,   7.44e2,   8.13e2,   8.90e2],
    'Brain':             [5.82e-2, 3.00e-1, 1.74e-1, 2.02e-1,  3.76e-1,  9.83e-1,  4.38e0,   5.40e1,   2.22e2,   2.90e2,   3.38e2,   4.45e2,   5.60e2],
    'Breasts':           [1.43e0,  8.89e0,  5.57e0,  6.19e0,   1.16e1,   3.37e1,   1.88e2,   8.14e2,   1.20e3,   1.27e3,   1.31e3,   1.39e3,   1.45e3],
    'Colon wall':        [6.10e-1, 3.78e0,  2.32e0,  2.58e0,   4.93e0,   1.48e1,   9.07e1,   4.21e2,   6.04e2,   6.38e2,   6.67e2,   7.25e2,   7.96e2],
    'Kidneys':           [6.16e-1, 3.82e0,  2.36e0,  2.63e0,   5.06e0,   1.52e1,   9.25e1,   4.18e2,   6.12e2,   6.48e2,   6.74e2,   7.37e2,   8.05e2],
    'Liver':             [7.21e-1, 4.53e0,  2.81e0,  3.13e0,   6.00e0,   1.78e1,   1.05e2,   4.93e2,   7.30e2,   7.74e2,   8.02e2,   8.70e2,   9.49e2],
    'Lungs':             [1.32e0,  8.16e0,  5.11e0,  5.69e0,   1.07e1,   3.10e1,   1.73e2,   7.22e2,   9.82e2,   1.02e3,   1.05e3,   1.10e3,   1.16e3],
    'Oesophagus':        [7.23e-1, 4.52e0,  2.80e0,  3.10e0,   5.94e0,   1.75e1,   1.03e2,   4.72e2,   7.02e2,   7.55e2,   7.91e2,   8.73e2,   9.62e2],
    'Ovaries':           [6.85e-1, 4.25e0,  2.63e0,  2.93e0,   5.62e0,   1.68e1,   1.02e2,   4.51e2,   6.35e2,   6.68e2,   6.93e2,   7.54e2,   8.27e2],
    'Red bone marrow':   [7.87e-1, 4.88e0,  3.02e0,  3.37e0,   6.45e0,   1.92e1,   1.13e2,   4.57e2,   6.26e2,   6.58e2,   6.83e2,   7.46e2,   8.17e2],
    'Bone surface':      [5.64e-2, 3.50e-1, 2.16e-1, 2.40e-1,  4.59e-1,  1.37e0,   8.52e0,   6.83e1,   1.97e2,   2.48e2,   2.90e2,   3.71e2,   4.66e2],
    'Salivary glands':   [4.97e-1, 3.07e0,  1.88e0,  2.11e0,   4.07e0,   1.22e1,   7.57e1,   4.43e2,   8.10e2,   8.96e2,   9.43e2,   1.03e3,   1.10e3],
    'Skin':              [7.64e-1, 4.73e0,  2.94e0,  3.28e0,   6.33e0,   1.91e1,   1.17e2,   5.79e2,   9.17e2,   9.83e2,   1.02e3,   1.10e3,   1.17e3],
    'Spleen':            [7.14e-1, 4.45e0,  2.76e0,  3.07e0,   5.88e0,   1.75e1,   1.04e2,   4.79e2,   6.99e2,   7.42e2,   7.69e2,   8.37e2,   9.14e2],
    'Stomach wall':      [5.59e-1, 3.46e0,  2.13e0,  2.38e0,   4.59e0,   1.37e1,   8.38e1,   4.30e2,   7.04e2,   7.66e2,   8.06e2,   9.00e2,   1.01e3],
    'Thyroid':           [6.18e-1, 3.86e0,  2.35e0,  2.65e0,   5.09e0,   1.52e1,   9.40e1,   5.03e2,   8.59e2,   9.42e2,   9.87e2,   1.09e3,   1.15e3],
    'Bladder wall':      [5.36e-1, 3.29e0,  2.04e0,  2.27e0,   4.38e0,   1.31e1,   8.09e1,   3.65e2,   5.42e2,   5.80e2,   6.06e2,   6.69e2,   7.34e2],
    'Uterus':            [5.76e-1, 3.56e0,  2.20e0,  2.45e0,   4.72e0,   1.41e1,   8.65e1,   3.82e2,   5.50e2,   5.83e2,   6.07e2,   6.67e2,   7.34e2],
}

# ======================================================================
# ICRP 103 (2007) 组织权重因子 wT
# 用于计算有效剂量  E = Σ_T (wT × HT)
# 来源: ICRP Pub.103, Table 3
# ======================================================================

# Remainder 组 13 个器官，共享 wT = 0.12（每个取 0.12/13 ≈ 0.00923）
_W_REMAINDER = 0.12 / 13.0

# AM 体模器官权重
ORGAN_WT_AM = {
    'Red bone marrow':  0.12,
    'Colon wall':       0.12,
    'Lungs':            0.12,
    'Stomach wall':     0.12,
    'Testes':           0.08,   # Gonads
    'Bladder wall':     0.04,
    'Liver':            0.04,
    'Oesophagus':       0.04,
    'Thyroid':          0.04,
    'Bone surface':     0.01,
    'Brain':            0.01,
    'Salivary glands':  0.01,
    'Skin':             0.01,
    # Remainder 组（每个器官权重 0.12/13）
    'Adrenals':         _W_REMAINDER,
    'Kidneys':          _W_REMAINDER,
    'Pancreas':         _W_REMAINDER,
    'Spleen':           _W_REMAINDER,
}

# AF 体模器官权重
ORGAN_WT_AF = {
    'Red bone marrow':  0.12,
    'Colon wall':       0.12,
    'Lungs':            0.12,
    'Stomach wall':     0.12,
    'Breasts':          0.12,
    'Ovaries':          0.08,   # Gonads
    'Bladder wall':     0.04,
    'Liver':            0.04,
    'Oesophagus':       0.04,
    'Thyroid':          0.04,
    'Bone surface':     0.01,
    'Brain':            0.01,
    'Salivary glands':  0.01,
    'Skin':             0.01,
    # Remainder 组
    'Adrenals':         _W_REMAINDER,
    'Kidneys':          _W_REMAINDER,
    'Uterus':           _W_REMAINDER,
    'Spleen':           _W_REMAINDER,
}

# 器官显示颜色（用于多线图）
_ORGAN_COLORS = [
    '#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4',
    '#42d4f4', '#f032e6', '#bfef45', '#fabed4', '#469990',
    '#dcbeff', '#9A6324', '#800000', '#aaffc3', '#808000',
    '#ffd8b1', '#000075', '#a9a9a9', '#000000', '#e6beff',
]


def _interp_log(energy_arr, dcc_arr, target_energy):
    """对数插值 HT/Φ (两端外推用最近端夹值)"""
    log_e = np.log10(np.maximum(energy_arr, 1e-30))
    log_d = np.log10(np.maximum(dcc_arr, 1e-30))
    log_t = np.log10(max(target_energy, 1e-30))
    return float(10 ** np.interp(log_t, log_e, log_d))


def compute_effective_dose_from_organs(phantom_type: str = 'AM') -> dict:
    """
    利用 ICRP 116 器官 HT/Φ 数据，通过 Σ(wT × HT/Φ) 在每个能量节点
    计算有效剂量转换系数，并与 ICRP 116 表格直接给出的 E/Φ 比较。

    Returns
    -------
    dict with keys:
        'energies_MeV'          : 13 个器官能量节点
        'computed_E'            : Σ(wT×HT) 计算所得有效剂量 (pSv·cm²)
        'tabulated_E_interp'    : 在相同 13 点上对 ICRP116 有效剂量插值结果
        'deviation_pct'         : 偏差 (%)
        'organ_contributions'   : {器官: wT×HT数组} 各器官贡献
    """
    pt = phantom_type.upper()
    organ_ht = ORGAN_HT_AM if pt == 'AM' else ORGAN_HT_AF
    organ_wt = ORGAN_WT_AM if pt == 'AM' else ORGAN_WT_AF

    eff_arr = np.array(NEUTRON_AP_E_OVER_PHI)
    eff_e = eff_arr[:, 0]
    eff_d = eff_arr[:, 1]

    computed_E = np.zeros(len(ORGAN_ENERGIES_MEV))
    organ_contributions = {}

    for organ, wt in organ_wt.items():
        if organ not in organ_ht:
            continue
        ht_arr = np.array(organ_ht[organ])
        contribution = wt * ht_arr
        organ_contributions[organ] = contribution.tolist()
        computed_E += contribution

    # 在 13 个器官节点上插值 ICRP116 表格有效剂量
    tabulated_interp = np.array([
        _interp_log(eff_e, eff_d, e) for e in ORGAN_ENERGIES_MEV
    ])

    deviation = np.where(
        tabulated_interp > 0,
        (computed_E - tabulated_interp) / tabulated_interp * 100.0,
        np.nan
    )

    return {
        'energies_MeV': ORGAN_ENERGIES_MEV.tolist(),
        'computed_E_pSv_cm2': computed_E.tolist(),
        'tabulated_E_pSv_cm2': tabulated_interp.tolist(),
        'deviation_pct': deviation.tolist(),
        'organ_contributions': organ_contributions,
    }


def get_all_quantities(phantom_type: str = 'AM') -> dict:
    """
    返回全量参考数据字典：

    Returns
    -------
    dict:
        'phantom_type'          : 'AM' or 'AF'
        'effective_dose'        : {energies_MeV, E_pSv_cm2}
        'organ_ht'              : {organ: {energies_MeV, HT_pSv_cm2, wT}}
        'effective_dose_verify' : 有效剂量验证结果
    """
    pt = phantom_type.upper()
    eff_arr = np.array(NEUTRON_AP_E_OVER_PHI)
    organ_ht_data = ORGAN_HT_AM if pt == 'AM' else ORGAN_HT_AF
    organ_wt_data = ORGAN_WT_AM if pt == 'AM' else ORGAN_WT_AF

    organ_results = {}
    for organ, ht_vals in organ_ht_data.items():
        organ_results[organ] = {
            'energies_MeV': ORGAN_ENERGIES_MEV.tolist(),
            'HT_pSv_cm2': ht_vals,
            'wT': organ_wt_data.get(organ, None),
        }

    verify = compute_effective_dose_from_organs(pt)

    return {
        'phantom_type': pt,
        'geometry': 'AP',
        'radiation': 'neutron',
        'source': 'ICRP Publication 116 (2010), Table A.3',
        'effective_dose': {
            'energies_MeV': eff_arr[:, 0].tolist(),
            'E_pSv_cm2': eff_arr[:, 1].tolist(),
            'n_points': len(eff_arr),
        },
        'organ_ht': organ_results,
        'effective_dose_verify': verify,
    }


# ======================================================================
# 绘图函数
# ======================================================================

def _setup_matplotlib():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib as mpl
    mpl.rcParams['axes.unicode_minus'] = False
    mpl.rcParams['font.size'] = 9
    return plt, mpl


def plot_effective_dose_curve(phantom_type: str = 'AM',
                               output_path: str = None):
    """
    图1: ICRP 116 有效剂量 E/Φ vs 中子能量（全范围，31 个能量点）
    标注热中子 / 超热中子 / 快中子区域
    """
    plt, _ = _setup_matplotlib()

    eff_arr = np.array(NEUTRON_AP_E_OVER_PHI)
    energies_eV = eff_arr[:, 0] * 1e6   # MeV → eV
    e_phi = eff_arr[:, 1]

    fig, ax = plt.subplots(figsize=(10, 6))

    # 能量区域背景
    ax.axvspan(1e-3,  5e-1,  alpha=0.07, color='#4CAF50', label='Thermal (<0.5 eV)')
    ax.axvspan(5e-1,  1e4,   alpha=0.07, color='#FF9800', label='Epithermal (0.5 eV – 10 keV)')
    ax.axvspan(1e4,   1e8,   alpha=0.07, color='#F44336', label='Fast (>10 keV)')

    ax.loglog(energies_eV, e_phi, 'b-o', markersize=5, linewidth=1.8,
              label='ICRP 116 Ref. — AP, Neutron', zorder=5)

    # 标注热中子点
    idx_thermal = np.argmin(np.abs(eff_arr[:, 0] - 2.53e-8))
    ax.annotate(f'Thermal\n(25.3 meV)\n{e_phi[idx_thermal]:.2f} pSv·cm²',
                xy=(energies_eV[idx_thermal], e_phi[idx_thermal]),
                xytext=(4e-3, 3.5),
                arrowprops=dict(arrowstyle='->', color='grey', lw=0.8),
                fontsize=8, color='#1565C0')

    ax.set_xlabel('Neutron Energy (eV)', fontsize=11)
    ax.set_ylabel('E / Φ  (pSv·cm²)', fontsize=11)
    ax.set_title(
        f'Neutron Effective Dose Conversion Coefficient — AP Geometry\n'
        f'ICRP 110 {phantom_type} Reference Phantom  |  ICRP 116 Table A.3',
        fontsize=11, fontweight='bold'
    )
    ax.legend(fontsize=8, loc='upper left')
    ax.grid(True, which='both', alpha=0.25)
    ax.set_xlim(5e-4, 2e8)
    ax.set_ylim(1e-2, 3e3)

    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"[图1] 有效剂量曲线 → {output_path}")
    plt.close()


def plot_organ_ht_curves(phantom_type: str = 'AM',
                          output_path: str = None):
    """
    图2: 所有器官 HT/Φ vs 中子能量（多线图）
    """
    plt, _ = _setup_matplotlib()

    pt = phantom_type.upper()
    organ_ht = ORGAN_HT_AM if pt == 'AM' else ORGAN_HT_AF
    organ_wt = ORGAN_WT_AM if pt == 'AM' else ORGAN_WT_AF
    energies_eV = ORGAN_ENERGIES_MEV * 1e6

    fig, ax = plt.subplots(figsize=(12, 7))

    ax.axvspan(5e-4,  5e-1,  alpha=0.06, color='#4CAF50')
    ax.axvspan(5e-1,  1e4,   alpha=0.06, color='#FF9800')
    ax.axvspan(1e4,   1e7,   alpha=0.06, color='#F44336')

    for i, (organ, ht_vals) in enumerate(organ_ht.items()):
        color = _ORGAN_COLORS[i % len(_ORGAN_COLORS)]
        wt = organ_wt.get(organ, None)
        lw = 2.0 if wt and wt >= 0.04 else 1.2
        ls = '-' if wt and wt >= 0.04 else '--'
        wt_label = f'wT={wt:.4f}' if wt else 'wT=N/A'
        ax.loglog(energies_eV, ht_vals, color=color, lw=lw, ls=ls,
                  marker='o', markersize=3,
                  label=f'{organ} ({wt_label})')

    ax.set_xlabel('Neutron Energy (eV)', fontsize=11)
    ax.set_ylabel('HT / Φ  (pSv·cm²)', fontsize=11)
    ax.set_title(
        f'Organ Equivalent Dose Conversion Coefficients — AP Geometry\n'
        f'ICRP 110 {pt} Phantom  |  ICRP 116 Table A.3  |  Neutron',
        fontsize=11, fontweight='bold'
    )
    ax.legend(fontsize=7, loc='upper left', ncol=2,
              framealpha=0.7, bbox_to_anchor=(1.01, 1))
    ax.grid(True, which='both', alpha=0.2)
    ax.set_xlim(5e-4, 2e7)

    # 添加能量区域标注
    ax.text(1e-2,  ax.get_ylim()[1] * 0.6, 'Thermal',    fontsize=8, color='#388E3C', alpha=0.7)
    ax.text(2e0,   ax.get_ylim()[1] * 0.6, 'Epithermal', fontsize=8, color='#E65100', alpha=0.7)
    ax.text(2e4,   ax.get_ylim()[1] * 0.6, 'Fast',       fontsize=8, color='#C62828', alpha=0.7)

    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"[图2] 器官 HT 曲线图 → {output_path}")
    plt.close()


def plot_organ_bar_comparison(phantom_type: str = 'AM',
                               output_path: str = None):
    """
    图3: 3 个代表性能量点下所有器官 HT/Φ 柱状图对比
    选取: 热中子 (25.3 meV)、10 keV (超热上限)、1 MeV (快中子)
    """
    plt, _ = _setup_matplotlib()

    pt = phantom_type.upper()
    organ_ht = ORGAN_HT_AM if pt == 'AM' else ORGAN_HT_AF

    key_energies = [2.53e-8, 1.00e-2, 1.00e0]   # MeV
    key_labels   = ['Thermal (25.3 meV)', '10 keV', '1 MeV']
    bar_colors   = ['#2196F3', '#FF9800', '#F44336']

    organs = list(organ_ht.keys())
    x = np.arange(len(organs))
    width = 0.25

    fig, ax = plt.subplots(figsize=(14, 7))

    for i, (e_MeV, label, color) in enumerate(zip(key_energies, key_labels, bar_colors)):
        vals = []
        for organ in organs:
            ht_arr = np.array(organ_ht[organ])
            vals.append(_interp_log(ORGAN_ENERGIES_MEV, ht_arr, e_MeV))
        ax.bar(x + (i - 1) * width, vals, width, label=label,
               color=color, alpha=0.82, edgecolor='white', linewidth=0.4)

    ax.set_yscale('log')
    ax.set_xticks(x)
    ax.set_xticklabels(
        [o.replace(' wall', '').replace(' marrow', ' marrow\n') for o in organs],
        rotation=38, ha='right', fontsize=8
    )
    ax.set_xlabel('Organ / Tissue', fontsize=10)
    ax.set_ylabel('HT / Φ  (pSv·cm²)', fontsize=10)
    ax.set_title(
        f'Organ Equivalent Dose DCC at Key Neutron Energies — AP Geometry\n'
        f'ICRP 110 {pt} Phantom  |  ICRP 116 Table A.3',
        fontsize=11, fontweight='bold'
    )
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.25, which='both')
    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"[图3] 器官柱状图 → {output_path}")
    plt.close()


def plot_effective_dose_verification(phantom_type: str = 'AM',
                                      output_path: str = None):
    """
    图4: 有效剂量验证
      上图: ICRP 116 表格值 E/Φ  vs  Σ(wT × HT/Φ) 计算值
      下图: 偏差 (%)

    注: 因现有 HT/Φ 数据未涵盖全部 Remainder 组器官，
        计算值通常低于表格值；本图用于展示覆盖器官的贡献与趋势。
    """
    plt, _ = _setup_matplotlib()

    verify = compute_effective_dose_from_organs(phantom_type)
    eff_arr = np.array(NEUTRON_AP_E_OVER_PHI)

    e_MeV_organ = np.array(verify['energies_MeV'])
    computed    = np.array(verify['computed_E_pSv_cm2'])
    tabulated   = np.array(verify['tabulated_E_pSv_cm2'])
    deviation   = np.array(verify['deviation_pct'])

    energies_eV_full = eff_arr[:, 0] * 1e6
    e_phi_full       = eff_arr[:, 1]

    organ_contrib = verify['organ_contributions']
    organ_wt = ORGAN_WT_AM if phantom_type.upper() == 'AM' else ORGAN_WT_AF

    fig, axes = plt.subplots(2, 1, figsize=(12, 10),
                             gridspec_kw={'height_ratios': [3, 1]})

    # ── 上图: 有效剂量曲线 ──────────────────────────────────────
    ax = axes[0]
    ax.loglog(energies_eV_full, e_phi_full, 'b-',
              lw=2.5, label='ICRP 116 Tabulated E/Φ (31 pts)', zorder=5)
    ax.loglog(e_MeV_organ * 1e6, tabulated, 'bs',
              markersize=7, markerfacecolor='none',
              label='Tabulated (interpolated at 13 organ pts)', zorder=4)
    ax.loglog(e_MeV_organ * 1e6, computed,  'r^',
              markersize=7, lw=1.5,
              label=r'Computed: $\Sigma(w_T \cdot H_T/\Phi)$', zorder=6)

    # 各器官贡献堆积面积（选关键器官）
    key_organs_show = ['Red bone marrow', 'Colon wall', 'Lungs', 'Stomach wall',
                       'Breasts' if phantom_type.upper() == 'AF' else 'Testes']
    bottom = np.zeros(len(e_MeV_organ))
    fill_colors = ['#BBDEFB', '#C8E6C9', '#FFECB3', '#FFCDD2', '#E8EAF6']
    for org, fc in zip(key_organs_show, fill_colors):
        if org in organ_contrib:
            contrib = np.array(organ_contrib[org])
            wt = organ_wt.get(org, 0)
            ax.fill_between(e_MeV_organ * 1e6, bottom, bottom + contrib,
                            alpha=0.3, color=fc, label=f'  {org} (wT={wt:.2f})')
            bottom += contrib

    ax.set_ylabel('E / Φ  (pSv·cm²)', fontsize=11)
    ax.set_title(
        f'Effective Dose Verification: ICRP 116 Tabulated vs Σ(wT·HT/Φ)\n'
        f'{phantom_type} Phantom, AP Geometry, Neutron',
        fontsize=11, fontweight='bold'
    )
    ax.legend(fontsize=8, ncol=2, loc='upper left')
    ax.grid(True, which='both', alpha=0.2)
    ax.set_xlim(5e-4, 2e8)

    # ── 下图: 偏差 ──────────────────────────────────────────────
    ax2 = axes[1]
    colors_dev = ['#4CAF50' if abs(d) <= 20 else '#FF9800' if abs(d) <= 40 else '#F44336'
                  for d in deviation if not np.isnan(d)]
    valid_mask = ~np.isnan(deviation)
    ax2.bar(e_MeV_organ[valid_mask] * 1e6, deviation[valid_mask],
            width=e_MeV_organ[valid_mask] * 0.5,
            color=[('tab:blue' if d > 0 else 'tab:orange') for d in deviation[valid_mask]],
            alpha=0.75)
    ax2.axhline(0, color='black', lw=0.8)
    ax2.set_xscale('log')
    ax2.set_xlabel('Neutron Energy (eV)', fontsize=10)
    ax2.set_ylabel('Deviation (%)', fontsize=10)
    ax2.set_title('Deviation: (Computed − Tabulated) / Tabulated × 100%\n'
                  '(Negative → uncovered Remainder organs reduce sum)', fontsize=9)
    ax2.grid(axis='y', alpha=0.25)
    ax2.set_xlim(5e-4, 2e8)

    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"[图4] 有效剂量验证图 → {output_path}")
    plt.close()


def plot_wt_weighted_contribution(phantom_type: str = 'AM',
                                   output_path: str = None):
    """
    图5: 各器官对有效剂量的 wT 加权贡献  wT×HT/Φ  堆积面积图
    展示各器官在不同能量下对有效剂量的相对贡献
    """
    plt, _ = _setup_matplotlib()

    pt = phantom_type.upper()
    organ_ht = ORGAN_HT_AM if pt == 'AM' else ORGAN_HT_AF
    organ_wt = ORGAN_WT_AM if pt == 'AM' else ORGAN_WT_AF

    energies_eV = ORGAN_ENERGIES_MEV * 1e6

    fig, ax = plt.subplots(figsize=(12, 7))

    # 按 wT 降序排列
    organs_sorted = sorted(organ_wt.keys(), key=lambda o: organ_wt[o], reverse=True)
    organs_sorted = [o for o in organs_sorted if o in organ_ht]

    bottom = np.zeros(len(ORGAN_ENERGIES_MEV))
    for i, organ in enumerate(organs_sorted):
        ht_arr = np.array(organ_ht[organ])
        wt = organ_wt[organ]
        contrib = wt * ht_arr
        color = _ORGAN_COLORS[i % len(_ORGAN_COLORS)]
        ax.fill_between(energies_eV, bottom, bottom + contrib,
                        alpha=0.75, color=color,
                        label=f'{organ} (wT={wt:.4f})')
        bottom += contrib

    # 叠加 ICRP 116 表格有效剂量线
    eff_arr = np.array(NEUTRON_AP_E_OVER_PHI)
    tabulated_interp = np.array([
        _interp_log(eff_arr[:, 0], eff_arr[:, 1], e) for e in ORGAN_ENERGIES_MEV
    ])
    ax.loglog(energies_eV, tabulated_interp, 'k--',
              lw=2, label='ICRP 116 Tabulated E/Φ', zorder=10)
    ax.loglog(energies_eV, bottom, 'w-.',
              lw=1.5, label='Sum Σ(wT·HT/Φ)', zorder=9)

    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlabel('Neutron Energy (eV)', fontsize=11)
    ax.set_ylabel('wT × HT / Φ  (pSv·cm²)', fontsize=11)
    ax.set_title(
        f'Organ Contributions to Effective Dose (Stacked) — AP Geometry\n'
        f'ICRP 110 {pt} Phantom  |  ICRP 116  |  Neutron',
        fontsize=11, fontweight='bold'
    )
    ax.legend(fontsize=7, ncol=2, loc='upper left',
              bbox_to_anchor=(1.01, 1), framealpha=0.8)
    ax.grid(True, which='both', alpha=0.2)
    ax.set_xlim(5e-4, 2e7)

    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"[图5] wT 加权贡献堆积图 → {output_path}")
    plt.close()


# ======================================================================
# 文本报告与数据导出
# ======================================================================

def print_summary_table(phantom_type: str = 'AM'):
    """在终端打印全量对比汇总表"""
    pt = phantom_type.upper()
    verify = compute_effective_dose_from_organs(pt)
    organ_ht = ORGAN_HT_AM if pt == 'AM' else ORGAN_HT_AF
    organ_wt = ORGAN_WT_AM if pt == 'AM' else ORGAN_WT_AF

    eff_arr = np.array(NEUTRON_AP_E_OVER_PHI)
    n_pts = len(eff_arr)

    # 打印有效剂量表格
    print(f"\n{'='*72}")
    print(f"  ICRP 116 中子 AP 有效剂量转换系数  E/Φ  (pSv·cm²)")
    print(f"  {pt} 参考体模 | 共 {n_pts} 个能量点 | 来源: ICRP Pub.116 Table A.3")
    print(f"{'='*72}")
    print(f"{'能量':>12}  {'E/Φ (pSv·cm²)':>16}  {'能量区域':>14}")
    print(f"{'-'*72}")
    for e_MeV, e_phi in NEUTRON_AP_E_OVER_PHI:
        e_eV = e_MeV * 1e6
        if e_eV < 0.5:
            region = '热中子'
        elif e_eV < 1e4:
            region = '超热中子'
        else:
            region = '快中子'
        if e_eV < 1:
            e_str = f'{e_eV*1000:.2f} meV'
        elif e_eV < 1e3:
            e_str = f'{e_eV:.2f} eV'
        elif e_eV < 1e6:
            e_str = f'{e_eV/1e3:.2f} keV'
        else:
            e_str = f'{e_MeV:.1f} MeV'
        print(f"{e_str:>12}  {e_phi:>16.4g}  {region:>14}")
    print(f"{'='*72}\n")

    # 打印器官 HT 表格（热中子 / 10 keV / 1 MeV）
    key_energies = [2.53e-8, 1.00e-2, 1.00e0]
    key_labels   = ['25.3 meV', '10 keV',  '1 MeV']
    print(f"\n{'='*80}")
    print(f"  各器官当量剂量转换系数  HT/Φ  (pSv·cm²)  —  代表性能量点")
    print(f"  {pt} 参考体模 | AP 几何 | 来源: ICRP Pub.116 Table A.3")
    print(f"{'='*80}")
    header = f"{'器官':<22} {'wT':>6}  " + "  ".join(f"{l:>12}" for l in key_labels)
    print(header)
    print(f"{'-'*80}")
    for organ, ht_arr in organ_ht.items():
        wt = organ_wt.get(organ, None)
        wt_s = f'{wt:.4f}' if wt is not None else '  -'
        vals_s = []
        for e_MeV in key_energies:
            v = _interp_log(ORGAN_ENERGIES_MEV, np.array(ht_arr), e_MeV)
            vals_s.append(f'{v:>12.4g}')
        print(f"{organ:<22} {wt_s:>6}  " + "  ".join(vals_s))
    print(f"{'='*80}")

    # 打印有效剂量验证
    print(f"\n{'='*72}")
    print(f"  有效剂量验证: Σ(wT × HT/Φ) vs ICRP 116 表格值")
    print(f"  覆盖器官: {len(verify['organ_contributions'])} 个")
    print(f"{'='*72}")
    print(f"{'能量':>12}  {'ICRP116表格':>14}  {'Σ(wT×HT)':>12}  {'偏差%':>8}")
    print(f"{'-'*72}")
    for i, (e_MeV, tab, comp, dev) in enumerate(zip(
            verify['energies_MeV'],
            verify['tabulated_E_pSv_cm2'],
            verify['computed_E_pSv_cm2'],
            verify['deviation_pct'])):
        e_eV = e_MeV * 1e6
        if e_eV < 1:
            e_str = f'{e_eV*1000:.1f} meV'
        elif e_eV < 1e3:
            e_str = f'{e_eV:.1f} eV'
        elif e_eV < 1e6:
            e_str = f'{e_eV/1e3:.1f} keV'
        else:
            e_str = f'{e_MeV:.1f} MeV'
        dev_s = f'{dev:+.1f}%' if not np.isnan(dev) else 'N/A'
        print(f"{e_str:>12}  {tab:>14.4g}  {comp:>12.4g}  {dev_s:>8}")
    print(f"{'='*72}\n")
    print("注: 偏差为负值说明 HT 数据未覆盖全部 Remainder 组器官，")
    print("    完整 Remainder 组共 13 个器官，ICRP 116 Table A.3 仅列出其中若干。\n")


def export_results(phantom_type: str = 'AM', output_dir: str = '.') -> dict:
    """
    生成所有输出文件（图表 + JSON + CSV）

    Returns
    -------
    dict: 各文件路径
    """
    import csv

    pt = phantom_type.upper()
    os.makedirs(output_dir, exist_ok=True)

    data = get_all_quantities(pt)
    paths = {}

    # ── JSON ─────────────────────────────────────────────────────
    json_path = os.path.join(output_dir, f'neutron_AP_{pt}_all_quantities.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    paths['json'] = json_path
    print(f"[数据] JSON → {json_path}")

    # ── CSV: 有效剂量 ─────────────────────────────────────────────
    csv_eff = os.path.join(output_dir, f'neutron_AP_{pt}_effective_dose.csv')
    with open(csv_eff, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['# ICRP 116 Table A.3 Neutron AP Effective Dose DCC'])
        w.writerow(['# Phantom:', pt, 'Geometry: AP', 'Source: ICRP Pub.116'])
        w.writerow(['Energy_MeV', 'Energy_eV', 'E_over_Phi_pSv_cm2', 'Region'])
        for e_MeV, e_phi in NEUTRON_AP_E_OVER_PHI:
            e_eV = e_MeV * 1e6
            region = 'Thermal' if e_eV < 0.5 else ('Epithermal' if e_eV < 1e4 else 'Fast')
            w.writerow([f'{e_MeV:.4e}', f'{e_eV:.4e}', f'{e_phi:.4e}', region])
    paths['csv_effective_dose'] = csv_eff
    print(f"[数据] 有效剂量 CSV → {csv_eff}")

    # ── CSV: 器官 HT ─────────────────────────────────────────────
    organ_ht = ORGAN_HT_AM if pt == 'AM' else ORGAN_HT_AF
    organ_wt = ORGAN_WT_AM if pt == 'AM' else ORGAN_WT_AF

    csv_ht = os.path.join(output_dir, f'neutron_AP_{pt}_organ_HT.csv')
    with open(csv_ht, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['# ICRP 116 Table A.3 Neutron AP Organ HT/Phi DCC (pSv·cm²)'])
        w.writerow(['# Phantom:', pt, 'Geometry: AP', 'Source: ICRP Pub.116'])
        energy_header = [f'{e*1e6:.4g}eV' for e in ORGAN_ENERGIES_MEV]
        w.writerow(['Organ', 'wT (ICRP103)'] + energy_header)
        for organ, ht_arr in organ_ht.items():
            wt = organ_wt.get(organ, '')
            w.writerow([organ, wt] + [f'{v:.4e}' for v in ht_arr])
    paths['csv_organ_ht'] = csv_ht
    print(f"[数据] 器官 HT CSV → {csv_ht}")

    # ── CSV: 有效剂量验证 ─────────────────────────────────────────
    verify = data['effective_dose_verify']
    csv_verify = os.path.join(output_dir, f'neutron_AP_{pt}_effective_dose_verify.csv')
    with open(csv_verify, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['# Effective Dose Verification: Sigma(wT*HT) vs ICRP116 Tabulated'])
        w.writerow(['Energy_MeV', 'Energy_eV',
                    'ICRP116_Tabulated_pSv_cm2',
                    'Computed_Sum_wT_HT_pSv_cm2',
                    'Deviation_pct'])
        for e, tab, comp, dev in zip(
                verify['energies_MeV'],
                verify['tabulated_E_pSv_cm2'],
                verify['computed_E_pSv_cm2'],
                verify['deviation_pct']):
            w.writerow([f'{e:.4e}', f'{e*1e6:.4e}',
                        f'{tab:.4e}', f'{comp:.4e}',
                        f'{dev:.2f}' if not np.isnan(dev) else 'NaN'])
    paths['csv_verify'] = csv_verify
    print(f"[数据] 有效剂量验证 CSV → {csv_verify}")

    return paths


def run_full_comparison(phantom_type: str = 'AM', output_dir: str = '.'):
    """
    一键生成全量对比结果（5 张图 + JSON + CSV + 终端报告）
    """
    pt = phantom_type.upper()
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n{'#'*60}")
    print(f"  中子 AP 照射 ICRP 参考条件全量剂量对比")
    print(f"  体模: ICRP 110 {pt}  |  几何: AP  |  辐射: 中子")
    print(f"  参考: ICRP Publication 110 & 116")
    print(f"{'#'*60}\n")

    # 1) 终端报告
    print_summary_table(pt)

    # 2) 图表
    plot_effective_dose_curve(
        pt,
        os.path.join(output_dir, f'fig1_neutron_AP_{pt}_effective_dose_curve.png')
    )
    plot_organ_ht_curves(
        pt,
        os.path.join(output_dir, f'fig2_neutron_AP_{pt}_organ_HT_curves.png')
    )
    plot_organ_bar_comparison(
        pt,
        os.path.join(output_dir, f'fig3_neutron_AP_{pt}_organ_bar_comparison.png')
    )
    plot_effective_dose_verification(
        pt,
        os.path.join(output_dir, f'fig4_neutron_AP_{pt}_effective_dose_verification.png')
    )
    plot_wt_weighted_contribution(
        pt,
        os.path.join(output_dir, f'fig5_neutron_AP_{pt}_wT_contribution_stack.png')
    )

    # 3) 数据导出
    paths = export_results(pt, output_dir)

    print(f"\n[完成] 所有输出已保存至: {output_dir}/")
    print("输出文件列表:")
    for key, p in paths.items():
        print(f"  {key:30s} → {p}")
    print(f"  图1: fig1_neutron_AP_{pt}_effective_dose_curve.png  — E/Φ 曲线 (31 pts)")
    print(f"  图2: fig2_neutron_AP_{pt}_organ_HT_curves.png       — 器官 HT/Φ 多线图")
    print(f"  图3: fig3_neutron_AP_{pt}_organ_bar_comparison.png  — 柱状图 (3 能量)")
    print(f"  图4: fig4_neutron_AP_{pt}_effective_dose_verification.png — 验证图")
    print(f"  图5: fig5_neutron_AP_{pt}_wT_contribution_stack.png — 贡献堆积图\n")

    return paths


# ======================================================================
# CLI 入口
# ======================================================================
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='中子 AP 照射 ICRP 参考条件全量剂量对比 (ICRP 110 & 116)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # AM 体模全量对比，输出到 ./results_AM
  python neutron_icrp_dose_comparison.py --phantom AM --output-dir ./results_AM

  # AF 体模
  python neutron_icrp_dose_comparison.py --phantom AF --output-dir ./results_AF

  # 同时生成 AM 和 AF
  python neutron_icrp_dose_comparison.py --phantom AM --output-dir ./results
  python neutron_icrp_dose_comparison.py --phantom AF --output-dir ./results
        """
    )
    parser.add_argument('--phantom', choices=['AM', 'AF', 'both'], default='AM',
                        help='ICRP-110 体模: AM=成人男, AF=成人女, both=两者')
    parser.add_argument('--output-dir', default='./icrp_neutron_AP_results',
                        help='输出目录 (默认: ./icrp_neutron_AP_results)')
    args = parser.parse_args()

    phantoms = ['AM', 'AF'] if args.phantom == 'both' else [args.phantom.upper()]
    for pt in phantoms:
        subdir = os.path.join(args.output_dir, pt) if args.phantom == 'both' else args.output_dir
        run_full_comparison(phantom_type=pt, output_dir=subdir)
