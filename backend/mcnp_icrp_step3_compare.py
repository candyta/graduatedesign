#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
MCNP ICRP-110 验证 — Step 3：提取器官剂量系数并与 ICRP-116 Table A.3 对比
===========================================================================

【物理原理】
  MCNP5 FMESH14 输出：每源粒子光子注量 Φ_T  (cm⁻² / source particle)
  AP 平行束，源面积 A_src = 2·Px × 2·Pz cm²，NPS = 1e7

  器官剂量系数（ICRP-116 约定）:
      h_T  (pGy·cm²) = Φ̄_T × A_src × E_MeV × (μ_en/ρ)_T × 160.2

  其中 160.2 = 1.602×10⁻¹³ J/MeV × 1000 g/kg × 10¹² pGy/Gy

【参考值来源】
  ICRP Publication 116 (2010), Table A.3
  AP 几何，成人男性 (AM)，光子，h_T (pGy·cm²)

【μ_en/ρ 来源】
  NIST XCOM，ICRU-44 软组织 (H 10.1%, C 11.1%, N 2.6%, O 76.2%)
  肺组织与软组织质量系数相近，骨低能时差异大（Z_eff 高）

【运行方法】
  python mcnp_icrp_step3_compare.py
  python mcnp_icrp_step3_compare.py \
      --out-dir  icrp_validation/mcnp_outputs \
      --mask     icrp_validation/organ_mask_127x63x111.npy \
      --meta     icrp_validation/organ_mask_meta.json \
      --chart    icrp_validation/mcnp_outputs/icrp116_comparison.png \
      --json-out icrp_validation/mcnp_outputs/icrp116_comparison.json

【输出】
  icrp116_comparison.png   — 4 能量点 × 器官剂量系数对比图
  icrp116_comparison.json  — 完整数值结果
  控制台打印偏差表
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# ═══════════════════════════════════════════════════════════════════════════
# 体模物理参数（与 Step1/Step2 保持一致）
# ═══════════════════════════════════════════════════════════════════════════
DS_SHAPE  = (127, 63, 111)          # (nx, ny, nz)
DS_VOX_CM = (0.4274, 0.4308, 1.6)  # 体素边长 cm

NX, NY, NZ = DS_SHAPE
HALF_X = DS_VOX_CM[0] / 2          # 0.2137 cm
HALF_Z = DS_VOX_CM[2] / 2          # 0.800  cm

PHANT_X = NX * HALF_X              # 27.140 cm
PHANT_Z = NZ * HALF_Z              # 88.800 cm

# AP 源面积 cm²  (X×Z 覆盖整个体模截面)
A_SOURCE = 2 * PHANT_X * 2 * PHANT_Z   # 9640.128 cm²
NPS      = 10_000_000                   # 与 Step2 inp 中 nps 卡一致

ENERGIES_MEV = [0.01, 0.10, 1.00, 10.00]
NPY_TEMPLATE = 'fluence_E{e:.3f}MeV.npy'


# ═══════════════════════════════════════════════════════════════════════════
# NIST XCOM  μ_en/ρ  (cm²/g)
# ═══════════════════════════════════════════════════════════════════════════
# 按组织类型分组，能量顺序: [0.01, 0.10, 1.00, 10.00] MeV
# 来源: NIST XCOM (https://physics.nist.gov/PhysRefData/Xcom/html/xcom1.html)
MU_EN_RHO = {
    # ICRU-44 软组织 (H:10.1%, C:11.1%, N:2.6%, O:76.2%)
    'soft':  [4.939,  0.02546, 0.03069, 0.02171],
    # 肺 (充气, ICRU-44 成分相同, 密度不同不影响质量系数)
    'lung':  [4.942,  0.02545, 0.03064, 0.02168],
    # 皮肤 (ICRU-44 相近)
    'skin':  [4.939,  0.02546, 0.03069, 0.02171],
    # 骨质 (ICRU 皮质骨, Ca/P 含量高, 低能 μ_en/ρ 大幅升高)
    'bone':  [26.09,  0.03008, 0.03011, 0.02182],
    # 红骨髓 (软组织为主)
    'marrow':[4.939,  0.02546, 0.03069, 0.02171],
}

# 能量索引映射
E_IDX = {e: i for i, e in enumerate(ENERGIES_MEV)}

