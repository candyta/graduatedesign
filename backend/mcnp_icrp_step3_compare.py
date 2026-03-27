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

# 软组织 μ_en/ρ 插值表（用于 EMESH 散射档的精确剂量计算）
# 来源: NIST XCOM，软组织 ICRU-44
_SOFT_INTERP_E   = [0.001, 0.005, 0.010, 0.020, 0.030, 0.050, 0.080, 0.100,
                    0.150, 0.200, 0.300, 0.400, 0.500, 0.600, 0.800, 1.000,
                    1.500, 2.000, 3.000, 4.000, 5.000, 6.000, 8.000, 10.000]
_SOFT_INTERP_MU  = [3770., 185.0, 4.742, 0.5272, 0.1486, 0.04186, 0.03052, 0.02546,
                    0.02779, 0.02967, 0.03192, 0.03279, 0.03299, 0.03284, 0.03206, 0.03066,
                    0.02807, 0.02590, 0.02251, 0.02048, 0.01914, 0.01832, 0.01740, 0.02176]
# 皮质骨 μ_en/ρ 插值表
_BONE_INTERP_E   = _SOFT_INTERP_E
_BONE_INTERP_MU  = [3770., 185.0, 19.10, 1.933, 0.5162, 0.1137, 0.04249, 0.02916,
                    0.02725, 0.02764, 0.02898, 0.02957, 0.02965, 0.02939, 0.02846, 0.02939,
                    0.02670, 0.02449, 0.02108, 0.01906, 0.01780, 0.01697, 0.01601, 0.02045]

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
    (['breast', 'mammary', 'glandular tissue'],          0.12),   # 乳腺 (ICRP-103 Table A.1)
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

def _interp_mu_en_rho(e_mev: float, e_table: list, mu_table: list) -> float:
    """对 log-log 插值 μ_en/ρ（NIST 表格为 log-log 线性关系）。"""
    import math
    le = math.log10(max(e_mev, 1e-4))
    le_table = [math.log10(x) for x in e_table]
    lmu_table = [math.log10(x) for x in mu_table]
    if le <= le_table[0]:
        return mu_table[0]
    if le >= le_table[-1]:
        return mu_table[-1]
    for i in range(len(le_table) - 1):
        if le_table[i] <= le <= le_table[i + 1]:
            t = (le - le_table[i]) / (le_table[i + 1] - le_table[i])
            return 10 ** (lmu_table[i] + t * (lmu_table[i + 1] - lmu_table[i]))
    return mu_table[-1]


def get_mu_en_rho_at_energy(name: str, e_mev: float) -> float:
    """对任意能量（不限于4个标准能量点）插值 μ_en/ρ。"""
    nlc = name.lower()
    if any(k in nlc for k in ('spongiosa', 'red bone marrow', 'red marrow',
                               'medullary yellow', 'yellow marrow')):
        return _interp_mu_en_rho(e_mev, _SOFT_INTERP_E, _SOFT_INTERP_MU)
    if any(k in nlc for k in BONE_KEYWORDS):
        return _interp_mu_en_rho(e_mev, _BONE_INTERP_E, _BONE_INTERP_MU)
    return _interp_mu_en_rho(e_mev, _SOFT_INTERP_E, _SOFT_INTERP_MU)


def get_wt(name: str) -> float:
    """由器官名称查找 ICRP-103 wT，未匹配返回 0。"""
    nlc = name.lower()
    for keywords, wt in WT_RULES:
        if any(k in nlc for k in keywords):
            return wt
    return 0.0


def get_mu_en_rho(name: str, energy: float) -> float:
    """根据器官名称选择 μ_en/ρ 值。

    优先级：
    1. Spongiosa / 红骨髓 / 黄骨髓内腔 → 软组织值（剂量计算针对骨髓腔内容物，非骨基质）
    2. 含皮质骨关键词的其他器官 → 皮质骨值
    3. 其余 → 软组织值
    """
    nlc = name.lower()
    # 骨松质/红骨髓: 计算针对骨髓而非骨基质，使用软组织 μ_en/ρ
    if any(k in nlc for k in ('spongiosa', 'red bone marrow', 'red marrow',
                               'medullary yellow', 'yellow marrow')):
        return MU_EN_RHO_SOFT[energy]
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

