#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
MCNP ICRP-116 验证 — 第三步：有效剂量换算系数对比
====================================================
读取 Step2b 生成的 fluence_E*.npy，结合器官掩膜和 ICRP-110 器官数据，
计算各能量点的光子注量-有效剂量换算系数 h_E（pSv·cm^2），
并与 ICRP-116 Table A.3（AP 几何，光子）参考值对比。

物理公式
--------
  D_T  [Gy/sp] = Phi_T [cm^-2/sp] x E [MeV] x (mu_en/rho)_T [cm^2/g] x 1.602e-10
  E_eff [Sv/sp] = sum_T  w_T x D_T          (光子 w_R = 1)
  h_E [pSv*cm^2] = E_eff / Phi_incident x 1e12
  Phi_incident  = 1 / beam_area              (平行束，单位 cm^-2/sp)

注: mu_en/rho 来自 NIST XCOM，对所有软组织器官统一使用软组织值；
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
PHANT_Y_FULL = NY * VOX_Y   # 27.14 cm（体模 AP 方向全深度）

# 4 个验证能量点
ENERGIES = [0.010, 0.100, 1.000, 10.000]

# ─── ICRP-116 Table A.3 参考值（AP 光子，pSv·cm^2） ───────────────
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

def is_data_reliable(fluence_npy: np.ndarray) -> bool:
    """
    检测 fluence 是否为可信的 MCNP 结果，还是 extract 脚本的随机数回退数据。

    extract_from_standard_output 回退时返回 np.random.rand(...) * 1e-5：
      - max 恰好约 1e-5（精确上限）
      - mean 约 5e-6，CV(变异系数) 约 0.577（均匀分布特征）
    真实 MCNP 数据具有明显的空间梯度，max 不会恰好等于上限。
    """
    max_val = fluence_npy.max()
    if max_val <= 0:
        return False
    # 检测 max 是否被钳位于 1e-5
    if 9.5e-6 <= max_val <= 1.0e-5:
        nonzero = fluence_npy[fluence_npy > 0]
        cv = nonzero.std() / nonzero.mean()
        if 0.40 < cv < 0.70:   # 均匀分布 CV = 1/sqrt(3) 约 0.577
            return False
    return True


def prepare_mcnp_fluence(fluence_npy: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """
    将 MCNP FMESH 输出 (nz_full, ny_full, nx_full) 转置并
    2× block-average 降采样至掩膜分辨率 (NX, NY, NZ)。
    """
    fluence = fluence_npy.transpose(2, 1, 0)   # (nx_full, ny_full, nz_full)
    if fluence.shape == mask.shape:
        return fluence
    nx_f, ny_f, nz_f = fluence.shape
    nx_m, ny_m, nz_m = mask.shape
    sx = nx_f // nx_m
    sy = ny_f // ny_m
    sz = nz_f // nz_m
    fluence = fluence.reshape(nx_m, sx, ny_f, nz_f).mean(axis=1)
    fluence = fluence[:, :ny_m * sy, :].reshape(nx_m, ny_m, sy, nz_f).mean(axis=2)
    fluence = fluence.reshape(nx_m, ny_m, nz_m, sz).mean(axis=3)
    assert fluence.shape == mask.shape, \
        f"降采样后 shape={fluence.shape} 与 mask={mask.shape} 不符"
    return fluence



def compute_h_eff_from_fluence(fluence: np.ndarray, mask: np.ndarray,
                                organs: dict, energy: float) -> tuple:
    """
    从已对齐至掩膜分辨率的 fluence (NX, NY, NZ) 计算 h_E (pSv·cm²)。
    """

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
    lines = ["Energy_MeV,h_calc_pSv_cm2,h_ref_pSv_cm2,deviation_pct,pass,source"]
    for e, h_calc, h_ref, dev in results:
        ok = "PASS" if abs(dev) <= 10 else "FAIL"
        lines.append(f"{e:.3f},{h_calc:.4f},{h_ref:.4f},{dev:.1f},{ok},MCNP")
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
    results   = []   # (energy, h_calc, h_ref, deviation%)
    skipped   = []   # 因数据不可用跳过的能量点

    for energy in ENERGIES:
        npy_name = f"fluence_E{energy:.3f}MeV.npy"
        npy_path = out_dir / npy_name

        if not npy_path.exists():
            print(f"\n  [跳过] 找不到 {npy_path}")
            print(f"  请先运行 Step2b 完成 MCNP 计算")
            skipped.append(energy)
            continue

        print(f"\n  -- E = {energy:.3f} MeV  [{npy_name}] --")
        fluence_npy = np.load(npy_path)
        print(f"     fluence shape={fluence_npy.shape}  "
              f"max={fluence_npy.max():.3e}  mean={fluence_npy.mean():.3e}")

        if not is_data_reliable(fluence_npy):
            print(f"     [数据检验] 检测到无效数据（max约1e-5，CV约0.577，疑为随机数）")
            print(f"     原因：MCNP 运行失败——很可能缺少光子截面库（如 .70p 未在 xsdir 中）")
            print(f"     请检查 D:\\LANL\\xsdir 是否包含所需光子库，")
            print(f"     或用 --phot-lib 参数指定实际可用的截面库后缀（如 .04p）")
            print(f"     并重新运行 Step2b")
            skipped.append(energy)
            continue

        fluence_ready = prepare_mcnp_fluence(fluence_npy, mask)
        print(f"     [数据检验] 通过 -> 使用 MCNP 结果")

        h_calc, organ_table = compute_h_eff_from_fluence(
            fluence_ready, mask, organs, energy)
        h_ref = ICRP116_REF[energy]
        dev   = (h_calc - h_ref) / h_ref * 100

        print_organ_table(organ_table, energy)

        flag = "OK" if abs(dev) <= 10 else ("~" if abs(dev) <= 20 else "FAIL")
        print(f"\n  [MCNP] h_E(calc)={h_calc:.4f}  h_E(ICRP-116)={h_ref:.4f}  "
              f"dev={dev:+.1f}%  {flag}")

        results.append((energy, h_calc, h_ref, dev))

    if skipped:
        print(f"\n[警告] 以下能量点因数据不可用已跳过: {skipped}")

    if not results:
        print("\n[错误] 没有可用的 MCNP 结果。")
        print("  请确认:")
        print("  1. Step2b 已成功完成（fluence_E*.npy 存在且非空）")
        print("  2. MCNP5 xsdir 包含所用光子截面库（默认 .70p）")
        print("     若无 .70p，检查 xsdir 中可用库后用 --phot-lib 重新生成输入文件")
        sys.exit(1)

    # ── 汇总表格 ─────────────────────────────────────────────
    print("\n" + "=" * 65)
    print(f"  {'能量(MeV)':<12} {'h_计算':>12} {'h_ICRP-116':>12} {'偏差':>8}  判定")
    print("  " + "-" * 60)
    passed = 0
    for e, hc, hr, d in results:
        ok  = abs(d) <= 10
        sym = "PASS" if ok else ("~<20%" if abs(d) <= 20 else "FAIL")
        print(f"  {e:<12.3f} {hc:>12.4f} {hr:>12.4f} {d:>+7.1f}%  {sym}")
        if ok:
            passed += 1
    print("  " + "-" * 60)
    print(f"  通过率（±10%）: {passed}/{len(results)}")
    print("=" * 65)

    # ── 保存 CSV ──────────────────────────────────────────────
    save_csv(results, out_dir)

    # ── 绘图 ─────────────────────────────────────────────────
    if not args.no_plot:
        try_plot(results, out_dir)

    print("\n完成！结果文件位于:", out_dir)


if __name__ == "__main__":
    main()