# 器官名 → 组织类型
ORGAN_TISSUE_TYPE = {
    'Adrenals':             'soft',
    'Brain':                'soft',
    'Colon wall':           'soft',
    'Oesophagus':           'soft',
    'Eye lenses':           'soft',
    'Gallbladder wall':     'soft',
    'Heart muscle':         'soft',
    'Kidneys':              'soft',
    'Liver':                'soft',
    'Lungs':                'lung',
    'Pancreas':             'soft',
    'Prostate':             'soft',
    'Salivary glands':      'soft',
    'Skin':                 'skin',
    'Spinal cord':          'soft',
    'Spleen':               'soft',
    'Stomach wall':         'soft',
    'Testes':               'soft',
    'Thymus':               'soft',
    'Thyroid':              'soft',
    'Urinary bladder wall': 'soft',
    'Red bone marrow':      'marrow',
    'Bone surface':         'bone',
}


# ═══════════════════════════════════════════════════════════════════════════
# ICRP-116 Table A.3 参考值
# AP 几何，成人男性 (AM)，光子，h_T (pGy·cm²)
# 来源: ICRP Publication 116 (2010), Table A.3
# 能量: 0.01, 0.10, 1.00, 10.00 MeV
# ═══════════════════════════════════════════════════════════════════════════
# 格式: {器官名: [h_T@0.01MeV, h_T@0.10MeV, h_T@1.00MeV, h_T@10.00MeV]}
# None 表示该表未单独列出该器官 / 在该能量下值极小
ICRP116_REF = {
    # 表 A.3 选取的器官（ICRP-116, 2010, AM, AP, photons）
    'Adrenals':             [None,   0.133,  1.10,   2.14],
    'Brain':                [None,   0.106,  0.898,  1.72],
    'Colon wall':           [None,   0.121,  1.07,   1.97],
    'Oesophagus':           [None,   0.130,  1.13,   2.24],
    'Gallbladder wall':     [None,   0.139,  1.16,   2.25],
    'Heart muscle':         [None,   0.145,  1.18,   2.32],
    'Kidneys':              [None,   0.137,  1.13,   2.17],
    'Liver':                [None,   0.147,  1.17,   2.25],
    'Lungs':                [None,   0.166,  1.29,   2.82],
    'Pancreas':             [None,   0.143,  1.16,   2.24],
    'Prostate':             [None,   0.061,  0.738,  1.40],
    'Salivary glands':      [None,   0.145,  1.04,   1.87],
    'Skin':                 [0.0147, 0.0613, 0.614,  1.30],
    'Spinal cord':          [None,   0.099,  0.967,  2.02],
    'Spleen':               [None,   0.147,  1.17,   2.25],
    'Stomach wall':         [None,   0.132,  1.11,   2.09],
    'Testes':               [None,   0.058,  0.717,  1.35],
    'Thymus':               [None,   0.165,  1.29,   2.66],
    'Thyroid':              [None,   0.197,  1.33,   2.40],
    'Urinary bladder wall': [None,   0.087,  0.800,  1.48],
    'Red bone marrow':      [None,   0.059,  0.680,  1.60],
    # 有效剂量系数 (pSv·cm²) — 单独列在最后
    'Effective dose':       [0.0288, 0.292,  1.21,   2.21],
}


# ═══════════════════════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════════════════════

def load_meta(meta_path: str) -> dict:
    """加载 organ_mask_meta.json，返回 {organ_name: [organ_ids]}"""
    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    return meta


def load_mask(mask_path: str) -> np.ndarray:
    """加载器官掩膜 (nx, ny, nz) uint8/int16"""
    mask = np.load(mask_path)
    if mask.shape != DS_SHAPE:
        raise ValueError(f'掩膜 shape {mask.shape} ≠ 期望 {DS_SHAPE}')
    return mask


def load_fluence(npy_path: str) -> np.ndarray:
    """
    加载通量 npy 文件，返回 shape (nx, ny, nz) float32/64。
    FMESH14 输出顺序为 (ix, iy, iz)，与掩膜轴向一致。
    """
    arr = np.load(npy_path).astype(np.float64)
    if arr.shape != DS_SHAPE:
        # 尝试 reshape
        if arr.size == NX * NY * NZ:
            arr = arr.reshape(DS_SHAPE)
        else:
            raise ValueError(
                f'{npy_path}: shape {arr.shape} 无法 reshape 为 {DS_SHAPE}'
            )
    return arr


# ═══════════════════════════════════════════════════════════════════════════
# 剂量系数计算
# ═══════════════════════════════════════════════════════════════════════════

