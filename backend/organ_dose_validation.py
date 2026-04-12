#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐器官剂量转换系数对比分析
============================
分析顺序（按老师要求）:
  Step 1: 单体模 + 单辐照条件 + 逐器官  HT/Φ 对比
  Step 2: 有效剂量误差来源分解  ΔE = Σ wT·ΔHT

辐射类型: 中子, AP 几何
参考体模: ICRP 110  AM / AF
参考数据: ICRP Publication 116 (2010), Table A.3

用法:
  python organ_dose_validation.py --phantom AM --energy 1.0
  python organ_dose_validation.py --phantom AM --all-energies
  python organ_dose_validation.py --phantom AF --all-energies
"""

import argparse
import sys
import warnings
import numpy as np
from pathlib import Path

warnings.filterwarnings('ignore')

# ── 从已有模块导入数据和计算函数 ─────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from neutron_icrp_dose_comparison import (
    ORGAN_ENERGIES_MEV,
    ORGAN_HT_AM, ORGAN_HT_AF,
    ORGAN_WT_AM, ORGAN_WT_AF,
    NEUTRON_AP_E_OVER_PHI,
    calculate_organ_dcc_analytical,
    _interp_log,
)


# ── 代表性能量点（热中子 / 超热 / 快中子） ─────────────────────
KEY_ENERGIES = {
    '25.3 meV (thermal)': 2.53e-8,
    '10 keV (epithermal)': 1.00e-2,
    '1 MeV (fast)': 1.00e0,
}

# ── 有效剂量参考数组 ─────────────────────────────────────────────
_EFF_ARR = np.array(NEUTRON_AP_E_OVER_PHI)
_EFF_E   = _EFF_ARR[:, 0]
_EFF_D   = _EFF_ARR[:, 1]


def _interp_eff(e_mev: float) -> float:
    """在 ICRP116 有效剂量曲线上插值。"""
    return float(_interp_log(_EFF_E, _EFF_D, e_mev))


def single_condition_compare(phantom_type: str, energy_mev: float) -> dict:
    """
    单体模 + 单辐照条件 → 逐器官对比结果。

    返回字典包含：
      organs        : 器官名列表
      ref_HT        : ICRP116 参考 HT/Φ (pSv·cm²)
      calc_HT       : 解析计算 HT/Φ (pSv·cm²)
      dev_pct       : (calc-ref)/ref × 100 (%)
      wT            : 各器官 ICRP103 组织权重因子
      wT_ref        : wT × ref_HT (有效剂量贡献)
      wT_calc       : wT × calc_HT
      delta_wT_HT   : wT × (calc-ref) = 有效剂量误差贡献
      E_eff_ref     : Σ(wT × HT_ref)  — 由器官HT求和
      E_eff_calc    : Σ(wT × HT_calc) — 我们的模型
      E_icrp116     : ICRP116直接给出的 E/Φ (插值)
      dev_eff_pct   : (E_eff_calc - E_icrp116) / E_icrp116 × 100
    """
    pt = phantom_type.upper()
    organ_ht_ref = ORGAN_HT_AM if pt == 'AM' else ORGAN_HT_AF
    organ_wt     = ORGAN_WT_AM if pt == 'AM' else ORGAN_WT_AF
    calc_dcc     = calculate_organ_dcc_analytical(pt)

    organs, ref_HT, calc_HT, dev_pct = [], [], [], []
    wT_list, wT_ref, wT_calc, delta_list = [], [], [], []

    for organ in organ_ht_ref:
        ref_v  = _interp_log(ORGAN_ENERGIES_MEV,
                             np.array(organ_ht_ref[organ]), energy_mev)
        if organ in calc_dcc:
            calc_v = float(_interp_log(ORGAN_ENERGIES_MEV,
                                       calc_dcc[organ], energy_mev))
        else:
            calc_v = float('nan')

        wt = organ_wt.get(organ, 0.0)
        dev = (calc_v - ref_v) / ref_v * 100 if ref_v > 0 else float('nan')

        organs.append(organ)
        ref_HT.append(ref_v)
        calc_HT.append(calc_v)
        dev_pct.append(dev)
        wT_list.append(wt)
        wT_ref.append(wt * ref_v)
        wT_calc.append(wt * calc_v if not np.isnan(calc_v) else float('nan'))
        delta_list.append(wt * (calc_v - ref_v) if not np.isnan(calc_v) else float('nan'))

    E_eff_ref  = float(np.nansum(wT_ref))
    E_eff_calc = float(np.nansum(wT_calc))
    E_icrp116  = _interp_eff(energy_mev)
    dev_eff    = (E_eff_calc - E_icrp116) / E_icrp116 * 100 if E_icrp116 > 0 else float('nan')

    return {
        'phantom_type': pt,
        'energy_mev': energy_mev,
        'organs': organs,
        'ref_HT': ref_HT,
        'calc_HT': calc_HT,
        'dev_pct': dev_pct,
        'wT': wT_list,
        'wT_ref': wT_ref,
        'wT_calc': wT_calc,
        'delta_wT_HT': delta_list,
        'E_eff_ref': E_eff_ref,
        'E_eff_calc': E_eff_calc,
        'E_icrp116': E_icrp116,
        'dev_eff_pct': dev_eff,
    }


def print_single_condition_table(result: dict):
    """在终端打印单条件逐器官对比表（Step 1）。"""
    pt  = result['phantom_type']
    e   = result['energy_mev']
    e_eV = e * 1e6
    if e_eV < 1:
        e_str = f'{e_eV*1000:.2f} meV'
    elif e_eV < 1e3:
        e_str = f'{e_eV:.1f} eV'
    elif e_eV < 1e6:
        e_str = f'{e_eV/1e3:.1f} keV'
    else:
        e_str = f'{e:.1f} MeV'

    print(f'\n{"="*80}')
    print(f'  Step 1 逐器官对比  |  {pt} 体模  |  AP 中子  |  E = {e_str}')
    print(f'  参考: ICRP 116 Table A.3  |  计算: Kerma 解析模型 (ICRP110 成分 + ENDF 截面)')
    print(f'{"="*80}')
    hdr = f"{'器官':<22} {'wT':>6}  {'Ref HT/Φ':>12}  {'Calc HT/Φ':>12}  {'偏差%':>8}  {'|偏差|':>7}"
    print(hdr)
    print(f'{"-"*80}')

    for i, organ in enumerate(result['organs']):
        ref  = result['ref_HT'][i]
        calc = result['calc_HT'][i]
        dev  = result['dev_pct'][i]
        wt   = result['wT'][i]
        wt_s = f'{wt:.4f}'
        dev_s = f'{dev:+.1f}%' if not np.isnan(dev) else 'N/A'
        flag = '  ✓' if not np.isnan(dev) and abs(dev) <= 5 else \
               ' !!' if not np.isnan(dev) and abs(dev) > 20 else '   '
        print(f'{organ:<22} {wt_s:>6}  {ref:>12.4g}  {calc:>12.4g}  {dev_s:>8}{flag}')

    print(f'{"="*80}')
    print(f'\n  Step 2 有效剂量误差来源分解')
    print(f'{"="*80}')
    print(f'  E_eff (Σ wT·HT_ref)  = {result["E_eff_ref"]:10.4f} pSv·cm²')
    print(f'  E_eff (Σ wT·HT_calc) = {result["E_eff_calc"]:10.4f} pSv·cm²')
    print(f'  E/Φ  (ICRP116 直接)  = {result["E_icrp116"]:10.4f} pSv·cm²')
    print(f'  有效剂量总偏差       = {result["dev_eff_pct"]:+.2f}%'
          f'  {"← 5%内，合理" if abs(result["dev_eff_pct"]) <= 5 else "← 偏差较大"}')

    # 各器官对有效剂量误差的贡献排序
    deltas = [(result['organs'][i], result['delta_wT_HT'][i], result['wT'][i])
              for i in range(len(result['organs']))
              if not np.isnan(result['delta_wT_HT'][i])]
    deltas.sort(key=lambda x: abs(x[1]), reverse=True)
    print(f'\n  各器官对有效剂量误差的贡献 ΔE_organ = wT × (HT_calc - HT_ref):')
    print(f'  {"器官":<22} {"wT":>6}  {"ΔE贡献 (pSv·cm²)":>18}  {"占总误差%":>10}')
    print(f'  {"-"*65}')
    total_err = result['E_eff_calc'] - result['E_icrp116']
    for organ, delta, wt in deltas[:8]:
        frac = delta / total_err * 100 if abs(total_err) > 0 else float('nan')
        print(f'  {organ:<22} {wt:.4f}  {delta:>18.4f}  {frac:>+10.1f}%')
    print(f'{"="*80}\n')


def plot_single_condition(result: dict, output_path: str = None):
    """
    单条件逐器官对比图（Step 1 图）。

    上图: 各器官 HT/Φ  参考值（蓝）vs 计算值（红）
    中图: 各器官偏差 (%)，±5% 绿线，±20% 橙线
    下图: wT × HT 贡献 + 误差条（有效剂量误差来源，Step 2）
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    pt  = result['phantom_type']
    e   = result['energy_mev']
    e_eV = e * 1e6
    if e_eV < 1:
        e_label = f'{e_eV*1000:.2f} meV (thermal)'
    elif e_eV < 1e3:
        e_label = f'{e_eV:.0f} eV'
    elif e_eV < 1e6:
        e_label = f'{e_eV/1e3:.0f} keV (epithermal)'
    else:
        e_label = f'{e:.0f} MeV (fast)'

    organs   = result['organs']
    ref_HT   = np.array(result['ref_HT'])
    calc_HT  = np.array(result['calc_HT'])
    dev_pct  = np.array(result['dev_pct'])
    wT       = np.array(result['wT'])
    wT_ref   = np.array(result['wT_ref'])
    wT_calc  = np.array(result['wT_calc'])
    delta    = np.array(result['delta_wT_HT'])

    x = np.arange(len(organs))
    short = [o.replace(' wall','').replace(' marrow','\nmarrow')
              .replace(' glands','\nglands').replace(' surface','\nsurf.') for o in organs]

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 13),
                                         gridspec_kw={'height_ratios': [3, 2, 2]})
    fig.suptitle(
        f'Organ-by-Organ Dose Validation  |  {pt} Phantom, AP Neutron, E = {e_label}\n'
        f'Step 1: Per-Organ HT/Φ  →  Step 2: Effective Dose Error Sources',
        fontsize=12, fontweight='bold'
    )

    # ── 上图: HT/Φ 参考 vs 计算 ─────────────────────────────────
    w = 0.38
    ax1.bar(x - w/2, ref_HT,  w, label='ICRP 116 Ref. (Table A.3)',
            color='#1E88E5', alpha=0.85, edgecolor='white')
    ax1.bar(x + w/2, calc_HT, w, label='Calc. (Kerma model)',
            color='#E53935', alpha=0.85, edgecolor='white')
    ax1.set_yscale('log')
    ax1.set_xticks(x); ax1.set_xticklabels(short, rotation=40, ha='right', fontsize=8)
    ax1.set_ylabel('HT / Φ  (pSv·cm²)', fontsize=10)
    ax1.set_title('Step 1a: Per-Organ Equivalent Dose Conversion Coefficient', fontsize=10)
    ax1.legend(fontsize=9); ax1.grid(axis='y', alpha=0.2, which='both')

    # ── 中图: 偏差 (%) ──────────────────────────────────────────
    colors = ['#43A047' if abs(d) <= 5 else '#FB8C00' if abs(d) <= 20
              else '#E53935' for d in dev_pct]
    ax2.bar(x, dev_pct, color=colors, alpha=0.85, edgecolor='white', lw=0.3)
    ax2.axhline(0,   color='black', lw=1.0)
    ax2.axhline(+5,  color='#43A047', lw=1.2, ls='--', label='±5% (teacher threshold)')
    ax2.axhline(-5,  color='#43A047', lw=1.2, ls='--')
    ax2.axhline(+20, color='#FB8C00', lw=1.0, ls=':',  label='±20%')
    ax2.axhline(-20, color='#FB8C00', lw=1.0, ls=':')
    ax2.set_xticks(x); ax2.set_xticklabels(short, rotation=40, ha='right', fontsize=8)
    ax2.set_ylabel('Deviation  (%)', fontsize=10)
    ax2.set_title('Step 1b: Per-Organ Deviation from ICRP 116 Reference', fontsize=10)
    ax2.legend(fontsize=8, loc='upper right')
    ax2.grid(axis='y', alpha=0.2)
    # 标注数值
    for i, (xi, d) in enumerate(zip(x, dev_pct)):
        if not np.isnan(d):
            ax2.text(xi, d + (1 if d >= 0 else -2), f'{d:+.0f}%',
                     ha='center', va='bottom' if d >= 0 else 'top',
                     fontsize=6.5, color='#333')

    # ── 下图: Step 2 误差来源 ─────────────────────────────────
    ax3.bar(x - w/2, wT_ref,  w, label='wT × HT_ref  (ICRP116)',
            color='#1E88E5', alpha=0.7, edgecolor='white')
    ax3.bar(x + w/2, wT_calc, w, label='wT × HT_calc (model)',
            color='#E53935', alpha=0.7, edgecolor='white')
    # 误差贡献标注
    for i, (xi, d) in enumerate(zip(x, delta)):
        if not np.isnan(d) and abs(d) > 0.001 * abs(result['E_eff_ref'] or 1):
            ax3.annotate(f'{d:+.2f}', xy=(xi + w/2, wT_calc[i]),
                         xytext=(0, 4), textcoords='offset points',
                         ha='center', fontsize=6, color='#B71C1C')
    ax3.set_xticks(x); ax3.set_xticklabels(short, rotation=40, ha='right', fontsize=8)
    ax3.set_ylabel('wT × HT / Φ  (pSv·cm²)', fontsize=10)
    ax3.set_title(
        f'Step 2: Effective Dose Error Sources  |  '
        f'E_calc={result["E_eff_calc"]:.2f}  E_ICRP116={result["E_icrp116"]:.2f}  '
        f'Δ={result["dev_eff_pct"]:+.1f}%',
        fontsize=10
    )
    ax3.legend(fontsize=9); ax3.grid(axis='y', alpha=0.2)

    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f'  → 图表已保存: {output_path}')
    plt.close()


