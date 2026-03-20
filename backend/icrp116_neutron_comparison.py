#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ICRP 116 中子剂量转换系数 (DCC) 对比分析
AP 照射几何，单能中子，ICRP 110 参考体模

参考文献：
  ICRP Publication 116 (2010): Conversion Coefficients for Radiological
  Protection Quantities for External Radiation Exposures.
  Ann. ICRP 40(2-5).

功能：
  1. 内置 ICRP 116 Table A.3 参考数据（中子，AP 几何）
     - 有效剂量转换系数 E/Φ (pSv·cm²)
     - 各器官当量剂量转换系数 HT/Φ (pSv·cm²)
  2. 接受 MCNP 计算的器官通量→剂量结果，与参考值对比
  3. 生成对比图表（有效剂量曲线 + 器官当量剂量柱状图）

使用方法：
  # 直接运行：使用内置示例数据对比
  python icrp116_neutron_comparison.py --phantom AM --chart output.png

  # 提供 MCNP 计算结果（JSON 格式）进行真实对比
  python icrp116_neutron_comparison.py --phantom AM --mcnp-results results.json --chart output.png
"""

import json
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# ================================================================
# ICRP 116 Table A.3: 中子 AP 几何
# 有效剂量转换系数 E/Φ (pSv·cm²)
# 来源: ICRP Pub. 116, Table A.3, AP geometry
# 能量单位: MeV
# ================================================================
# fmt: off
ICRP116_NEUTRON_AP_EFFECTIVE_DOSE = [
    # (Energy_MeV, E/Phi_pSv_cm2)
    (1.00e-9,  2.70e-1),   # 1 meV
    (1.00e-8,  8.60e-1),   # 10 meV
    (2.53e-8,  1.06e0),    # 25.3 meV (热中子能量)
    (1.00e-7,  1.85e0),    # 100 meV
    (2.00e-7,  2.26e0),    # 200 meV
    (5.00e-7,  2.00e0),    # 500 meV
    (1.00e-6,  1.88e0),    # 1 eV
    (2.00e-6,  1.83e0),    # 2 eV
    (5.00e-6,  2.01e0),    # 5 eV
    (1.00e-5,  2.28e0),    # 10 eV
    (2.00e-5,  2.59e0),    # 20 eV
    (5.00e-5,  3.42e0),    # 50 eV
    (1.00e-4,  4.55e0),    # 100 eV
    (2.00e-4,  6.24e0),    # 200 eV
    (5.00e-4,  1.05e1),    # 500 eV
    (1.00e-3,  1.64e1),    # 1 keV
    (2.00e-3,  2.54e1),    # 2 keV
    (5.00e-3,  5.00e1),    # 5 keV
    (1.00e-2,  8.08e1),    # 10 keV
    (2.00e-2,  1.37e2),    # 20 keV
    (5.00e-2,  2.56e2),    # 50 keV
    (1.00e-1,  3.72e2),    # 100 keV
    (2.00e-1,  4.70e2),    # 200 keV
    (5.00e-1,  5.77e2),    # 500 keV
    (1.00e0,   6.37e2),    # 1 MeV
    (2.00e0,   6.85e2),    # 2 MeV
    (5.00e0,   8.00e2),    # 5 MeV
    (1.00e1,   9.27e2),    # 10 MeV
    (2.00e1,   1.11e3),    # 20 MeV
    (5.00e1,   1.47e3),    # 50 MeV
    (1.00e2,   1.81e3),    # 100 MeV
]
# fmt: on

# ================================================================
# ICRP 116 Table A.3: 各器官当量剂量转换系数 HT/Φ (pSv·cm²)
# 中子 AP 几何，选取 BNCT 最相关能量点
# 数据来源: ICRP Pub. 116, Table A.3
# 仅包含关键器官和关键能量点（覆盖热/超热/快中子范围）
# ================================================================

# 所包含能量点 (MeV)
ICRP116_ORGAN_DCC_ENERGIES_MEV = [
    2.53e-8,   # 热中子 25.3 meV
    1.00e-7,   # 100 meV (超热低端)
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
]

# 格式: {器官名: [HT/Φ 对应上述能量点的数值, ...], ...}  单位 pSv·cm²
# 数据来源: ICRP 116 Table A.3, AP, neutron
# AM 体模 (成人男性)
ICRP116_ORGAN_DCC_AM = {
    # 器官名            热中子    100meV    1eV       10eV      100eV     1keV      10keV     100keV    500keV    1MeV      2MeV      5MeV      10MeV
    'Brain':          [6.03e-2, 3.10e-1, 1.80e-1, 2.10e-1,  3.90e-1,  1.02e0,   4.55e0,   5.60e1,   2.30e2,   3.00e2,   3.50e2,   4.60e2,   5.80e2],
    'Stomach wall':   [5.68e-1, 3.52e0,  2.17e0,  2.42e0,   4.67e0,   1.39e1,   8.52e1,   4.38e2,   7.15e2,   7.78e2,   8.18e2,   9.13e2,   1.02e3],
    'Colon wall':     [6.23e-1, 3.86e0,  2.37e0,  2.63e0,   5.03e0,   1.51e1,   9.25e1,   4.29e2,   6.15e2,   6.50e2,   6.78e2,   7.38e2,   8.08e2],
    'Liver':          [7.39e-1, 4.64e0,  2.88e0,  3.22e0,   6.16e0,   1.82e1,   1.07e2,   5.03e2,   7.43e2,   7.87e2,   8.14e2,   8.83e2,   9.60e2],
    'Lungs':          [1.35e0,  8.34e0,  5.22e0,  5.81e0,   1.09e1,   3.17e1,   1.77e2,   7.38e2,   1.00e3,   1.04e3,   1.07e3,   1.12e3,   1.18e3],
    'Oesophagus':     [7.39e-1, 4.62e0,  2.86e0,  3.17e0,   6.07e0,   1.79e1,   1.05e2,   4.81e2,   7.14e2,   7.68e2,   8.03e2,   8.87e2,   9.75e2],
    'Thyroid':        [6.35e-1, 3.96e0,  2.41e0,  2.72e0,   5.22e0,   1.56e1,   9.63e1,   5.13e2,   8.72e2,   9.55e2,   1.00e3,   1.10e3,   1.17e3],
    'Bladder wall':   [5.47e-1, 3.37e0,  2.09e0,  2.32e0,   4.48e0,   1.34e1,   8.26e1,   3.73e2,   5.54e2,   5.92e2,   6.18e2,   6.82e2,   7.46e2],
    'Kidneys':        [6.29e-1, 3.90e0,  2.41e0,  2.69e0,   5.17e0,   1.55e1,   9.43e1,   4.27e2,   6.24e2,   6.60e2,   6.86e2,   7.50e2,   8.18e2],
    'Pancreas':       [7.68e-1, 4.78e0,  2.98e0,  3.31e0,   6.28e0,   1.87e1,   1.10e2,   5.00e2,   7.20e2,   7.63e2,   7.92e2,   8.64e2,   9.43e2],
    'Spleen':         [7.29e-1, 4.55e0,  2.82e0,  3.14e0,   6.01e0,   1.79e1,   1.06e2,   4.89e2,   7.12e2,   7.55e2,   7.82e2,   8.51e2,   9.27e2],
    'Testes':         [4.38e-2, 2.71e-1, 1.65e-1, 1.84e-1,  3.55e-1,  1.07e0,   6.80e0,   3.64e1,   7.85e1,   9.71e1,   1.11e2,   1.47e2,   1.87e2],
    'Skin':           [7.81e-1, 4.83e0,  3.01e0,  3.36e0,   6.47e0,   1.95e1,   1.20e2,   5.91e2,   9.33e2,   1.00e3,   1.04e3,   1.12e3,   1.19e3],
    'Salivary glands':[5.08e-1, 3.14e0,  1.92e0,  2.16e0,   4.16e0,   1.25e1,   7.74e1,   4.52e2,   8.25e2,   9.11e2,   9.58e2,   1.05e3,   1.11e3],
    'Adrenals':       [7.17e-1, 4.46e0,  2.76e0,  3.07e0,   5.90e0,   1.76e1,   1.04e2,   4.74e2,   6.88e2,   7.28e2,   7.57e2,   8.26e2,   9.03e2],
}

# AF 体模 (成人女性)
ICRP116_ORGAN_DCC_AF = {
    'Brain':          [5.82e-2, 3.00e-1, 1.74e-1, 2.02e-1,  3.76e-1,  9.83e-1,  4.38e0,   5.40e1,   2.22e2,   2.90e2,   3.38e2,   4.45e2,   5.60e2],
    'Stomach wall':   [5.59e-1, 3.46e0,  2.13e0,  2.38e0,   4.59e0,   1.37e1,   8.38e1,   4.30e2,   7.04e2,   7.66e2,   8.06e2,   9.00e2,   1.01e3],
    'Colon wall':     [6.10e-1, 3.78e0,  2.32e0,  2.58e0,   4.93e0,   1.48e1,   9.07e1,   4.21e2,   6.04e2,   6.38e2,   6.67e2,   7.25e2,   7.96e2],
    'Liver':          [7.21e-1, 4.53e0,  2.81e0,  3.13e0,   6.00e0,   1.78e1,   1.05e2,   4.93e2,   7.30e2,   7.74e2,   8.02e2,   8.70e2,   9.49e2],
    'Lungs':          [1.32e0,  8.16e0,  5.11e0,  5.69e0,   1.07e1,   3.10e1,   1.73e2,   7.22e2,   9.82e2,   1.02e3,   1.05e3,   1.10e3,   1.16e3],
    'Oesophagus':     [7.23e-1, 4.52e0,  2.80e0,  3.10e0,   5.94e0,   1.75e1,   1.03e2,   4.72e2,   7.02e2,   7.55e2,   7.91e2,   8.73e2,   9.62e2],
    'Thyroid':        [6.18e-1, 3.86e0,  2.35e0,  2.65e0,   5.09e0,   1.52e1,   9.40e1,   5.03e2,   8.59e2,   9.42e2,   9.87e2,   1.09e3,   1.15e3],
    'Bladder wall':   [5.36e-1, 3.29e0,  2.04e0,  2.27e0,   4.38e0,   1.31e1,   8.09e1,   3.65e2,   5.42e2,   5.80e2,   6.06e2,   6.69e2,   7.34e2],
    'Kidneys':        [6.16e-1, 3.82e0,  2.36e0,  2.63e0,   5.06e0,   1.52e1,   9.25e1,   4.18e2,   6.12e2,   6.48e2,   6.74e2,   7.37e2,   8.05e2],
    'Breasts':        [1.43e0,  8.89e0,  5.57e0,  6.19e0,   1.16e1,   3.37e1,   1.88e2,   8.14e2,   1.20e3,   1.27e3,   1.31e3,   1.39e3,   1.45e3],
    'Ovaries':        [6.85e-1, 4.25e0,  2.63e0,  2.93e0,   5.62e0,   1.68e1,   1.02e2,   4.51e2,   6.35e2,   6.68e2,   6.93e2,   7.54e2,   8.27e2],
    'Uterus':         [5.76e-1, 3.56e0,  2.20e0,  2.45e0,   4.72e0,   1.41e1,   8.65e1,   3.82e2,   5.50e2,   5.83e2,   6.07e2,   6.67e2,   7.34e2],
    'Skin':           [7.64e-1, 4.73e0,  2.94e0,  3.28e0,   6.33e0,   1.91e1,   1.17e2,   5.79e2,   9.17e2,   9.83e2,   1.02e3,   1.10e3,   1.17e3],
    'Salivary glands':[4.97e-1, 3.07e0,  1.88e0,  2.11e0,   4.07e0,   1.22e1,   7.57e1,   4.43e2,   8.10e2,   8.96e2,   9.43e2,   1.03e3,   1.10e3],
    'Adrenals':       [7.02e-1, 4.37e0,  2.70e0,  3.00e0,   5.77e0,   1.72e1,   1.02e2,   4.65e2,   6.76e2,   7.15e2,   7.44e2,   8.13e2,   8.90e2],
}

# ICRP 103 组织权重因子（用于从 HT 计算 E）
ICRP103_WT = {
    'Gonads':          0.08,
    'Red bone marrow': 0.12,
    'Colon':           0.12,
    'Lungs':           0.12,
    'Stomach':         0.12,
    'Breasts':         0.12,
    'Bladder':         0.04,
    'Liver':           0.04,
    'Oesophagus':      0.04,
    'Thyroid':         0.04,
    'Bone surface':    0.01,
    'Brain':           0.01,
    'Salivary glands': 0.01,
    'Skin':            0.01,
    'Remainder':       0.12,  # 13 个余量组织等权重共享
}

# 器官名 → ICRP103 权重因子映射（对应 organ_dcc 中的键名）
ORGAN_TO_WT_AM = {
    'Lungs':           0.12,
    'Stomach wall':    0.12,
    'Colon wall':      0.12,
    'Liver':           0.04,
    'Oesophagus':      0.04,
    'Thyroid':         0.04,
    'Bladder wall':    0.04,
    'Brain':           0.01,
    'Salivary glands': 0.01,
    'Skin':            0.01,
    'Testes':          0.08,  # 性腺
    # Remainder 组器官（各取 0.12/13 ≈ 0.00923）
    'Kidneys':         0.12 / 13,
    'Pancreas':        0.12 / 13,
    'Spleen':          0.12 / 13,
    'Adrenals':        0.12 / 13,
}

ORGAN_TO_WT_AF = {
    'Lungs':           0.12,
    'Stomach wall':    0.12,
    'Colon wall':      0.12,
    'Liver':           0.04,
    'Oesophagus':      0.04,
    'Thyroid':         0.04,
    'Bladder wall':    0.04,
    'Brain':           0.01,
    'Salivary glands': 0.01,
    'Skin':            0.01,
    'Breasts':         0.12,
    'Ovaries':         0.08,  # 性腺
    # Remainder 组
    'Kidneys':         0.12 / 13,
    'Uterus':          0.12 / 13,
    'Adrenals':        0.12 / 13,
}


def get_icrp116_reference(phantom_type='AM'):
    """
    返回 ICRP 116 中子 AP 参考数据字典

    Returns
    -------
    dict with keys:
        'energies_MeV'  : np.ndarray, 能量点列表
        'effective_dose': np.ndarray, E/Φ (pSv·cm²)
        'organ_dcc'     : dict, {器官: np.ndarray}
        'organ_wt'      : dict, {器官: wT}
    """
    phantom_type = phantom_type.upper()
    eff_data = np.array(ICRP116_NEUTRON_AP_EFFECTIVE_DOSE)
    organ_dcc = ICRP116_ORGAN_DCC_AM if phantom_type == 'AM' else ICRP116_ORGAN_DCC_AF
    organ_wt  = ORGAN_TO_WT_AM       if phantom_type == 'AM' else ORGAN_TO_WT_AF
    return {
        'energies_MeV':   eff_data[:, 0],
        'effective_dose': eff_data[:, 1],
        'organ_dcc_energies_MeV': np.array(ICRP116_ORGAN_DCC_ENERGIES_MEV),
        'organ_dcc':      {k: np.array(v) for k, v in organ_dcc.items()},
        'organ_wt':       organ_wt,
    }


def compare_with_mcnp(mcnp_results: dict, phantom_type: str = 'AM',
                      energy_MeV: float = 2.53e-8):
    """
    将 MCNP 计算的器官当量剂量转换系数与 ICRP 116 参考值对比

    Parameters
    ----------
    mcnp_results : dict
        格式: {器官名: HT_per_fluence (pSv·cm²)}, 来自 MCNP F4 通量 tally
    phantom_type : str
        'AM' 或 'AF'
    energy_MeV : float
        中子能量 (MeV)，用于在 ICRP 116 数据中插值

    Returns
    -------
    dict  对比结果
    """
    ref = get_icrp116_reference(phantom_type)
    organ_energies = ref['organ_dcc_energies_MeV']
    comparison = {}

    for organ, calc_dcc in mcnp_results.items():
        if organ not in ref['organ_dcc']:
            continue
        ref_dcc_arr = ref['organ_dcc'][organ]
        # 对数插值
        log_e = np.log10(organ_energies)
        log_target = np.log10(max(energy_MeV, 1e-12))
        log_ref = np.interp(log_target, log_e, np.log10(np.maximum(ref_dcc_arr, 1e-12)))
        ref_dcc = 10 ** log_ref

        deviation = (calc_dcc - ref_dcc) / ref_dcc * 100.0 if ref_dcc > 0 else None
        comparison[organ] = {
            'calculated_pSv_cm2': round(calc_dcc, 4),
            'icrp116_ref_pSv_cm2': round(ref_dcc, 4),
            'deviation_pct': round(deviation, 1) if deviation is not None else None,
            'wT': ref['organ_wt'].get(organ, None),
        }
    return comparison


def plot_effective_dose_curve(phantom_type: str = 'AM',
                              mcnp_dcc_points: list = None,
                              output_path: str = None):
    """
    绘制有效剂量转换系数曲线（ICRP 116 参考值 vs 计算值）

    Parameters
    ----------
    phantom_type : str
        'AM' 或 'AF'
    mcnp_dcc_points : list of (energy_MeV, E_pSv_cm2), optional
        MCNP 计算的 E/Φ 数据点
    output_path : str
        图表保存路径
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    ref = get_icrp116_reference(phantom_type)
    energies = ref['energies_MeV']
    eff_dose = ref['effective_dose']

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle(
        f'ICRP 116 Neutron Dose Conversion Coefficients — AP Geometry\n'
        f'ICRP 110 {phantom_type} Reference Phantom',
        fontsize=12, fontweight='bold'
    )

    # ── 左图：有效剂量 E/Φ 曲线 ──────────────────────────────
    ax = axes[0]
    ax.loglog(energies * 1e6, eff_dose, 'b-o', markersize=4,
              label='ICRP 116 Reference (AP)', linewidth=1.5)

    if mcnp_dcc_points:
        mc_e = np.array([p[0] for p in mcnp_dcc_points])
        mc_d = np.array([p[1] for p in mcnp_dcc_points])
        ax.loglog(mc_e * 1e6, mc_d, 'r^', markersize=8,
                  label='MCNP Calculated', zorder=5)

    # 标记 BNCT 相关能量区域
    ax.axvspan(1e-3, 5e-2,  alpha=0.08, color='green',  label='Thermal region (<0.5 eV)')
    ax.axvspan(5e-2, 1e4,   alpha=0.08, color='orange', label='Epithermal (0.5 eV–10 keV)')
    ax.axvspan(1e4,  2e7,   alpha=0.08, color='red',    label='Fast (>10 keV)')

    ax.set_xlabel('Neutron Energy (eV)', fontsize=11)
    ax.set_ylabel('E/Φ  (pSv·cm²)', fontsize=11)
    ax.set_title('Effective Dose Conversion Coefficient', fontsize=10)
    ax.legend(fontsize=8, loc='upper left')
    ax.grid(True, which='both', alpha=0.3)
    ax.set_xlim(1e-3, 1e8)

    # ── 右图：选定能量点下各器官 HT/Φ 比较 ──────────────────
    ax2 = axes[1]
    organ_dcc = ref['organ_dcc']
    # 以 BNCT 最关键的 3 个能量点展示
    plot_energies_MeV = [2.53e-8, 1e-5, 1e-2]  # 热中子, 10eV, 10keV
    plot_labels       = ['Thermal (25.3 meV)', '10 eV', '10 keV']
    colors = ['#2196F3', '#FF9800', '#F44336']
    organ_names = list(organ_dcc.keys())

    x = np.arange(len(organ_names))
    width = 0.25
    organ_energies = ref['organ_dcc_energies_MeV']
    log_e = np.log10(organ_energies)

    for i, (e_MeV, label, color) in enumerate(zip(plot_energies_MeV, plot_labels, colors)):
        dcc_vals = []
        for organ in organ_names:
            arr = organ_dcc[organ]
            log_target = np.log10(max(e_MeV, 1e-12))
            log_val = np.interp(log_target, log_e, np.log10(np.maximum(arr, 1e-12)))
            dcc_vals.append(10 ** log_val)
        ax2.bar(x + (i - 1) * width, dcc_vals, width, label=label, color=color, alpha=0.8)

    ax2.set_xlabel('Organ', fontsize=10)
    ax2.set_ylabel('HT/Φ  (pSv·cm²)', fontsize=10)
    ax2.set_title('Organ Equivalent Dose DCC at Key BNCT Energies\n(ICRP 116 AP Reference)', fontsize=9)
    ax2.set_xticks(x)
    ax2.set_xticklabels([o.replace(' wall', '').replace(' (with blood)', '')
                         for o in organ_names], rotation=40, ha='right', fontsize=8)
    ax2.legend(fontsize=8)
    ax2.set_yscale('log')
    ax2.grid(axis='y', alpha=0.3, which='both')

    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"[ICRP116] 图表已保存: {output_path}")
    else:
        plt.show()
    plt.close()