def organ_dose_coefficient(
    fluence: np.ndarray,
    mask: np.ndarray,
    organ_ids: list,
    energy_mev: float,
    tissue_type: str,
) -> tuple:
    """
    计算单个器官在单个能量下的剂量系数。

    Parameters
    ----------
    fluence    : (nx, ny, nz)  cm⁻² per source particle
    mask       : (nx, ny, nz)  organ id per voxel
    organ_ids  : list of int   属于该器官的 organ_id 列表
    energy_mev : float         光子能量 (MeV)
    tissue_type: str           组织类型 key in MU_EN_RHO

    Returns
    -------
    h_T    : float  pGy·cm²（若体素数=0 则 None）
    n_vox  : int    体素数
    phi_mean: float 平均注量 (cm⁻²/particle)
    """
    # 提取器官体素
    mask_bool = np.zeros(DS_SHAPE, dtype=bool)
    for oid in organ_ids:
        mask_bool |= (mask == oid)

    n_vox = int(np.sum(mask_bool))
    if n_vox == 0:
        return None, 0, 0.0

    phi_mean = float(np.mean(fluence[mask_bool]))

    # μ_en/ρ 插值（仅支持4个固定能量，直接查表）
    ei = E_IDX.get(round(energy_mev, 3))
    if ei is None:
        # fallback: 最近邻
        ei = int(np.argmin([abs(e - energy_mev) for e in ENERGIES_MEV]))
    mu_en_rho = MU_EN_RHO[tissue_type][ei]

    # h_T (pGy·cm²) = Φ̄_T × A_src × E_MeV × μ_en/ρ × 160.2
    # 160.2 = 1.602e-13 J/MeV × 1e3 g/kg × 1e12 pGy/Gy
    h_T = phi_mean * A_SOURCE * energy_mev * mu_en_rho * 160.2

    return h_T, n_vox, phi_mean


# ═══════════════════════════════════════════════════════════════════════════
# 主分析流程
# ═══════════════════════════════════════════════════════════════════════════

def run_analysis(
    out_dir: str,
    mask_path: str,
    meta_path: str,
) -> dict:
    """
    对 4 个能量点逐一计算器官剂量系数，返回完整结果字典。
    """
    out_dir = Path(out_dir)
    print(f'\n[Step3] 载入器官掩膜: {mask_path}')
    mask = load_mask(mask_path)

    print(f'[Step3] 载入元数据: {meta_path}')
    meta = load_meta(meta_path)
    organ_groups = meta.get('organ_groups', {})
    print(f'  器官组数: {len(organ_groups)}')

    all_results = {}

    for energy in ENERGIES_MEV:
        npy_name = NPY_TEMPLATE.format(e=energy)
        npy_path = out_dir / npy_name

        if not npy_path.exists():
            print(f'  [跳过] 未找到 {npy_path}')
            continue

        print(f'\n[Step3] E={energy:.3f} MeV  → {npy_path.name}')
        fluence = load_fluence(str(npy_path))

        # 基本统计
        fmax = float(np.max(fluence))
        fmean_body = float(np.mean(fluence[mask > 0]))
        print(f'  fluence max={fmax:.3e}  body_mean={fmean_body:.3e} cm⁻²/particle')

        organ_results = {}
        for organ_name, organ_ids in organ_groups.items():
            tissue = ORGAN_TISSUE_TYPE.get(organ_name, 'soft')
            h_T, n_vox, phi_mean = organ_dose_coefficient(
                fluence, mask, organ_ids, energy, tissue
            )
            ref_vals = ICRP116_REF.get(organ_name)
            ref_h = ref_vals[E_IDX[round(energy, 3)]] if ref_vals else None

            if h_T is not None and ref_h is not None and ref_h > 0:
                dev_pct = (h_T - ref_h) / ref_h * 100.0
            else:
                dev_pct = None

            organ_results[organ_name] = {
                'h_T_mcnp_pGy_cm2':   round(h_T, 4) if h_T is not None else None,
                'h_T_icrp116_pGy_cm2': ref_h,
                'deviation_pct':       round(dev_pct, 1) if dev_pct is not None else None,
                'voxel_count':         n_vox,
                'phi_mean_per_particle': float(f'{phi_mean:.4e}'),
                'tissue_type':         tissue,
            }

            # 控制台简报
            if h_T is not None and ref_h is not None:
                flag = ''
                if dev_pct is not None:
                    if abs(dev_pct) <= 10:
                        flag = '✓'
                    elif abs(dev_pct) <= 20:
                        flag = '△'
                    else:
                        flag = '✗'
                print(f'  {organ_name:<26}  MCNP={h_T:7.4f}  REF={ref_h:7.4f}  '
                      f'dev={dev_pct:+6.1f}%  {flag}  ({n_vox} vox)')
            elif h_T is not None:
                print(f'  {organ_name:<26}  MCNP={h_T:7.4f}  (无ICRP-116参考值)  ({n_vox} vox)')

        all_results[energy] = {
            'energy_mev': energy,
            'A_source_cm2': A_SOURCE,
            'NPS': NPS,
            'fluence_file': str(npy_path),
            'organ_results': organ_results,
        }

    return all_results


