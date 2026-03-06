#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ICRP-110 标准体模 vs ICRP参考数据 对比分析

用ICRP-110参考体模（标准模型）计算器官质量，
与ICRP Publication 110 Table A.1中发布的参考值进行对比验证。

Author: BNCT Team
"""

import os
import sys
import json
import re
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# ICRP-110 Table A.1 发布的参考器官质量 (单位: g)
# 来源: ICRP Publication 110, Table A.1 (AM) and Table A.2 (AF)
# ============================================================

ICRP_REFERENCE_MASSES = {
    'AM': {  # Adult Male 成人男性参考值
        'Adrenals':            14.0,
        'Brain':             1450.0,
        'Breasts':             25.0,
        'Colon wall':         370.0,
        'Oesophagus':          40.0,
        'Eye lenses':           0.44,
        'Gallbladder wall':     8.0,
        'Heart muscle':       330.0,
        'Kidneys':            310.0,
        'Liver':             1800.0,
        'Lungs (with blood)': 1200.0,
        'Oesophagus':          40.0,
        'Pancreas':           140.0,
        'Prostate':            17.0,
        'Salivary glands':     85.0,
        'Skin':              3300.0,
        'Spinal cord':         30.0,
        'Spleen':             150.0,
        'Stomach wall':       150.0,
        'Testes':              35.0,
        'Thymus':              25.0,
        'Thyroid':             20.0,
        'Urinary bladder wall': 50.0,
    },
    'AF': {  # Adult Female 成人女性参考值
        'Adrenals':            13.0,
        'Brain':             1300.0,
        'Breasts':            500.0,
        'Colon wall':         310.0,
        'Oesophagus':          35.0,
        'Eye lenses':           0.36,
        'Gallbladder wall':     6.0,
        'Heart muscle':       250.0,
        'Kidneys':            275.0,
        'Liver':             1400.0,
        'Lungs (with blood)':  950.0,
        'Ovaries':             11.0,
        'Pancreas':           120.0,
        'Salivary glands':     70.0,
        'Skin':              2300.0,
        'Spinal cord':         25.0,
        'Spleen':             130.0,
        'Stomach wall':       140.0,
        'Thymus':              20.0,
        'Thyroid':             17.0,
        'Uterus':              80.0,
        'Urinary bladder wall': 40.0,
    }
}

# ============================================================
# 器官分组定义: 将多个organ ID合并为一个解剖结构
# 格式: {解剖名称: [organ_id, ...], ...}
# 适用于AM体模 (根据AM_organs.dat的ID)
# ============================================================

ORGAN_GROUPS_AM = {
    'Adrenals':             [1, 2],
    'Brain':                [61],
    'Breasts':              [62, 63, 64, 65],
    'Colon wall':           [76, 78, 80, 82, 84, 86],
    'Oesophagus':           [110],
    'Eye lenses':           [66, 68],
    'Gallbladder wall':     [70],
    'Heart muscle':         [87],
    'Kidneys':              [89, 90, 91, 92, 93, 94],
    'Liver':                [95],
    'Lungs (with blood)':   [96, 97, 98, 99],
    'Pancreas':             [113],
    'Prostate':             [115],
    'Salivary glands':      [120, 121],
    'Skin':                 [122, 123, 124, 125],
    'Spinal cord':          [126],
    'Spleen':               [127],
    'Stomach wall':         [72],
    'Testes':               [129, 130],
    'Thymus':               [131],
    'Thyroid':              [132],
    'Urinary bladder wall': [137],
}

ORGAN_GROUPS_AF = {
    'Adrenals':             [1, 2],
    'Brain':                [61],
    'Breasts':              [62, 63, 64, 65],
    'Colon wall':           [76, 78, 80, 82, 84, 86],
    'Oesophagus':           [110],
    'Eye lenses':           [66, 68],
    'Gallbladder wall':     [70],
    'Heart muscle':         [87],
    'Kidneys':              [89, 90, 91, 92, 93, 94],
    'Liver':                [95],
    'Lungs (with blood)':   [96, 97, 98, 99],
    'Ovaries':              [111, 112],
    'Pancreas':             [113],
    'Salivary glands':      [120, 121],
    'Skin':                 [122, 123, 124, 125],
    'Spinal cord':          [126],
    'Spleen':               [127],
    'Stomach wall':         [72],
    'Thymus':               [131],
    'Thyroid':              [132],
    'Uterus':               [139],
    'Urinary bladder wall': [137],
}

# 体模物理参数
PHANTOM_DIMS = {
    'AM': {
        'columns': 254, 'rows': 127, 'slices': 222,
        'voxel_size': (2.137, 2.137, 8.0),  # mm
        'height_cm': 176, 'mass_kg': 73
    },
    'AF': {
        'columns': 299, 'rows': 137, 'slices': 348,
        'voxel_size': (1.775, 1.775, 4.84),  # mm
        'height_cm': 163, 'mass_kg': 60
    }
}


def parse_organs_dat(filepath):
    """解析organ.dat文件，返回 {organ_id: (tissue_num, density, name)}"""
    organs = {}
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    for line in lines:
        line = line.strip('\r\n')
        m = re.match(r'^\s*(\d+)\s+(.+?)\s{2,}(\d+)\s+([\d.]+)\s*$', line)
        if m:
            organ_id = int(m.group(1))
            organ_name = m.group(2).strip()
            tissue_num = int(m.group(3))
            density = float(m.group(4))
            organs[organ_id] = (tissue_num, density, organ_name)
    return organs


def load_voxel_data(dat_file, dims):
    """从文本格式的.dat文件加载体素数据"""
    ncol = dims['columns']
    nrow = dims['rows']
    nsli = dims['slices']

    voxel_data = np.zeros((ncol, nrow, nsli), dtype=np.int16)

    with open(dat_file, 'r') as f:
        all_numbers = []
        for line in f:
            numbers = [int(x) for x in line.split()]
            all_numbers.extend(numbers)

    idx = 0
    for nsl in range(nsli):
        for nr in range(nrow):
            for nc in range(ncol):
                if idx < len(all_numbers):
                    voxel_data[nc, nr, nsl] = all_numbers[idx]
                    idx += 1

    return voxel_data


def compute_organ_mass(voxel_data, organ_ids, density_map, voxel_volume_cm3):
    """计算一组器官ID对应的总质量 (g)"""
    total_mass = 0.0
    for oid in organ_ids:
        count = int(np.sum(voxel_data == oid))
        density = density_map.get(oid, 1.0)  # g/cm³
        total_mass += count * voxel_volume_cm3 * density
    return total_mass


def run_comparison(phantom_type, data_dir, output_chart_path=None):
    """
    主对比函数：加载体模数据，计算器官质量，与ICRP参考值对比

    Parameters
    ----------
    phantom_type : str
        'AM' 或 'AF'
    data_dir : str
        包含 {phantom_type}/ 子目录的根目录
    output_chart_path : str, optional
        输出图表路径 (.png)

    Returns
    -------
    dict
        对比结果
    """
    phantom_type = phantom_type.upper()
    dims = PHANTOM_DIMS[phantom_type]

    # 定位数据文件
    phantom_dir = Path(data_dir) / phantom_type / phantom_type
    if not phantom_dir.exists():
        # 尝试另一种路径结构
        phantom_dir = Path(data_dir) / phantom_type
        if not phantom_dir.exists():
            raise FileNotFoundError(f"找不到体模数据目录: {phantom_dir}")

    organs_file = phantom_dir / f"{phantom_type}_organs.dat"
    dat_file = phantom_dir / f"{phantom_type}.dat"

    if not organs_file.exists():
        raise FileNotFoundError(f"找不到器官定义文件: {organs_file}")
    if not dat_file.exists():
        raise FileNotFoundError(f"找不到体素数据文件: {dat_file}")

    print(f"[ICRP对比] 加载 {phantom_type} 体模器官定义...", flush=True)
    organs = parse_organs_dat(str(organs_file))
    density_map = {oid: d for oid, (_, d, _) in organs.items()}

    print(f"[ICRP对比] 加载体素数据 ({dims['columns']}×{dims['rows']}×{dims['slices']})...", flush=True)
    voxel_data = load_voxel_data(str(dat_file), dims)

    # 体素体积 (mm³ → cm³)
    voxel_vol_cm3 = (dims['voxel_size'][0] * dims['voxel_size'][1] * dims['voxel_size'][2]) / 1000.0

    print(f"[ICRP对比] 计算器官质量...", flush=True)
    organ_groups = ORGAN_GROUPS_AM if phantom_type == 'AM' else ORGAN_GROUPS_AF
    reference_masses = ICRP_REFERENCE_MASSES[phantom_type]

    results = []
    for organ_name, organ_ids in organ_groups.items():
        calc_mass = compute_organ_mass(voxel_data, organ_ids, density_map, voxel_vol_cm3)
        ref_mass = reference_masses.get(organ_name, None)

        if ref_mass is not None and ref_mass > 0 and calc_mass > 0:
            deviation_pct = (calc_mass - ref_mass) / ref_mass * 100.0
        else:
            deviation_pct = None

        results.append({
            'organ': organ_name,
            'calculated_g': round(calc_mass, 2),
            'reference_g': ref_mass,
            'deviation_pct': round(deviation_pct, 1) if deviation_pct is not None else None,
        })

    # 排序：按参考质量降序
    results.sort(key=lambda x: x['reference_g'] if x['reference_g'] else 0, reverse=True)

    # 总体质量
    total_calc = float(np.sum(voxel_data > 0)) * voxel_vol_cm3 * 1.0  # 粗略估计
    ref_total_kg = dims['mass_kg']

    summary = {
        'phantom_type': phantom_type,
        'phantom_height_cm': dims['height_cm'],
        'phantom_mass_kg': dims['mass_kg'],
        'voxel_size_mm': dims['voxel_size'],
        'voxel_volume_cm3': round(voxel_vol_cm3, 6),
        'total_voxels': int(np.prod([dims['columns'], dims['rows'], dims['slices']])),
        'nonzero_voxels': int(np.count_nonzero(voxel_data)),
        'organs_compared': len(results),
        'organ_results': results,
    }

    # 生成对比图表
    if output_chart_path:
        try:
            _generate_chart(results, phantom_type, output_chart_path)
            summary['chart_path'] = output_chart_path
        except Exception as e:
            summary['chart_error'] = str(e)

    print(f"[ICRP对比] 完成，对比了 {len(results)} 个器官", flush=True)
    return summary


def _generate_chart(results, phantom_type, output_path):
    """生成对比条形图"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    # 过滤有效数据（两者都大于0）
    valid = [r for r in results if r['reference_g'] and r['reference_g'] > 0 and r['calculated_g'] > 0]

    # 分两组：大质量器官 和 小质量器官（阈值100g）
    large_organs = [r for r in valid if r['reference_g'] >= 100]
    small_organs = [r for r in valid if r['reference_g'] < 100]

    fig, axes = plt.subplots(1, 2, figsize=(16, 8))
    fig.suptitle(f'ICRP-110 {phantom_type} 标准体模 器官质量对比\n(计算值 vs ICRP Publication 110 参考值)',
                 fontsize=13, fontweight='bold')

    for ax, organ_list, title in [
        (axes[0], large_organs, '主要器官 (≥100 g)'),
        (axes[1], small_organs, '小器官 (<100 g)')
    ]:
        if not organ_list:
            ax.set_visible(False)
            continue

        names = [r['organ'] for r in organ_list]
        calc_vals = [r['calculated_g'] for r in organ_list]
        ref_vals = [r['reference_g'] for r in organ_list]

        x = np.arange(len(names))
        width = 0.35

        bars1 = ax.bar(x - width/2, ref_vals, width, label='ICRP参考值', color='#2196F3', alpha=0.85)
        bars2 = ax.bar(x + width/2, calc_vals, width, label='体模计算值', color='#FF5722', alpha=0.85)

        ax.set_xlabel('器官', fontsize=10)
        ax.set_ylabel('质量 (g)', fontsize=10)
        ax.set_title(title, fontsize=11)
        ax.set_xticks(x)
        ax.set_xticklabels(names, rotation=40, ha='right', fontsize=8)
        ax.legend(fontsize=9)
        ax.grid(axis='y', alpha=0.3)

        # 在每组bars旁标注偏差%
        for bar1, bar2, r in zip(bars1, bars2, organ_list):
            if r['deviation_pct'] is not None:
                color = '#4CAF50' if abs(r['deviation_pct']) <= 5 else (
                    '#FF9800' if abs(r['deviation_pct']) <= 15 else '#F44336')
                ax.text(bar2.get_x() + bar2.get_width()/2,
                        bar2.get_height() + max(ref_vals) * 0.01,
                        f"{r['deviation_pct']:+.1f}%",
                        ha='center', va='bottom', fontsize=7, color=color, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='ICRP-110 标准体模 vs 参考值对比')
    parser.add_argument('--phantom', choices=['AM', 'AF'], default='AM',
                        help='体模类型 (AM=成人男性, AF=成人女性)')
    parser.add_argument('--data-dir', required=True,
                        help='ICRP-110数据根目录 (包含AM/或AF/子目录)')
    parser.add_argument('--chart', default=None,
                        help='输出图表路径 (.png)')
    parser.add_argument('--json-output', default=None,
                        help='输出JSON结果路径')
    args = parser.parse_args()

    result = run_comparison(
        phantom_type=args.phantom,
        data_dir=args.data_dir,
        output_chart_path=args.chart
    )

    if args.json_output:
        with open(args.json_output, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"结果已保存到: {args.json_output}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
