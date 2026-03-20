#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
MCNP ICRP-116 验证 — 第三步：有效剂量换算系数对比
====================================================
读取 Step2b 生成的 fluence_E*.npy，结合器官掩膜和 ICRP-110 器官数据，
计算各能量点的光子注量-有效剂量换算系数 h_E（pSv·cm²），
并与 ICRP-116 Table A.3（AP 几何，光子）参考值对比。

物理公式
--------
  D_T  [Gy/sp] = Φ_T [cm⁻²/sp] × E [MeV] × (μ_en/ρ)_T [cm²/g] × 1.602e-10
  E_eff [Sv/sp] = Σ_T  w_T × D_T          (光子 w_R = 1)
  h_E [pSv·cm²] = E_eff / Φ_incident × 1e12
  Φ_incident  = 1 / beam_area              (平行束，单位 cm⁻²/sp)

注: μ_en/ρ 来自 NIST XCOM，对所有软组织器官统一使用软组织值；
    含有 cortical/spongiosa/bone 关键字的器官使用皮质骨值。

【运行方法】
  python mcnp_icrp_step3_compare.py
  python mcnp_icrp_step3_compare.py \
      --out-dir  backend/icrp_validation/mcnp_outputs \
      --mask     backend/icrp_validation/organ_mask_127x63x111.npy \
      --zip      "backend/P110 data V1.2/AM.zip"