# ═══════════════════════════════════════════════════════════════════════════
# 汇总打印
# ═══════════════════════════════════════════════════════════════════════════

def print_summary(all_results: dict):
    """打印偏差汇总表。"""
    if not all_results:
        print('\n[Step3] 无可用结果（是否已将 fluence npy 文件复制到 mcnp_outputs 目录？）')
        return

    print('\n' + '=' * 80)
    print('ICRP-116 Table A.3 对比汇总  (AP, AM, photons)  [pGy·cm²]')
    print('=' * 80)

    # 汇总：有几个器官在各能量点偏差 <10%
    for energy, edata in sorted(all_results.items()):
        print(f'\n  E = {energy:.3f} MeV')
        print(f'  {"器官":<26} {"MCNP":>8} {"ICRP116":>8} {"偏差%":>8} {"体素":>6}')
        print(f'  {"-"*26} {"-"*8} {"-"*8} {"-"*8} {"-"*6}')

        ok = warn = err = skip = 0
        for oname, od in edata['organ_results'].items():
            h  = od['h_T_mcnp_pGy_cm2']
            r  = od['h_T_icrp116_pGy_cm2']
            dv = od['deviation_pct']
            nv = od['voxel_count']
            if h is None:
                skip += 1
                continue
            if r is None:
                print(f'  {oname:<26} {h:8.4f} {"N/A":>8} {"N/A":>8} {nv:6d}')
                continue
            dv_str = f'{dv:+.1f}%' if dv is not None else 'N/A'
            if dv is not None:
                if abs(dv) <= 10:  ok += 1
                elif abs(dv) <= 20: warn += 1
                else: err += 1
            print(f'  {oname:<26} {h:8.4f} {r:8.4f} {dv_str:>8} {nv:6d}')

        print(f'  → ✓≤10%: {ok}  △10-20%: {warn}  ✗>20%: {err}  跳过(0体素): {skip}')

    print('\n注：偏差来源分析见 JSON 报告；以下器官体素数少，离散化误差大：')
    print('  Adrenals(47), Bone surface(41), Gallbladder(48), '
          'Prostate(46), Thyroid(44), Testes(99), Eye lenses(0)')


# ═══════════════════════════════════════════════════════════════════════════
# 图表生成
# ═══════════════════════════════════════════════════════════════════════════