def run_systematic_analysis(phantom_type: str = 'AM', output_dir: str = '.'):
    """
    完整的系统化分析：
    对三个代表性能量点（热 / 超热 / 快中子），分别执行
    单体模 + 单辐照条件 + 逐器官对比，最后汇总有效剂量误差。
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    pt = phantom_type.upper()
    print(f'\n{"#"*72}')
    print(f'#  系统化器官剂量验证  |  {pt} 体模  |  AP 中子  |  ICRP 116')
    print(f'#  分析顺序: Step1 逐器官HT/Φ → Step2 有效剂量误差分解')
    print(f'{"#"*72}')

    summary_rows = []
    for label, e_mev in KEY_ENERGIES.items():
        print(f'\n>>> 条件: {label}  (E = {e_mev:.3e} MeV)')
        res = single_condition_compare(pt, e_mev)
        print_single_condition_table(res)

        safe_label = label.replace(' ', '_').replace('(', '').replace(')', '').replace('.', 'p')
        fig_path = str(out / f'organ_validation_{pt}_{safe_label}.png')
        plot_single_condition(res, fig_path)

        summary_rows.append({
            'energy': label,
            'E_eff_calc': res['E_eff_calc'],
            'E_icrp116': res['E_icrp116'],
            'dev_pct': res['dev_eff_pct'],
        })

    # 汇总表
    print(f'\n{"="*60}')
    print(f'  有效剂量验证汇总  |  {pt} 体模')
    print(f'{"="*60}')
    print(f'  {"条件":<30} {"计算值":>10}  {"参考值":>10}  {"偏差":>8}')
    print(f'  {"-"*58}')
    for row in summary_rows:
        flag = '✓' if abs(row['dev_pct']) <= 5 else '!'
        print(f'  {row["energy"]:<30} {row["E_eff_calc"]:>10.3f}  '
              f'{row["E_icrp116"]:>10.3f}  {row["dev_pct"]:>+7.1f}% {flag}')
    print(f'{"="*60}')
    print(f'  注: 5% 以内为合理范围（老师阈值）\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='逐器官剂量验证 — 单体模 + 单辐照条件 + 单器官'
    )
    parser.add_argument('--phantom', choices=['AM', 'AF', 'both'], default='AM')
    parser.add_argument('--energy', type=float, default=None,
                        help='单能量点 (MeV)，不填则跑三个代表点')
    parser.add_argument('--all-energies', action='store_true',
                        help='跑全部三个代表性能量点')
    parser.add_argument('--output-dir', default='./organ_validation_results')
    args = parser.parse_args()

    phantoms = ['AM', 'AF'] if args.phantom == 'both' else [args.phantom.upper()]

    for pt in phantoms:
        if args.energy is not None:
            res = single_condition_compare(pt, args.energy)
            print_single_condition_table(res)
            fig_path = str(Path(args.output_dir) /
                           f'organ_validation_{pt}_{args.energy:.3e}MeV.png')
            Path(args.output_dir).mkdir(parents=True, exist_ok=True)
            plot_single_condition(res, fig_path)
        else:
            run_systematic_analysis(pt, args.output_dir)