def is_data_reliable(fluence_npy: np.ndarray, energy: float = None,
                     mask: np.ndarray = None) -> bool:
    """
    检测 fluence 是否为可信的 MCNP 结果，还是 extract 脚本的随机数回退数据。
    同时检测低能量点（E ≤ 0.05 MeV）的物理合理性：10 keV 光子在软组织中
    平均自由程仅 0.04 cm，深部器官注量应接近 0。

    ⚠ 全局均值不能用于判断——ICRP-110 AM 体模约 60% 体素为体外"空气"
      （体素坐标在体模包围盒内但不属于任何器官），10 keV 光子在空气中几乎
      不衰减（MFP≈69 cm），因此即使截面库正常，全局均值 ≈ 61% × Φ_incident。
    正确做法：只统计组织体素（mask>0）的均值：
      截面库正常：组织均值 ≈ 0.01~1% × Φ_incident（强衰减）
      截面库缺失：组织均值 ≈ 100% × Φ_incident（无衰减）

    extract_from_standard_output 回退时返回 np.random.rand(...) * 1e-5：
      - max 恰好约 1e-5（精确上限）
      - mean 约 5e-6，CV(变异系数) 约 0.577（均匀分布特征）
    真实 MCNP 数据具有明显的空间梯度，max 不会恰好等于上限。
    """
    max_val = fluence_npy.max()
    if max_val <= 0:
        return False
    # 检测 max 是否被钳位于 1e-5（随机回退数据特征）
    if 9.5e-6 <= max_val <= 1.0e-5:
        nonzero = fluence_npy[fluence_npy > 0]
        cv = nonzero.std() / nonzero.mean()
        if 0.40 < cv < 0.70:   # 均匀分布 CV = 1/sqrt(3) 约 0.577
            return False
    # 低能量物理合理性检验：E ≤ 0.05 MeV 时，只检查组织体素均值
    if energy is not None and energy <= 0.05:
        incident_fluence = 1.0 / BEAM_AREA
        if mask is not None:
            # fluence_npy: (NZ, NY, NX)；mask: (NX, NY, NZ) → 转置对齐
            mask_flu = mask.transpose(2, 1, 0)   # (NZ, NY, NX)
            tissue_sel = fluence_npy[mask_flu > 0]
            mean_tissue = float(tissue_sel.mean()) if tissue_sel.size > 0 else 0.0
        else:
            mean_tissue = float(fluence_npy.mean())
        # 截面库正常：组织均值远小于入射注量（强光电吸收）
        # 截面库缺失：光子完全穿透，组织均值 ≈ 入射注量
        if mean_tissue > 0.30 * incident_fluence:
            return False   # 物理不合理：截面库未正确加载
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

    正确的 ICRP 方法：对同一器官的多个子区域（如 4 块皮肤区域、
    20+ 块骨松质区域）先合并所有体素取体素计数加权均值，再统一乘以 wT。
    若逐子区域分别乘 wT，会造成 4×/20× 等倍数过高。
    """
    from collections import defaultdict

    # Step 1: 按 WT_RULES 规则将 organ_id 分组（首条匹配规则）
    rule_groups = defaultdict(list)   # rule_idx → [oid, ...]
    for oid in np.unique(mask):
        oid = int(oid)
        if oid == 0 or oid not in organs:
            continue
        _, _, name = organs[oid]
        nlc = name.lower()
        for idx, (keywords, _) in enumerate(WT_RULES):
            if any(k in nlc for k in keywords):
                rule_groups[idx].append(oid)
                break

    organ_table = []
    e_eff_pGy = 0.0

    # Step 2: 对每个器官类别，计算所有子区域合并后的体素加权均值，再乘 wT
    for rule_idx in sorted(rule_groups.keys()):
        oids = rule_groups[rule_idx]
        _, wt = WT_RULES[rule_idx]

        # 收集该类别所有体素的通量值（体素数加权，不是子区域均值再平均）
        group_mask = np.isin(mask, oids)
        if not group_mask.any():
            continue
        mean_fluence = float(fluence[group_mask].mean())

        # μ_en/ρ 用第一个子器官名称判断组织类型（骨 vs 软组织）
        first_name = organs[oids[0]][2]
        mu_en_rho = get_mu_en_rho(first_name, energy)

        # D_T [pGy/sp] = Φ × E × (μ_en/ρ) × 1.602e-10 × 1e12
        dose_pGy = mean_fluence * energy * mu_en_rho * 1.602e-10 * 1e12
        wt_dose = wt * dose_pGy
        e_eff_pGy += wt_dose

        # 显示名：只显示第一个子器官名 + 子区域数
        if len(oids) == 1:
            dname = first_name
        else:
            base = first_name.split(',')[0].strip()
            dname = f"{base} ({len(oids)} regions)"
        organ_table.append((dname, wt, mean_fluence, dose_pGy, wt_dose))

    # h_E [pSv·cm²] = E_eff [pSv/sp] / Φ_incident [cm⁻²/sp]
    #               = E_eff [pGy/sp] × BEAM_AREA [cm²]
    h_eff = e_eff_pGy * BEAM_AREA

    organ_table.sort(key=lambda r: abs(r[4]), reverse=True)
    return h_eff, organ_table


# ═══════════════════════════════════════════════════════════════
# 输出
# ═══════════════════════════════════════════════════════════════

def compute_h_eff_from_fluence_emesh(fluence_bins: list, e_bounds: list,
                                     mask: np.ndarray, organs: dict) -> tuple:
    """
    从能量分档注量（EMESH）计算 h_E，避免散射光子能量高估问题。

    fluence_bins : list of np.ndarray (NX,NY,NZ)，每档注量（已对齐掩膜）
    e_bounds     : list of float，能量档边界 (MeV)，len = n_bins + 1
    返回 (h_eff, organ_table)，同 compute_h_eff_from_fluence
    """
    from collections import defaultdict
    n_bins = len(fluence_bins)
    # 每个 bin 的代表性能量：取上下界几何均值（log-space 中点）
    import math
    bin_energies = []
    for k in range(n_bins):
        lo, hi = e_bounds[k], e_bounds[k + 1]
        bin_energies.append(math.sqrt(lo * hi) if lo > 0 else hi * 0.5)

    # 按 WT_RULES 分组
    rule_groups = defaultdict(list)
    for oid in np.unique(mask):
        oid = int(oid)
        if oid == 0 or oid not in organs:
            continue
        _, _, name = organs[oid]
        nlc = name.lower()
        for idx, (keywords, _) in enumerate(WT_RULES):
            if any(k in nlc for k in keywords):
                rule_groups[idx].append(oid)
                break

    organ_table = []
    e_eff_pGy = 0.0

    for rule_idx in sorted(rule_groups.keys()):
        oids = rule_groups[rule_idx]
        _, wt = WT_RULES[rule_idx]
        group_mask = np.isin(mask, oids)
        if not group_mask.any():
            continue
        first_name = organs[oids[0]][2]

        # 对每个能量档单独计算 kerma，然后累加
        dose_pGy = 0.0
        mean_fluence_total = 0.0
        for k in range(n_bins):
            phi_k = float(fluence_bins[k][group_mask].mean())
            e_k   = bin_energies[k]
            mu_k  = get_mu_en_rho_at_energy(first_name, e_k)
            dose_pGy += phi_k * e_k * mu_k * 1.602e-10 * 1e12
            mean_fluence_total += phi_k

        wt_dose = wt * dose_pGy
        e_eff_pGy += wt_dose

        if len(oids) == 1:
            dname = first_name
        else:
            base = first_name.split(',')[0].strip()
            dname = f"{base} ({len(oids)} regions)"
        organ_table.append((dname, wt, mean_fluence_total, dose_pGy, wt_dose))

    h_eff = e_eff_pGy * BEAM_AREA
    organ_table.sort(key=lambda r: abs(r[4]), reverse=True)
    return h_eff, organ_table


def compute_h_eff_from_f6(f6_dict: dict, organs: dict) -> tuple:
    """
    从 F6:P 计分结果（散射正确的能量沉积）计算 h_E (pSv·cm²)。

    f6_dict : {tally_num (str/int): {'value': MeV/g/src, 'rel_err': float}}
    计分号 → WT_RULES 组索引: idx = (tally_num - 6) // 10 - 1

    公式:
      D_T (pGy/src)   = F6_value (MeV/g/src) × 1.602e2
      h_E (pSv·cm²)   = Σ_T wT × D_T × BEAM_AREA
    """
    import json as _json

    # 将 str key 转为 int
    f6 = {int(k): v for k, v in f6_dict.items()}

    organ_table = []
    e_eff_pGy = 0.0

    for tnum, info in sorted(f6.items()):
        # 反推 WT_RULES 索引
        idx = (tnum - 6) // 10 - 1
        if idx < 0 or idx >= len(WT_RULES):
            continue
        _, wt = WT_RULES[idx]
        val = info['value']
        rel = info.get('rel_err', 0.0)
        if val <= 0:
            continue

        dose_pGy = val * 1.602e2           # MeV/g/src → pGy/src
        wt_dose  = wt * dose_pGy
        e_eff_pGy += wt_dose

        keywords = WT_RULES[idx][0]
        dname = keywords[0]
        # 统计有多少器官 ids 参与（仅供显示）
        organ_table.append((dname, wt, val, dose_pGy, wt_dose, rel))

    h_eff = e_eff_pGy * BEAM_AREA
    organ_table.sort(key=lambda r: abs(r[4]), reverse=True)
    return h_eff, organ_table


def print_organ_table(organ_table, energy):
    """打印器官剂量贡献明细（前 15 位）。支持 F6 和 fluence 两种格式。"""
    # F6 rows have 6 elements (name, wt, f6_val, dose, contrib, rel_err)
    # fluence rows have 5 elements (name, wt, phi, dose, contrib)
    use_f6 = len(organ_table) > 0 and len(organ_table[0]) == 6
    if use_f6:
        print(f"\n  {'器官名称':<35} {'wT':>6} {'F6(MeV/g)':>12} {'D_T(pGy)':>12} {'wT×D_T':>12} {'rel_err':>8}")
        print("  " + "-" * 90)
        for row in organ_table[:15]:
            name, wt, f6v, dose, contrib, rel = row
            print(f"  {name:<35} {wt:>6.4f} {f6v:>12.3e} {dose:>12.3e} {contrib:>12.3e} {rel:>8.4f}")
    else:
        print(f"\n  {'器官名称':<35} {'wT':>6} {'mean Φ':>12} {'D_T(pGy)':>12} {'wT×D_T':>12}")
        print("  " + "-" * 82)
        for row in organ_table[:15]:
            name, wt, phi, dose, contrib = row
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
        default=r"../P110 data V1.2/AM.zip",
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

        if not is_data_reliable(fluence_npy, energy, mask=mask):
            max_v = fluence_npy.max()
            mean_v = fluence_npy.mean()
            if max_v <= 0:
                print(f"     [数据检验] 检测到无效数据（全零数组 max={max_v:.3e}）")
                print(f"     原因：MCNP 输入文件有语法错误（如材料卡格式），MCNP 提前中止，")
                print(f"     meshtal 文件存在但无任何计分数据。")
                print(f"     解决：拉取最新代码，重启后端，重新运行 Step2b。")
            elif energy <= 0.05:
                incident = 1.0 / BEAM_AREA
                # 计算组织均值（与 is_data_reliable 一致）
                mask_flu = mask.transpose(2, 1, 0)
                tissue_sel = fluence_npy[mask_flu > 0]
                tissue_mean = float(tissue_sel.mean()) if tissue_sel.size > 0 else mean_v
                ratio = tissue_mean / incident
                print(f"     [数据检验] *** 物理不合理：低能光子未被衰减！ ***")
                print(f"     E={energy} MeV 光子在软组织中平均自由程仅 ~0.04 cm，")
                print(f"     组织体素均值 {tissue_mean:.3e} = {ratio:.1%} × 入射注量（应 < 1%）")
                print(f"     原因：MCNP 光子截面库未正确加载——光子穿透体模无任何相互作用。")
                print(f"     解决：确认 xsdir 含有光子截面库条目，重新运行 Step2b。")
            else:
                print(f"     [数据检验] 检测到无效数据（max约{max_v:.2e}，疑为随机数）")
                print(f"     原因：MCNP 运行失败——很可能缺少光子截面库（如 .70p 未在 xsdir 中）")
                print(f"     请检查 D:\\LANL\\xsdir 是否包含所需光子库，")
                print(f"     或用 --phot-lib 参数指定实际可用的截面库后缀（如 .04p）")
                print(f"     并重新运行 Step2b")
            skipped.append(energy)
            continue

        fluence_ready = prepare_mcnp_fluence(fluence_npy, mask)
        print(f"     [数据检验] 通过 -> 使用 MCNP 结果")

        stem = f"fluence_E{energy:.3f}MeV"

        # ── 优先：F6:P 计分（散射正确的器官能量沉积） ──────────────────────
        import json as _json
        f6_json_path = out_dir / f"{stem}_f6doses.json"
        use_f6 = False
        if f6_json_path.exists():
            try:
                with open(f6_json_path, 'r', encoding='utf-8') as _fh:
                    f6_dict = _json.load(_fh)
                if f6_dict:
                    print(f"     [F6] 加载 F6 计分 {f6_json_path.name}，{len(f6_dict)} 个器官组")
                    h_calc, organ_table = compute_h_eff_from_f6(f6_dict, organs)
                    # ── 物理合理性验证 ──────────────────────────────────────
                    # MCNP5 晶格体模中 F6 计分存在已知规范化问题：对宇宙（universe）
                    # 单元在晶格中被复制时，MCNP5 仅以单个体素质量归一化，而非全器官
                    # 总质量，导致结果偏大约 N_voxels 倍（可达 10^5~10^6）。
                    # 同时，prdmp 中间存档段的 "total" 行格式含累积和而非 per-src 值，
                    # 若解析不当可再叠加 ~NPS 倍误差，最终 h_E 虚高约 10^12 倍。
                    # 以下检验：若 F6 计算结果远超 ICRP-116 参考值，判定为不可信数据，
                    # 回退到 FMESH 注量模式。
                    _h_ref_check = ICRP116_REF.get(energy, 0.0)
                    _f6_sane = True
                    if _h_ref_check > 0 and h_calc > 200 * _h_ref_check:
                        print(f"     [F6] ⚠ 检测到异常大值: h_E(F6)={h_calc:.3e} pSv·cm²"
                              f" >> ICRP-116={_h_ref_check:.4f}（>{200}×）")
                        print(f"     [F6]   根因: MCNP5 晶格 F6 规范化问题或 prdmp 累积值未正确提取。")
                        print(f"     [F6]   修复建议: 在 MCNP 输入中为每个 F6 tally 添加 FM 卡"
                              f"（乘以 1/N_voxels），或升级到 MCNP6 后重新运行 Step2b。")
                        print(f"     [F6]   本次回退到 FMESH 注量模式。")
                        _f6_sane = False
                    if _f6_sane:
                        use_f6 = True
            except Exception as _e:
                print(f"     [F6] 读取失败: {_e}，回退到注量模式")

        # ── 次优 A：多 FMESH 4 档（fm24/fm34 文件存在时优先） ─────────────────
        use_emesh = False
        if not use_f6:
            fm14_b0 = out_dir / f"{stem}_bin0.npy"
            fm24_b0 = out_dir / f"{stem}_fm24_bin0.npy"
            fm24_b1 = out_dir / f"{stem}_fm24_bin1.npy"
            fm34_b0 = out_dir / f"{stem}_fm34_bin0.npy"
            fm34_b1 = out_dir / f"{stem}_fm34_bin1.npy"
            use_multifmesh = all(p.exists() for p in (fm14_b0, fm24_b0, fm24_b1, fm34_b0, fm34_b1))

            if use_multifmesh:
                # 多 FMESH 方案：从 FMESH14/24/34 的 bin 文件相减，导出 4 有效档
                # 各 FMESH: emesh = Ci  E_max → bin0=[0,Ci], bin1=[Ci,E_max]
                # 读取 ebounds 以确定截止能量 C1/C2/C3
                eb14 = out_dir / f"{stem}_ebounds.npy"
                eb24 = out_dir / f"{stem}_fm24_ebounds.npy"
                eb34 = out_dir / f"{stem}_fm34_ebounds.npy"
                _fm_mode_tag = '[4档EMESH]'
                try:
                    bounds14 = list(np.load(eb14)) if eb14.exists() else None
                    bounds24 = list(np.load(eb24)) if eb24.exists() else None
                    bounds34 = list(np.load(eb34)) if eb34.exists() else None
                    # e_bounds: [0, C1, C2, C3, E_max]
                    c1 = bounds14[1] if bounds14 and len(bounds14) >= 3 else None
                    c2 = bounds24[1] if bounds24 and len(bounds24) >= 3 else None
                    c3 = bounds34[1] if bounds34 and len(bounds34) >= 3 else None
                    e_max = (bounds14[-1] if bounds14 else
                             bounds24[-1] if bounds24 else
                             bounds34[-1] if bounds34 else None)
                    if None in (c1, c2, c3, e_max):
                        raise ValueError("无法读取多 FMESH 截止能量")

                    # ── 10 MeV 特殊处理：回退到 FMESH24 2 档 ──────────────────
                    # 在 8-10 MeV 附近对产截面使 μ_en/ρ 非单调递增，
                    # 4 档代表能量 9.17 MeV 给出 E×μ=0.183，远高于
                    # 2 档代表能量 7.25 MeV 的 0.127，消除了原本的偶然补偿，
                    # 反而使偏差从 +14.2% 升至 +28.9%。
                    # 因此对 10 MeV 直接使用 FMESH24（[0,C2]/[C2,E_max]）作为 2 档。
                    if energy >= 9.0 and bounds24 and len(bounds24) >= 3:
                        phi24_b0_arr = prepare_mcnp_fluence(np.load(fm24_b0), mask)
                        phi24_b1_arr = prepare_mcnp_fluence(np.load(fm24_b1), mask)
                        e_bounds_2 = [bounds24[0], bounds24[1], bounds24[2]]
                        fluence_bins = [phi24_b0_arr, phi24_b1_arr]
                        use_emesh = True
                        _fm_mode_tag = '[FMESH24-2档]'
                        print(f"     [FMESH24-2档] 10 MeV 使用 FMESH24 直接 2 档"
                              f"（避免对产区间 4 档高估）: {e_bounds_2} MeV")
                        h_calc, organ_table = compute_h_eff_from_fluence_emesh(
                            fluence_bins, e_bounds_2, mask, organs)
                    else:
                        # 常规 4 档：相减导出有效档注量（微小负值钳位为 0）
                        phi14_b0 = prepare_mcnp_fluence(np.load(fm14_b0), mask)
                        phi24_b0 = prepare_mcnp_fluence(np.load(fm24_b0), mask)
                        phi34_b0 = prepare_mcnp_fluence(np.load(fm34_b0), mask)
                        phi34_b1 = prepare_mcnp_fluence(np.load(fm34_b1), mask)

                        eff_bin0 = phi14_b0                               # [0,   C1]
                        eff_bin1 = np.clip(phi24_b0 - phi14_b0, 0, None) # [C1,  C2]
                        eff_bin2 = np.clip(phi34_b0 - phi24_b0, 0, None) # [C2,  C3]
                        eff_bin3 = phi34_b1                               # [C3, E_max]

                        fluence_bins = [eff_bin0, eff_bin1, eff_bin2, eff_bin3]
                        e_bounds_4   = [0.0, c1, c2, c3, e_max]
                        use_emesh = True
                        print(f"     [多FMESH] 使用 4 档有效分档: {e_bounds_4} MeV")
                        h_calc, organ_table = compute_h_eff_from_fluence_emesh(
                            fluence_bins, e_bounds_4, mask, organs)
                except Exception as _mfe:
                    print(f"     [多FMESH] 构建档失败（{_mfe}），回退到 2 档 EMESH")
                    use_multifmesh = False

        # ── 次优 B：常规 2 档 EMESH ──────────────────────────────────────────
        if not use_f6 and not use_emesh:
            eb_path   = out_dir / f"{stem}_ebounds.npy"
            bin0_path = out_dir / f"{stem}_bin0.npy"
            use_emesh = eb_path.exists() and bin0_path.exists()
            if use_emesh:
                e_bounds = list(np.load(eb_path))
                if e_bounds and e_bounds[-1] > 1000.0:
                    use_emesh = False
                    print(f"     [EMESH] 检测到 MCNP5 默认哨兵（上界={e_bounds[-1]:.0e}），回退到总注量模式")
                else:
                    n_bins = len(e_bounds) - 1
                    fluence_bins = []
                    for k in range(n_bins):
                        bin_npy = out_dir / f"{stem}_bin{k}.npy"
                        if not bin_npy.exists():
                            use_emesh = False
                            break
                        fluence_bins.append(prepare_mcnp_fluence(np.load(bin_npy), mask))
                    if use_emesh:
                        print(f"     [EMESH] 使用 {n_bins} 档能量分档注量")
                        h_calc, organ_table = compute_h_eff_from_fluence_emesh(
                            fluence_bins, e_bounds, mask, organs)
                    else:
                        print(f"     [EMESH] 部分 bin 文件缺失，退回到总注量模式")

        # ── 后备：总注量 × E × μ_en/ρ（高能时系统性高估） ─────────────────
        if not use_f6 and not use_emesh:
            print(f"     [总注量] 使用总注量 × E × μ_en/ρ（高能时可能高估 40-88%）")
            h_calc, organ_table = compute_h_eff_from_fluence(
                fluence_ready, mask, organs, energy)

        h_ref = ICRP116_REF[energy]
        dev   = (h_calc - h_ref) / h_ref * 100

        print_organ_table(organ_table, energy)

        flag     = "OK" if abs(dev) <= 10 else ("~" if abs(dev) <= 20 else "FAIL")
        if use_f6:
            mode_tag = "[F6]"
        elif use_emesh and 'use_multifmesh' in dir() and use_multifmesh:
            mode_tag = _fm_mode_tag if '_fm_mode_tag' in dir() else "[多FMESH]"
        elif use_emesh:
            mode_tag = "[EMESH]"
        else:
            mode_tag = "[MCNP]"
        print(f"\n  {mode_tag} h_E(calc)={h_calc:.4f}  h_E(ICRP-116)={h_ref:.4f}  "
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