def generate_chart(all_results: dict, chart_path: str):
    """生成 4 能量点 × 器官剂量系数对比图。"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib as mpl
        mpl.rcParams['axes.unicode_minus'] = False
    except ImportError:
        print('[Step3] matplotlib 未安装，跳过图表生成')
        return

    energies = sorted(all_results.keys())
    n_e = len(energies)
    if n_e == 0:
        return

    fig, axes = plt.subplots(1, n_e, figsize=(5 * n_e, 7))
    if n_e == 1:
        axes = [axes]

    fig.suptitle(
        'ICRP-116 Table A.3 Validation: MCNP5 vs Reference\n'
        'AP Photons, Adult Male (AM)',
        fontsize=12, fontweight='bold'
    )

    # 仅显示有 ICRP-116 参考值且体素数 ≥ 50 的器官
    for ax, energy in zip(axes, energies):
        edata = all_results[energy]
        rows = [
            (oname, od)
            for oname, od in edata['organ_results'].items()
            if od['h_T_mcnp_pGy_cm2'] is not None
            and od['h_T_icrp116_pGy_cm2'] is not None
            and od['voxel_count'] >= 50
        ]
        if not rows:
            ax.set_title(f'E={energy:.3f} MeV\n(no data)')
            continue

        names  = [r[0].replace(' wall', '').replace(' muscle', '').replace(' (with blood)', '')
                  for r in rows]
        mcnp   = [r[1]['h_T_mcnp_pGy_cm2'] for r in rows]
        ref    = [r[1]['h_T_icrp116_pGy_cm2'] for r in rows]
        devs   = [r[1]['deviation_pct'] for r in rows]

        x = np.arange(len(names))
        w = 0.35

        bars_r = ax.bar(x - w/2, ref,  w, label='ICRP-116 Ref', color='#2196F3', alpha=0.82)
        bars_m = ax.bar(x + w/2, mcnp, w, label='MCNP5',        color='#FF5722', alpha=0.82)

        # 偏差标注
        max_v = max(max(ref), max(mcnp)) if ref else 1
        for bar, dv in zip(bars_m, devs):
            if dv is None:
                continue
            color = '#4CAF50' if abs(dv) <= 10 else ('#FF9800' if abs(dv) <= 20 else '#F44336')
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max_v * 0.015,
                f'{dv:+.0f}%', ha='center', va='bottom',
                fontsize=6, color=color, fontweight='bold'
            )

        ax.set_title(f'E = {energy:.3f} MeV', fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(names, rotation=45, ha='right', fontsize=7)
        ax.set_ylabel('h$_T$ (pGy·cm²)', fontsize=9)
        ax.legend(fontsize=8)
        ax.grid(axis='y', alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'\n[Step3] 图表已保存: {chart_path}')


# ═══════════════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='ICRP-116 验证 Step3: 提取 MCNP5 器官剂量系数并与参考值对比'
    )
    parser.add_argument(
        '--out-dir', default='icrp_validation/mcnp_outputs',
        help='含 fluence_E*.npy 的目录（Step2b 输出）'
    )
    parser.add_argument(
        '--mask', default='icrp_validation/organ_mask_127x63x111.npy',
        help='器官掩膜 npy 文件（Step1 输出）'
    )
    parser.add_argument(
        '--meta', default='icrp_validation/organ_mask_meta.json',
        help='器官元数据 JSON（Step1 输出）'
    )
    parser.add_argument(
        '--chart', default='icrp_validation/mcnp_outputs/icrp116_comparison.png',
        help='输出图表路径'
    )
    parser.add_argument(
        '--json-out', default='icrp_validation/mcnp_outputs/icrp116_comparison.json',
        help='输出 JSON 结果路径'
    )
    args = parser.parse_args()

    # ── 检查前置文件 ──────────────────────────────────────────────────────
    missing = []
    if not Path(args.mask).exists():
        missing.append(f'  器官掩膜:  {args.mask}')
    if not Path(args.meta).exists():
        missing.append(f'  元数据:    {args.meta}')
    if missing:
        print('[错误] 缺少前置文件:')
        for m in missing:
            print(m)
        print('  请先运行 Step1 (mcnp_icrp_step1_organ_mask.py)')
        sys.exit(1)

    out_dir = Path(args.out_dir)
    if not out_dir.exists():
        print(f'[错误] mcnp_outputs 目录不存在: {out_dir}')
        print('  请先在 Windows 上运行 Step2b (mcnp_icrp_step2b_run_mcnp.py),')
        print('  再将生成的 fluence_E*.npy 文件复制到此目录。')
        sys.exit(1)

    available = list(out_dir.glob('fluence_E*.npy'))
    if not available:
        print(f'[错误] {out_dir} 中未找到 fluence_E*.npy 文件')
        print('  请将 MCNP5 计算结果 (fluence_E0.010MeV.npy 等) 复制到该目录')
        sys.exit(1)

    print(f'[Step3] 找到 {len(available)} 个通量文件:')
    for f in sorted(available):
        size_kb = f.stat().st_size / 1024
        print(f'  {f.name}  ({size_kb:.0f} KB)')

    # ── 运行分析 ──────────────────────────────────────────────────────────
    all_results = run_analysis(
        out_dir=str(out_dir),
        mask_path=args.mask,
        meta_path=args.meta,
    )

    # ── 汇总打印 ──────────────────────────────────────────────────────────
    print_summary(all_results)

    # ── 保存 JSON ─────────────────────────────────────────────────────────
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        # 将 float 键转为 str 以支持 JSON
        serializable = {str(k): v for k, v in all_results.items()}
        with open(args.json_out, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
        print(f'\n[Step3] JSON 结果: {args.json_out}')

    # ── 生成图表 ──────────────────────────────────────────────────────────
    if args.chart:
        Path(args.chart).parent.mkdir(parents=True, exist_ok=True)
        generate_chart(all_results, args.chart)

    print('\n[Step3] 完成！')


if __name__ == '__main__':
    main()