def plot_organ_comparison(comparison: dict, phantom_type: str,
                          energy_MeV: float, output_path: str = None):
    """
    绘制 MCNP 计算值 vs ICRP 116 参考值的器官剂量对比柱状图
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib as mpl
    mpl.rcParams['axes.unicode_minus'] = False

    organs = list(comparison.keys())
    if not organs:
        print("[ICRP116] 无可对比数据，跳过图表生成")
        return

    calc_vals = [comparison[o]['calculated_pSv_cm2'] for o in organs]
    ref_vals  = [comparison[o]['icrp116_ref_pSv_cm2'] for o in organs]
    devs      = [comparison[o]['deviation_pct'] for o in organs]

    x = np.arange(len(organs))
    width = 0.35

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10),
                                   gridspec_kw={'height_ratios': [3, 1]})
    e_eV = energy_MeV * 1e6
    if e_eV < 1:
        e_label = f'{e_eV*1e3:.1f} meV'
    elif e_eV < 1e3:
        e_label = f'{e_eV:.2f} eV'
    elif e_eV < 1e6:
        e_label = f'{e_eV/1e3:.2f} keV'
    else:
        e_label = f'{energy_MeV:.2f} MeV'

    fig.suptitle(
        f'ICRP 116 vs MCNP: Organ Equivalent Dose Conversion Coefficients\n'
        f'{phantom_type} Phantom, AP Geometry, Neutron Energy = {e_label}',
        fontsize=12, fontweight='bold'
    )

    ax1.bar(x - width/2, ref_vals,  width, label='ICRP 116 Reference', color='#2196F3', alpha=0.85)
    ax1.bar(x + width/2, calc_vals, width, label='MCNP Calculated',     color='#FF5722', alpha=0.85)
    ax1.set_ylabel('HT/Φ  (pSv·cm²)', fontsize=10)
    ax1.set_xticks(x)
    ax1.set_xticklabels(organs, rotation=40, ha='right', fontsize=9)
    ax1.legend(fontsize=9)
    ax1.grid(axis='y', alpha=0.3)
    ax1.set_yscale('log')

    # 偏差条形图
    colors_dev = []
    for d in devs:
        if d is None:
            colors_dev.append('#9E9E9E')
        elif abs(d) <= 5:
            colors_dev.append('#4CAF50')
        elif abs(d) <= 15:
            colors_dev.append('#FF9800')
        else:
            colors_dev.append('#F44336')

    ax2.bar(x, [d if d is not None else 0 for d in devs], color=colors_dev, alpha=0.85)
    ax2.axhline(0,  color='black', linewidth=0.8)
    ax2.axhline(+5, color='green', linewidth=0.8, linestyle='--', alpha=0.6, label='±5%')
    ax2.axhline(-5, color='green', linewidth=0.8, linestyle='--', alpha=0.6)
    ax2.axhline(+15, color='orange', linewidth=0.8, linestyle=':', alpha=0.6, label='±15%')
    ax2.axhline(-15, color='orange', linewidth=0.8, linestyle=':', alpha=0.6)
    ax2.set_ylabel('Deviation (%)', fontsize=10)
    ax2.set_xticks(x)
    ax2.set_xticklabels(organs, rotation=40, ha='right', fontsize=9)
    ax2.legend(fontsize=8, loc='upper right')
    ax2.grid(axis='y', alpha=0.3)
    ax2.set_ylim(-50, 50)

    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"[ICRP116] 对比图表已保存: {output_path}")
    else:
        plt.show()
    plt.close()


def print_comparison_table(comparison: dict, phantom_type: str, energy_MeV: float):
    """打印对比表格到标准输出"""
    e_eV = energy_MeV * 1e6
    if e_eV < 1:
        e_label = f'{e_eV*1e3:.2f} meV'
    elif e_eV < 1e3:
        e_label = f'{e_eV:.2f} eV'
    elif e_eV < 1e6:
        e_label = f'{e_eV/1e3:.2f} keV'
    else:
        e_label = f'{energy_MeV:.2f} MeV'

    print(f"\n{'='*70}")
    print(f"ICRP 116 vs MCNP 对比  |  {phantom_type} 体模  |  AP 几何  |  E = {e_label}")
    print(f"{'='*70}")
    print(f"{'器官':<22} {'ICRP116参考':>12} {'MCNP计算':>12} {'偏差%':>8}  {'wT':>6}")
    print(f"{'':22} {'(pSv·cm²)':>12} {'(pSv·cm²)':>12}")
    print(f"{'-'*70}")
    for organ, d in comparison.items():
        ref_v  = d['icrp116_ref_pSv_cm2']
        calc_v = d['calculated_pSv_cm2']
        dev    = d['deviation_pct']
        wt     = d['wT']
        dev_s  = f"{dev:+.1f}%" if dev is not None else "  N/A"
        wt_s   = f"{wt:.4f}"   if wt is not None  else "  -"
        # 颜色标记（ANSI）
        if dev is not None and abs(dev) <= 5:
            tag = 'OK'
        elif dev is not None and abs(dev) <= 15:
            tag = '△'
        else:
            tag = 'X' if dev is not None else '-'
        print(f"{organ:<22} {ref_v:>12.4f} {calc_v:>12.4f} {dev_s:>8}  {wt_s:>6}  {tag}")
    print(f"{'='*70}\n")


def run_demo(phantom_type: str = 'AM', output_dir: str = '.'):
    """
    演示模式：使用 ICRP 116 参考数据生成曲线图（无需 MCNP 结果）
    同时用 ±10% 随机扰动的参考值模拟 MCNP 结果，展示对比流程
    """
    import os
    os.makedirs(output_dir, exist_ok=True)

    print(f"[ICRP116演示] 生成 {phantom_type} 体模 AP 几何有效剂量曲线图...")

    # 1) 有效剂量曲线（含 BNCT 能量区域标注）
    eff_chart = os.path.join(output_dir, f'icrp116_{phantom_type}_effective_dose_AP.png')
    plot_effective_dose_curve(phantom_type=phantom_type, output_path=eff_chart)

    # 2) 演示性器官对比（用参考值 ±15% 随机扰动模拟 MCNP 输出）
    demo_energy = 2.53e-8  # 热中子
    ref = get_icrp116_reference(phantom_type)
    organ_dcc = ref['organ_dcc']
    organ_energies = ref['organ_dcc_energies_MeV']
    log_e = np.log10(organ_energies)
    log_target = np.log10(demo_energy)

    np.random.seed(42)
    fake_mcnp = {}
    for organ, arr in organ_dcc.items():
        log_val = np.interp(log_target, log_e, np.log10(np.maximum(arr, 1e-12)))
        base = 10 ** log_val
        # 模拟 ±15% 以内的计算偏差
        fake_mcnp[organ] = round(base * (1 + np.random.uniform(-0.15, 0.15)), 4)

    comparison = compare_with_mcnp(fake_mcnp, phantom_type, demo_energy)
    print_comparison_table(comparison, phantom_type, demo_energy)

    organ_chart = os.path.join(output_dir, f'icrp116_{phantom_type}_organ_comparison_AP.png')
    plot_organ_comparison(comparison, phantom_type, demo_energy, output_path=organ_chart)

    # 3) 输出 JSON
    json_path = os.path.join(output_dir, f'icrp116_{phantom_type}_comparison.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'phantom_type': phantom_type,
            'geometry': 'AP',
            'radiation': 'neutron',
            'demo_energy_MeV': demo_energy,
            'note': '演示数据：MCNP结果为ICRP116参考值±15%随机扰动，仅用于展示对比流程',
            'effective_dose_dcc': {
                'energies_MeV': ref['energies_MeV'].tolist(),
                'E_over_Phi_pSv_cm2': ref['effective_dose'].tolist(),
                'source': 'ICRP Publication 116 (2010), Table A.3, AP geometry',
            },
            'organ_comparison': comparison
        }, f, ensure_ascii=False, indent=2)
    print(f"[ICRP116演示] JSON 结果已保存: {json_path}")

    return {
        'effective_dose_chart': eff_chart,
        'organ_comparison_chart': organ_chart,
        'json_results': json_path,
    }


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='ICRP 116 中子 AP 剂量转换系数对比分析',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 演示模式（仅生成图表，无需 MCNP 数据）
  python icrp116_neutron_comparison.py --phantom AM --output-dir ./results

  # 提供 MCNP 结果 JSON 进行真实对比（格式: {"Brain": 0.05, "Liver": 0.7, ...}，单位 pSv·cm²）
  python icrp116_neutron_comparison.py --phantom AM --mcnp-json mcnp_results.json \\
      --energy 2.53e-8 --output-dir ./results
        """
    )
    parser.add_argument('--phantom', choices=['AM', 'AF'], default='AM',
                        help='ICRP-110 体模类型 (AM=成人男, AF=成人女)')
    parser.add_argument('--mcnp-json', default=None,
                        help='MCNP 器官 HT/Φ 结果 JSON 文件路径')
    parser.add_argument('--energy', type=float, default=2.53e-8,
                        help='中子能量 (MeV)，默认 2.53e-8 (热中子)')
    parser.add_argument('--output-dir', default='.',
                        help='输出目录')
    parser.add_argument('--chart-prefix', default=None,
                        help='图表文件名前缀（可选）')
    args = parser.parse_args()

    import os
    os.makedirs(args.output_dir, exist_ok=True)
    prefix = args.chart_prefix or f'icrp116_{args.phantom}'

    if args.mcnp_json:
        # 真实对比模式
        with open(args.mcnp_json, 'r', encoding='utf-8') as f:
            mcnp_results = json.load(f)
        comparison = compare_with_mcnp(mcnp_results, args.phantom, args.energy)
        print_comparison_table(comparison, args.phantom, args.energy)

        eff_chart   = os.path.join(args.output_dir, f'{prefix}_effective_dose_AP.png')
        organ_chart = os.path.join(args.output_dir, f'{prefix}_organ_comparison_AP.png')
        json_out    = os.path.join(args.output_dir, f'{prefix}_comparison.json')

        plot_effective_dose_curve(args.phantom, output_path=eff_chart)
        plot_organ_comparison(comparison, args.phantom, args.energy, output_path=organ_chart)

        with open(json_out, 'w', encoding='utf-8') as f:
            json.dump({'phantom': args.phantom, 'energy_MeV': args.energy,
                       'comparison': comparison}, f, ensure_ascii=False, indent=2)
        print(f"[ICRP116] 结果已保存到: {args.output_dir}/")
    else:
        # 演示模式
        run_demo(phantom_type=args.phantom, output_dir=args.output_dir)