"""

import argparse
import re
import sys
import zipfile
from pathlib import Path

# Windows GBK 终端下强制 UTF-8 输出，避免含特殊字符的 print 崩溃
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import numpy as np

# ─── 体模参数（与 Step 1/2 保持完全一致） ────────────────────────
NX, NY, NZ   = 127, 63, 111
VOX_X, VOX_Y, VOX_Z = 0.4274, 0.4308, 1.6      # cm（全尺寸体素）
PHANT_X = NX * VOX_X / 2    # 27.1399 cm
PHANT_Z = NZ * VOX_Z / 2    # 88.800 cm
BEAM_AREA = (2 * PHANT_X) * (2 * PHANT_Z)       # cm²  ≈ 9639 cm²

# 4 个验证能量点
ENERGIES = [0.010, 0.100, 1.000, 10.000]

# ─── ICRP-116 Table A.3 参考值（AP 光子，pSv·cm²） ───────────────
# 来源: ICRP Publication 116 (2010), Table A.3
ICRP116_REF = {
    0.010:  0.0288,
    0.100:  0.340,
    1.000:  2.76,
    10.000: 18.1,
}

# ─── NIST XCOM μ_en/ρ（cm²/g） ──────────────────────────────────
# 软组织 ICRU-44: H10.1%, C11.1%, N2.6%, O76.2%
MU_EN_RHO_SOFT = {0.010: 4.742,  0.100: 0.02546, 1.000: 0.03066, 10.000: 0.02176}
# 皮质骨 ICRU-44
MU_EN_RHO_BONE = {0.010: 19.10,  0.100: 0.02916, 1.000: 0.02939, 10.000: 0.02045}

# ─── ICRP-103 组织权重因子 wT ─────────────────────────────────────
# (关键字列表, wT)  — 按优先级排列，首先匹配者生效
_W = 0.12 / 14   # 余量器官每个 wT
WT_RULES = [
    (['testes', 'testis'],                               0.08),   # 性腺(男)
    (['ovaries', 'ovary'],                               0.08),   # 性腺(女)
    (['colon', 'large intestine'],                       0.12),
    (['lung'],                                           0.12),
    (['stomach wall', 'stomach'],                        0.12),
    (['red bone marrow', 'red marrow', 'spongiosa'],     0.12),   # 红骨髓
    (['urinary bladder', 'bladder wall', 'bladder'],     0.04),
    (['oesophagus', 'esophagus'],                        0.04),
    (['liver'],                                          0.04),
    (['thyroid'],                                        0.04),
    (['bone surface', 'endosteum'],                      0.01),
    (['brain'],                                          0.01),
    (['salivary gland', 'salivary'],                     0.01),
    (['skin'],                                           0.01),
    # 余量器官 (0.12 / 14 each)
    (['adrenal'],                                        _W),
    (['extrathoracic', 'et region'],                     _W),
    (['gallbladder', 'gall bladder'],                    _W),
    (['heart wall', 'heart muscle', 'heart'],            _W),
    (['kidney'],                                         _W),
    (['lymph node', 'lymph'],                            _W),
    (['muscle'],                                         _W),
    (['oral mucosa'],                                    _W),
    (['pancreas'],                                       _W),
    (['prostate'],                                       _W),
    (['small intestine'],                                _W),
    (['spleen'],                                         _W),
    (['thymus'],                                         _W),
    (['uterus', 'cervix'],                               _W),
]

# 使用皮质骨 μ_en/ρ 的器官关键字
BONE_KEYWORDS = [
    'cortical bone', 'cranium', 'mandible', 'spine', 'vertebra',
    'rib', 'pelv', 'femur', 'humer', 'tibia', 'fibula',
    'clavicle', 'scapul', 'patella', 'sternum', 'sacrum',
    'bone surface', 'endosteum',
]


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def get_wt(name: str) -> float:
    """由器官名称查找 ICRP-103 wT，未匹配返回 0。"""
    nlc = name.lower()
    for keywords, wt in WT_RULES:
        if any(k in nlc for k in keywords):
            return wt
    return 0.0


def get_mu_en_rho(name: str, energy: float) -> float:
    """根据器官名称选择 μ_en/ρ 值。"""
    nlc = name.lower()
    if any(k in nlc for k in BONE_KEYWORDS):
        return MU_EN_RHO_BONE[energy]
    return MU_EN_RHO_SOFT[energy]


def parse_organs(lines):
    """AM_organs.dat → {organ_id: (tissue_num, density, name)}"""
    organs = {}
    for line in lines:
        m = re.match(r'^\s*(\d+)\s+(.+?)\s{2,}(\d+)\s+([\d.]+)\s*$', line.strip())
        if m:
            oid     = int(m.group(1))
            name    = m.group(2).strip()
            tissue  = int(m.group(3))
            density = float(m.group(4))
            organs[oid] = (tissue, density, name)
    return organs


def load_organs(zip_path: str) -> dict:
    """从 AM.zip 读取 AM_organs.dat，返回 {id: (tissue, density, name)}。"""
    with zipfile.ZipFile(zip_path, 'r') as z:
        text = z.read('AM/AM_organs.dat').decode('utf-8', errors='replace')
    return parse_organs(text.splitlines())


# ═══════════════════════════════════════════════════════════════
# 核心计算
# ═══════════════════════════════════════════════════════════════

def compute_h_eff(fluence_npy: np.ndarray, mask: np.ndarray,
                  organs: dict, energy: float) -> tuple:
    """
    计算单能量点的 h_E（pSv·cm²）。

    Parameters
    ----------
    fluence_npy : shape (nz, ny, nx) — MCNP FMESH 注量 [cm⁻²/sp]
    mask        : shape (nx, ny, nz) — 器官掩膜（uint8/int）
    organs      : {organ_id: (tissue, density, name)}
    energy      : 光子能量 MeV

    Returns
    -------
    h_eff       : float, pSv·cm²
    organ_table : list of (name, wT, mean_fluence, dose_pGy, wT_dose) sorted by |contribution|
    """
    # 将 fluence (nz,ny,nx) 转置为 (nx,ny,nz) 与 mask 对齐
    fluence = fluence_npy.transpose(2, 1, 0)   # (nx, ny, nz)

    unique_ids = np.unique(mask)
    organ_table = []
    e_eff_pGy = 0.0   # pGy per source particle

    for oid in unique_ids:
        if oid == 0:
            continue   # 体外空气
        if oid not in organs:
            continue

        _, _, name = organs[oid]
        wt = get_wt(name)
        if wt == 0.0:
            continue   # 无需计入有效剂量

        mu_en_rho = get_mu_en_rho(name, energy)

        # 该器官体素索引
        voxel_mask = (mask == oid)
        mean_fluence = float(fluence[voxel_mask].mean())

        # D_T [pGy/sp] = Φ × E × (μ_en/ρ) × 1.602e-10 × 1e12
        dose_pGy = mean_fluence * energy * mu_en_rho * 1.602e-10 * 1e12

        wt_dose = wt * dose_pGy
        e_eff_pGy += wt_dose

        organ_table.append((name, wt, mean_fluence, dose_pGy, wt_dose))

    # h_E [pSv·cm²] = E_eff [pSv/sp] / Φ_incident [cm⁻²/sp]
    #               = E_eff [pGy/sp] × BEAM_AREA [cm²]
    h_eff = e_eff_pGy * BEAM_AREA

    organ_table.sort(key=lambda r: abs(r[4]), reverse=True)
    return h_eff, organ_table


# ═══════════════════════════════════════════════════════════════
# 输出
# ═══════════════════════════════════════════════════════════════

def print_organ_table(organ_table, energy):
    """打印器官剂量贡献明细（前 15 位）。"""
    print(f"\n  {'器官名称':<35} {'wT':>6} {'mean Φ':>12} {'D_T(pGy)':>12} {'wT×D_T':>12}")
    print("  " + "-" * 82)
    for name, wt, phi, dose, contrib in organ_table[:15]:
        print(f"  {name:<35} {wt:>6.4f} {phi:>12.3e} {dose:>12.3e} {contrib:>12.3e}")
    if len(organ_table) > 15:
        print(f"  ... 共 {len(organ_table)} 个器官")


def save_csv(results, out_dir: Path):
    """保存对比结果到 CSV。"""
    csv_path = out_dir / "icrp116_comparison.csv"
    lines = ["Energy_MeV,h_calc_pSv_cm2,h_ref_pSv_cm2,deviation_pct,pass"]
    for e, h_calc, h_ref, dev in results:
        ok = "PASS" if abs(dev) <= 10 else "FAIL"
        lines.append(f"{e:.3f},{h_calc:.4f},{h_ref:.4f},{dev:.1f},{ok}")
    csv_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[CSV] 结果已保存: {csv_path}")
    return csv_path


def try_plot(results, out_dir: Path):
    """生成对比折线图（需要 matplotlib）。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[提示] 未安装 matplotlib，跳过绘图")
        return

    energies  = [r[0] for r in results]
    h_calc    = [r[1] for r in results]
    h_ref     = [r[2] for r in results]
    devs      = [r[3] for r in results]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # ── 左图：h_E 对比 ──
    ax1.loglog(energies, h_ref,  'o-', color='royalblue',  lw=2, ms=7, label='ICRP-116 参考值')
    ax1.loglog(energies, h_calc, 's--', color='tomato', lw=2, ms=7, label='MCNP5 计算值')
    ax1.set_xlabel('光子能量 (MeV)', fontsize=12)
    ax1.set_ylabel('h_E  (pSv·cm²)', fontsize=12)
    ax1.set_title('AP 光子注量-有效剂量换算系数', fontsize=13)
    ax1.legend(fontsize=11)
    ax1.grid(True, which='both', alpha=0.3)
    for e, hc, hr in zip(energies, h_calc, h_ref):
        ax1.annotate(f'{e} MeV', xy=(e, hc), xytext=(4, 4),
                     textcoords='offset points', fontsize=8)

    # ── 右图：偏差 % ──
    colors = ['green' if abs(d) <= 5 else ('orange' if abs(d) <= 10 else 'red')
              for d in devs]
    bars = ax2.bar([f'{e} MeV' for e in energies], devs, color=colors, edgecolor='k', width=0.5)
    ax2.axhline(0,   color='black', lw=1)
    ax2.axhline(+10, color='orange', lw=1.2, ls='--', label='±10%')
    ax2.axhline(-10, color='orange', lw=1.2, ls='--')
    ax2.axhline(+5,  color='green',  lw=1,   ls=':',  label='±5%')
    ax2.axhline(-5,  color='green',  lw=1,   ls=':')
    ax2.set_xlabel('光子能量', fontsize=12)
    ax2.set_ylabel('偏差 (%)', fontsize=12)
    ax2.set_title('相对偏差  (MCNP5 − ICRP-116) / ICRP-116', fontsize=13)
    ax2.legend(fontsize=10)
    for bar, d in zip(bars, devs):
        ax2.text(bar.get_x() + bar.get_width()/2, d + (0.3 if d >= 0 else -0.8),
                 f'{d:+.1f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')

    fig.tight_layout()
    png_path = out_dir / "icrp116_comparison.png"
    fig.savefig(png_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"[图表] 已保存: {png_path}")


# ═══════════════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="ICRP-116 验证 Step3：计算 h_E 并与参考值对比"
    )
    parser.add_argument("--out-dir",
        default=r"icrp_validation/mcnp_outputs",
        help="fluence_E*.npy 所在目录（同时也是输出目录）")
    parser.add_argument("--mask",
        default=r"icrp_validation/organ_mask_127x63x111.npy",
        help="Step1 生成的器官掩膜路径")
    parser.add_argument("--zip",
        default=r"P110 data V1.2/AM.zip",
        help="ICRP-110 AM.zip 路径（含 AM_organs.dat）")
    parser.add_argument("--no-plot", action="store_true",
        help="跳过生成图表")
    args = parser.parse_args()

    out_dir  = Path(args.out_dir)
    mask_path = Path(args.mask)
    zip_path  = Path(args.zip)

    # ── 检查输入 ──────────────────────────────────────────────
    errors = []
    if not out_dir.exists():
        errors.append(f"输出目录不存在: {out_dir}")
    if not mask_path.exists():
        errors.append(f"器官掩膜不存在: {mask_path}")
    if not zip_path.exists():
        errors.append(f"AM.zip 不存在: {zip_path}")
    if errors:
        for e in errors:
            print(f"[错误] {e}")
        sys.exit(1)

    # ── 加载公共数据 ─────────────────────────────────────────
    print("━━━ ICRP-116 Step3 对比分析 ━━━")
    print(f"  out_dir  : {out_dir}")
    print(f"  mask     : {mask_path}")
    print(f"  zip      : {zip_path}")
    print(f"  beam_area: {BEAM_AREA:.2f} cm^2\n")

    print("[1/3] 加载器官掩膜 ...")
    mask = np.load(mask_path)
    assert mask.shape == (NX, NY, NZ), \
        f"掩膜 shape 应为 ({NX},{NY},{NZ})，实为 {mask.shape}"
    print(f"      shape={mask.shape}  unique_ids={len(np.unique(mask))}")

    print("[2/3] 加载 AM_organs.dat ...")
    organs = load_organs(str(zip_path))
    print(f"      共 {len(organs)} 个器官")

    # ── 逐能量点计算 ─────────────────────────────────────────
    print("\n[3/3] 逐能量点计算 h_E ...")
    results = []   # (energy, h_calc, h_ref, deviation%)

    for energy in ENERGIES:
        npy_name = f"fluence_E{energy:.3f}MeV.npy"
        npy_path = out_dir / npy_name

        if not npy_path.exists():
            print(f"\n  [跳过] 找不到 {npy_path}")
            continue

        print(f"\n  ── E = {energy:.3f} MeV  [{npy_name}] ──")
        fluence = np.load(npy_path)
        print(f"     fluence shape={fluence.shape}  "
              f"max={fluence.max():.3e}  mean={fluence.mean():.3e}")

        h_calc, organ_table = compute_h_eff(fluence, mask, organs, energy)
        h_ref  = ICRP116_REF[energy]
        dev    = (h_calc - h_ref) / h_ref * 100

        print_organ_table(organ_table, energy)

        flag = "✓" if abs(dev) <= 10 else ("△" if abs(dev) <= 20 else "✗")
        print(f"\n  结果:  h_E(计算)={h_calc:.4f}  h_E(ICRP-116)={h_ref:.4f}  "
              f"偏差={dev:+.1f}%  {flag}")

        results.append((energy, h_calc, h_ref, dev))

    if not results:
        print("\n[错误] 未找到任何 fluence npy 文件，请先运行 Step2b")
        sys.exit(1)

    # ── 汇总表格 ─────────────────────────────────────────────
    print("\n" + "═" * 65)
    print(f"  {'能量(MeV)':<12} {'h_计算(pSv·cm²)':>16} {'h_ICRP-116':>12} {'偏差':>8}  判定")
    print("  " + "─" * 60)
    passed = 0
    for e, hc, hr, d in results:
        ok  = abs(d) <= 10
        sym = "PASS ✓" if ok else ("△<20%" if abs(d) <= 20 else "FAIL ✗")
        print(f"  {e:<12.3f} {hc:>16.4f} {hr:>12.4f} {d:>+7.1f}%  {sym}")
        if ok:
            passed += 1
    print("  " + "─" * 60)
    print(f"  通过率（±10%）: {passed}/{len(results)}")
    print("═" * 65)

    # ── 保存 CSV ──────────────────────────────────────────────
    save_csv(results, out_dir)

    # ── 绘图 ─────────────────────────────────────────────────
    if not args.no_plot:
        try_plot(results, out_dir)

    print("\n完成！结果文件位于:", out_dir)


if __name__ == "__main__":
    main()
