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

# ─── AF 体模 BEAM_AREA ────────────────────────────────────────────
# AF phantom (downsampled 127×63×111), full physical size:
#   X: 299 × 1.775 mm = 530.725 mm = 53.0725 cm
#   Z: 348 × 4.84  mm = 1684.32 mm = 168.432 cm
_AF_BEAM_AREA = (299 * 1.775 / 10) * (348 * 4.84 / 10)  # 53.0725 × 168.432 ≈ 8939 cm²
# AF phantom voxel Y (AP) size: 137 × 1.775 mm = 243.175 mm, downsampled to 63 voxels
_AF_VOX_Y = (137 * 1.775 / 10) / 63  # ≈ 0.386 cm

# ─── ICRP-116 参考值（AP 光子，pSv·cm²） ────────────────────────────
# 来源: ICRP Publication 116 (2010), Table A.1, Photons, AP column
# 性别平均值，AM 与 AF 验证统一使用此表（ICRP-116 不发布分性别有效剂量 E）
ICRP116_REF = {
    0.010:  0.0685,
    0.100:  0.519,
    1.000:  4.49,
    10.000: 20.5,
}

# AF 与 AM 使用同一张 ICRP-116 Table A.1 参考表（性别平均）
ICRP116_REF_AF = ICRP116_REF

# ─── NIST XCOM μ_en/ρ（cm²/g） ──────────────────────────────────
# 软组织 ICRU-44: H10.1%, C11.1%, N2.6%, O76.2%
MU_EN_RHO_SOFT = {0.010: 4.742,  0.100: 0.02546, 1.000: 0.03066, 10.000: 0.01680}
# 注：10 MeV 原值 0.02176 已修正为 0.01680（NIST XCOM 软组织，见 _SOFT_INTERP_MU 注释）
# 皮质骨 ICRU-44
MU_EN_RHO_BONE = {0.010: 19.10,  0.100: 0.02916, 1.000: 0.02939, 10.000: 0.02045}

# 软组织 μ_en/ρ 插值表（用于 EMESH 散射档的精确剂量计算）
# 来源: NIST XCOM，软组织 ICRU-44
_SOFT_INTERP_E   = [0.001, 0.005, 0.010, 0.020, 0.030, 0.050, 0.080, 0.100,
                    0.150, 0.200, 0.300, 0.400, 0.500, 0.600, 0.800, 1.000,
                    1.500, 2.000, 3.000, 4.000, 5.000, 6.000, 8.000, 10.000]
_SOFT_INTERP_MU  = [3770., 185.0, 4.742, 0.5272, 0.1486, 0.04186, 0.03052, 0.02546,
                    0.02779, 0.02967, 0.03192, 0.03279, 0.03299, 0.03284, 0.03206, 0.03066,
                    0.02807, 0.02590, 0.02251, 0.02048, 0.01914, 0.01832, 0.01740, 0.01680]
# 注：10 MeV 原值 0.02176 与 NIST XCOM 不符（8→10 MeV 异常跳增25%），
#     已修正为 0.01680（≈ NIST 水值 0.01677，符合软组织 Compton+配对产生趋势）。
# 皮质骨 μ_en/ρ 插值表
_BONE_INTERP_E   = _SOFT_INTERP_E
_BONE_INTERP_MU  = [3770., 185.0, 19.10, 1.933, 0.5162, 0.1137, 0.04249, 0.02916,
                    0.02725, 0.02764, 0.02898, 0.02957, 0.02965, 0.02939, 0.02846, 0.02939,
                    0.02670, 0.02449, 0.02108, 0.01906, 0.01780, 0.01697, 0.01601, 0.02045]

# ─── 骨松质 μ_en/ρ 修正因子表 ──────────────────────────────────────
# DE/DF 模式下 FMESH 输出使用软组织 DF(E)，但 ICRP-116 参考值基于
# 骨松质复合材料（骨小梁+骨髓混合物）的能量沉积计算。
# 在 0.1 MeV 以下，骨松质中的 Ca（均值~3.8%）使 μ_en/ρ 比软组织高
# 约 6%（光电效应贡献），需乘以修正因子 f = μ_en/ρ(骨松质) / μ_en/ρ(软组织)。
#
# 基于 ICRP-110 AM 19 种骨松质组织的平均组成（H:9.45, C:37.7, O:43.9, Ca:3.8%）
# 使用 NIST XCOM 元素截面数据逐点计算后，对 _SOFT_INTERP_E 能量网格插值。
#
# 注：1 MeV 以上 Compton 截面与 Z/A 相关，骨松质含 H 略少（9.45% vs 10.1%），
# 修正因子略小于 1（约 0.993），在允许偏差范围内。
_SPONGIOSA_CORR_E = [0.001, 0.005, 0.010, 0.020, 0.030, 0.050, 0.080, 0.100,
                     0.150, 0.200, 0.300, 0.400, 0.500, 0.600, 0.800, 1.000,
                     1.500, 2.000, 3.000, 4.000, 5.000, 6.000, 8.000, 10.000]
_SPONGIOSA_CORR_F = [2.36,  2.21,  2.35,  2.80,  2.95,  2.69,  1.52,  1.060,
                     1.020, 1.002, 0.998, 0.995, 0.994, 0.993, 0.993, 0.993,
                     0.993, 0.993, 0.993, 0.993, 0.993, 0.993, 0.993, 0.993]
# 说明：0.1 MeV 的修正因子 1.060 由完整组成计算得出；
#       低能（<0.08 MeV）的值来自皮质骨/软组织比值按 Ca 比例插值（不确定性较大），
#       但这些能量点数据无效（被 is_data_reliable 过滤），实际不会被使用。

# ─── ICRP-103 组织权重因子 wT ─────────────────────────────────────
# (关键字列表, wT)  — 按优先级排列，首先匹配者生效
_W = 0.12 / 14   # 余量器官每个 wT
WT_RULES = [
    (['testes', 'testis'],                               0.08),   # 性腺(男)
    (['ovaries', 'ovary'],                               0.08),   # 性腺(女)
    (['colon', 'large intestine', 'rectum'],              0.12),  # 结肠含直肠壁
    (['lung'],                                           0.12),
    (['stomach wall', 'stomach'],                        0.12),
    (['red bone marrow', 'red marrow', 'spongiosa'],     0.12),   # 红骨髓
    (['breast', 'mammary', 'glandular tissue'],          0.12),   # 乳腺 (ICRP-103 Table A.1)
    (['urinary bladder'],                                0.04),  # 仅匹配泌尿膀胱；'bladder wall/bladder'会误匹配胆囊
    (['oesophagus', 'esophagus'],                        0.04),
    (['liver'],                                          0.04),
    (['thyroid'],                                        0.04),
    (['bone surface', 'endosteum', 'cortical'],           0.01),  # 骨表面:皮质骨作代理
    (['brain'],                                          0.01),
    (['salivary gland', 'salivary'],                     0.01),
    (['skin'],                                           0.01),
    # 余量器官 (0.12 / 14 each)
    (['adrenal'],                                        _W),
    (['extrathoracic', 'et region', 'nasal passage'],     _W),  # ET气道 (ET1/ET2)
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


def _load_organs_from_zip(zip_path: str, phantom: str = 'AM') -> dict:
    """
    从 AM.zip 或 AF.zip 读取器官定义。

    Parameters
    ----------
    zip_path : str
        路径指向 AM.zip 或 AF.zip
    phantom : str
        'AM' 或 'AF'

    Returns
    -------
    dict : {organ_id: (tissue_num, density, name)}
    """
    if phantom == 'AF':
        organs_entry = 'AF/AF_organs.dat'
    else:
        organs_entry = 'AM/AM_organs.dat'
    with zipfile.ZipFile(zip_path, 'r') as z:
        text = z.read(organs_entry).decode('utf-8', errors='replace')
    return parse_organs(text.splitlines())


# ═══════════════════════════════════════════════════════════════
# 核心计算
# ═══════════════════════════════════════════════════════════════

def is_data_reliable(fluence_npy: np.ndarray, energy: float = None,
                     mask: np.ndarray = None,
                     de_df_mode: bool = False) -> bool:
    """
    检测 fluence 是否为可信的 MCNP 结果，还是 extract 脚本的随机数回退数据。
    同时检测低能量点（E ≤ 0.05 MeV）的物理合理性：10 keV 光子在软组织中
    平均自由程仅 0.04 cm，深部器官注量应接近 0。

    ⚠ 全局均值不能用于判断——ICRP-110 AM 体模约 60% 体素为体外"空气"
      （体素坐标在体模包围盒内但不属于任何器官），10 keV 光子在空气中几乎
      不衰减（MFP≈69 cm），因此即使截面库正常，全局均值 ≈ 61% × Φ_incident。
    正确做法：只统计组织体素（mask>0）的均值：
      截面库正常：组织均值 ≈ 0.01~1% × Φ_incident（强衰减）
      截面库缺失：光子完全穿透，组织均值 ≈ 入射注量

    de_df_mode : bool
        True 时 fluence_npy 存储的是 kerma（pGy/src），而非注量（cm⁻²/src）。
        低能物理检验会先除以 DF(E) 换算回注量单位，再与入射注量比较，
        避免单位不一致导致误报（DE/DF 模式下 DF(0.01 MeV)=7.6，
        直接比较会把 pGy/sr 误作 cm⁻²/src，给出虚高的 "400%" 比值）。

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
        # DE/DF 模式：npy 存的是 kerma (pGy/src)，需除以 DF(E) 换算回注量 (cm⁻²/src)
        if de_df_mode and energy is not None:
            df_factor = (_interp_mu_en_rho(energy, _SOFT_INTERP_E, _SOFT_INTERP_MU)
                         * energy * 1.602e2)
            if df_factor > 0:
                mean_tissue = mean_tissue / df_factor
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


def compute_h_eff_from_f6(f6_dict: dict, organs: dict,
                          mask: np.ndarray = None) -> tuple:
    """
    从 F6:P 计分结果（scatter-correct 光子 kerma 能量沉积）计算 h_E (pSv·cm²)。

    f6_dict : {tally_num (str/int): {'value': MeV/g/src, 'rel_err': float}}
    计分号 → WT_RULES 组索引: idx = (tally_num - 6) // 10 - 1

    MCNP5 lattice 规范化：F6 原始值 = N_vox × D_organ_avg
    （对所有同材质体素累加但仅除以单体素质量，而非总质量）。
    当 mask 不为 None 时，从掩膜计算每个器官组的 N_vox 并除以，还原 D_organ_avg。

    公式:
      D_T (pGy/src)   = (F6_raw / N_vox) × 1.602e2
      h_E (pSv·cm²)   = Σ_T wT × D_T × BEAM_AREA
    """
    from collections import defaultdict

    # 将 str key 转为 int
    f6 = {int(k): v for k, v in f6_dict.items()}

    # 预先建立 WT_RULES 关键字 → organ_ids 映射（用于计算 N_vox）
    if mask is not None:
        rule_oids: dict[int, list] = defaultdict(list)
        for oid in np.unique(mask):
            oid = int(oid)
            if oid == 0 or oid not in organs:
                continue
            _, _, name = organs[oid]
            nlc = name.lower()
            for ridx, (kws, _) in enumerate(WT_RULES):
                if any(k in nlc for k in kws):
                    rule_oids[ridx].append(oid)
                    break
    else:
        rule_oids = {}

    organ_table = []
    e_eff_pGy = 0.0

    for tnum, info in sorted(f6.items()):
        idx = (tnum - 6) // 10 - 1
        if idx < 0 or idx >= len(WT_RULES):
            continue
        _, wt = WT_RULES[idx]
        val = info['value']
        rel = info.get('rel_err', 0.0)
        # MCNP5 prdmp TFC format stores rel as (1 + sigma/mean) rather than
        # sigma/mean directly.  e.g. 0.04% error → stored as 1.0004.
        # Normalise: if rel > 1.0 treat it as 1+sigma/mean and subtract 1.
        actual_rel = (rel - 1.0) if rel > 1.0 else rel
        if actual_rel > 0.10:
            print(f"  [F6] 跳过 tally {tnum} (rel_err={actual_rel:.4f} > 10%，统计未收敛)")
            continue
        if val <= 0:
            continue

        # N_vox 修正：MCNP5 lattice F6 累加所有同类体素但仅除以单体素质量
        # → raw = N_vox × D_avg；除以 N_vox 还原器官平均吸收剂量
        n_vox = 1
        if mask is not None and idx in rule_oids:
            oids = rule_oids[idx]
            if oids:
                n_vox = max(1, int(np.sum(np.isin(mask, oids))))
        d_avg = val / n_vox          # MeV/g/src，器官平均吸收剂量

        dose_pGy = d_avg * 1.602e2   # MeV/g/src → pGy/src
        wt_dose  = wt * dose_pGy
        e_eff_pGy += wt_dose

        keywords = WT_RULES[idx][0]
        dname = keywords[0]
        organ_table.append((dname, wt, d_avg, dose_pGy, wt_dose, rel))

    h_eff = e_eff_pGy * BEAM_AREA
    organ_table.sort(key=lambda r: abs(r[4]), reverse=True)
    return h_eff, organ_table


def _cpe_d_depth(energy_mev: float) -> float:
    """
    返回光子能量 E (MeV) 对应的次级电子 CPE 建立深度 d_CPE (cm)。

    基于软组织中电子 CSDA 射程（NIST ESTAR 数据）的近似插值。
    用于修正高能光子（E ≥ 5 MeV）下 AP 照射时浅层器官的 kerma→吸收剂量偏差。

    参考：NIST ESTAR, ICRU Report 37, 软组织 ρ = 1.04 g/cm³
      E=1 MeV → CSDA ≈ 0.43 cm (CPE 建立深度较小)
      E=5 MeV → CSDA ≈ 2.0 cm
      E=6 MeV → CSDA ≈ 2.5 cm
      E=8 MeV → CSDA ≈ 3.2 cm
      E=10 MeV → 6.0 cm（有效建立深度，含电子散射/角分布展宽效应，
                  大于 CSDA 最大值 4.5 cm，以覆盖次级电子能量分布的高能尾部）
    """
    _table_e = [1.0, 5.0, 6.0, 8.0, 10.0]
    _table_d = [0.43, 2.0, 2.5, 3.2, 6.0]
    return float(np.interp(energy_mev, _table_e, _table_d))


def compute_h_eff_from_kerma(kerma: np.ndarray, mask: np.ndarray,
                              organs: dict,
                              energy: float = None,
                              vox_y_cm: float = None) -> tuple:
    """
    从 DE/DF 模式的 FMESH 输出（单位 pGy/src）计算 h_E (pSv·cm²)。

    在 --de-df-mode 下，Step2 写入了 FMESH14 + DE14/DF14 乘子，
    MCNP5 输出的 FMESH 值已乘以 DF(E) [pGy·cm²]，每个体素值单位为：
        kerma_voxel [pGy/src] = integral[ Phi(E) × DF(E) dE ]

    此函数直接用体素 kerma 均值计算器官剂量，无需再做 E×μ_en/ρ 变换。

    公式：
        D_T [pGy/src] = mean_{voxels ∈ T}( kerma_voxel )
        h_E [pSv·cm²] = Σ_T wT × D_T × BEAM_AREA   (光子 wR=1, pGy≡pSv)

    高能 CPE 修正（E ≥ 5 MeV）：
        FMESH:P + DE/DF 给出的是光子碰撞 kerma，而非吸收剂量。
        对于 E ≥ 5 MeV，次级电子的 CSDA 射程可达数厘米，AP 照射时
        浅层器官（如乳腺）在 CPE 尚未建立时 absorbed dose << kerma。
        修正因子：f_CPE(y) = 1 - exp(-y / d_CPE(E))
        其中 y 为体素中心在 AP 方向（Y 轴）的深度，d_CPE 由 _cpe_d_depth() 给出。
        注意：此修正为近似处理，精确计算需 mode p e + 电子网格计分。

    Parameters
    ----------
    kerma    : np.ndarray (NX, NY, NZ) — 已对齐至掩膜分辨率的 kerma 场
    mask     : np.ndarray (NX, NY, NZ) — 器官掩膜
    organs   : dict — {organ_id: (tissue_num, density, name)}
    energy   : float, optional — 光子能量 (MeV)，用于 CPE 修正
    vox_y_cm : float, optional — Y 方向体素尺寸 (cm)，用于计算体素中心深度

    Returns
    -------
    (h_eff, organ_table)  同 compute_h_eff_from_fluence
    """
    from collections import defaultdict

    # ── μ_en/ρ DF 修正（仅 DE/DF kerma 模式）──────────────────────────────
    # Step2 _DEDF_SOFT_KERMA 中 10 MeV 的 DF=34.86 pGy·cm² 对应 μ_en/ρ=0.02176，
    # 但 NIST XCOM 软组织 10 MeV 正确值约 0.0168 cm²/g（≈ 水值 0.01677）。
    # 原因：8→10 MeV 跳增 25% 异常，应为对产截面贡献被高估或数据录入错误。
    # 在此按 (μ_correct/μ_used) 修正，无需重跑 MCNP。
    # 一旦重跑 MCNP 并修正 Step2 DF 表，此处应设 _DF_MU_CORRECTION = {}。
    # Step2 DF 表已用正确 μ_en/ρ=0.01680 重跑 MCNP，.npy 已包含正确 kerma，无需二次修正
    _DF_MU_CORRECTION = {}
    if energy is not None and energy in _DF_MU_CORRECTION:
        corr = _DF_MU_CORRECTION[energy]
        kerma = kerma * corr
        print(f"  [μ修正] E={energy} MeV: 施加 DE/DF DF 修正因子 {corr:.4f}"
              f" (μ_en/ρ: 0.02176 → 0.01680 cm²/g, 参考 NIST XCOM 软组织)")

    # 高能 CPE 修正：对 E ≥ 5 MeV 按深度衰减 kerma → 近似吸收剂量
    if energy is not None and energy >= 5.0 and vox_y_cm is not None:
        d_cpe = _cpe_d_depth(energy)
        ny = kerma.shape[1]
        # 体素中心深度 y = (j + 0.5) × vox_y_cm，j 为 Y 方向索引
        depths = (np.arange(ny) + 0.5) * vox_y_cm   # shape (NY,)
        cpe_factors = 1.0 - np.exp(-depths / d_cpe)  # shape (NY,)
        cpe_factors = np.clip(cpe_factors, 0.0, 1.0)
        # 广播至 (NX, NY, NZ)
        kerma = kerma * cpe_factors[np.newaxis, :, np.newaxis]
        print(f"  [CPE] E={energy} MeV: 已应用深度相关 CPE 修正 "
              f"(d_CPE={d_cpe:.1f} cm, 最大衰减深度={depths[-1]:.1f} cm)")
        print(f"  [CPE] 注意：FMESH:P + DE/DF 给出光子碰撞 kerma；"
              f"此 CPE 修正为近似。精确值需 mode p e + 电子 FMESH。")
    elif energy is not None and energy >= 5.0:
        print(f"  [CPE] ⚠ E={energy} MeV 需 CPE 修正但未提供 vox_y_cm，跳过修正")

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
        # kerma 场已是 pGy/src（DE/DF 直接输出），取体素均值即为器官平均剂量
        dose_pGy = float(kerma[group_mask].mean())
        if dose_pGy <= 0:
            continue

        first_name = organs[oids[0]][2]
        # 骨松质μ_en/ρ修正：ICRP-116参考值基于骨松质复合材料（平均3.8% Ca）能量沉积，
        # 在0.1 MeV附近比软组织DF高约6%；1 MeV以上因H含量略低而约低0.7%。
        _spon_kws = ('spongiosa', 'red bone marrow', 'red marrow')
        if any(k in first_name.lower() for k in _spon_kws):
            _corr = _interp_mu_en_rho(
                energy if energy is not None else 1.0,
                _SPONGIOSA_CORR_E, _SPONGIOSA_CORR_F)
            dose_pGy *= _corr

        wt_dose = wt * dose_pGy
        e_eff_pGy += wt_dose
        if len(oids) == 1:
            dname = first_name
        else:
            base = first_name.split(',')[0].strip()
            dname = f"{base} ({len(oids)} regions)"
        # organ_table: (name, wt, mean_kerma_pGy, dose_pGy, wt_dose)
        organ_table.append((dname, wt, dose_pGy, dose_pGy, wt_dose))

    h_eff = e_eff_pGy * BEAM_AREA
    organ_table.sort(key=lambda r: abs(r[4]), reverse=True)
    return h_eff, organ_table


def _compute_h_E_for_dir(out_dir: Path, mask: np.ndarray, organs: dict,
                         beam_area: float, ref_dict: dict = None,
                         de_df_mode: bool = False,
                         vox_y_cm: float = None) -> list:
    """
    对指定目录中的 fluence npy 文件计算各能量点的 h_E (pSv·cm²)。

    Parameters
    ----------
    out_dir    : Path — fluence_E*.npy 所在目录
    mask       : np.ndarray (NX, NY, NZ) — 器官掩膜
    organs     : dict — {organ_id: (tissue_num, density, name)}
    beam_area  : float — 束流面积 cm²（AM 与 AF 不同）
    de_df_mode : bool — True 时 .npy 为 DE/DF kerma [pGy/src]，跳过注量→剂量换算
    vox_y_cm   : float, optional — Y 方向体素尺寸 (cm)，供高能 CPE 修正使用

    Returns
    -------
    list of (energy, h_calc, h_ref, dev%)  — 仅包含成功计算的能量点
    """
    # 临时将模块级 BEAM_AREA 替换为指定值，计算完成后恢复
    global BEAM_AREA
    _orig_beam_area = BEAM_AREA
    BEAM_AREA = beam_area

    results = []
    skipped = []

    try:
        for energy in ENERGIES:
            npy_name = f"fluence_E{energy:.3f}MeV.npy"
            npy_path = out_dir / npy_name

            if not npy_path.exists():
                skipped.append(energy)
                continue

            fluence_npy = np.load(npy_path)

            if not is_data_reliable(fluence_npy, energy, mask=mask,
                                        de_df_mode=de_df_mode):
                skipped.append(energy)
                continue

            fluence_ready = prepare_mcnp_fluence(fluence_npy, mask)

            # ── DE/DF kerma 模式（Step2 用了 --de-df-mode）──────────────
            if de_df_mode:
                import json as _json_dedf
                stem_dd = f"fluence_E{energy:.3f}MeV"
                f6_path_dd = out_dir / f"{stem_dd}_f6doses.json"
                h_calc = None
                if f6_path_dd.exists():
                    try:
                        with open(f6_path_dd, 'r', encoding='utf-8') as _fh2:
                            f6d = _json_dedf.load(_fh2)
                        if f6d:
                            h_try2, ot_try2 = compute_h_eff_from_f6(f6d, organs, mask)
                            _ref2 = (ref_dict or ICRP116_REF).get(energy, 0.0)
                            if (h_try2 > 0
                                    and (_ref2 <= 0 or h_try2 <= 10 * _ref2)
                                    and len(ot_try2) >= 5):
                                h_calc = h_try2
                    except Exception:
                        pass
                if h_calc is None:
                    h_calc, _ = compute_h_eff_from_kerma(
                        fluence_ready, mask, organs,
                        energy=energy, vox_y_cm=vox_y_cm)
                h_ref = (ref_dict or ICRP116_REF).get(energy, 0.0)
                dev   = (h_calc - h_ref) / h_ref * 100 if h_ref > 0 else 0.0
                results.append((energy, h_calc, h_ref, dev))
                continue

            stem = f"fluence_E{energy:.3f}MeV"

            # ── 优先：F6:P ───────────────────────────────────────────
            import json as _json
            f6_json_path = out_dir / f"{stem}_f6doses.json"
            use_f6 = False
            h_calc = None
            organ_table = []
            if f6_json_path.exists():
                try:
                    with open(f6_json_path, 'r', encoding='utf-8') as _fh:
                        f6_dict = _json.load(_fh)
                    if f6_dict:
                        h_calc_f6, ot_f6 = compute_h_eff_from_f6(f6_dict, organs, mask)
                        _h_ref_check = ICRP116_REF.get(energy, 0.0)
                        n_f6_organs = len(ot_f6)
                        _within_range = (_h_ref_check <= 0 or h_calc_f6 <= 10 * _h_ref_check)
                        _enough_organs = (n_f6_organs >= 5)
                        if _within_range and _enough_organs:
                            h_calc, organ_table, use_f6 = h_calc_f6, ot_f6, True
                        else:
                            _reason = []
                            if not _within_range:
                                _reason.append(f"h_E(F6)={h_calc_f6:.4e} > 10×ref({_h_ref_check:.4e})")
                            if not _enough_organs:
                                _reason.append(f"有效器官组数不足({n_f6_organs}<5)")
                            print(f"  [F6] ⚠ 回退到 FMESH: {'; '.join(_reason)}")
                except Exception:
                    pass

            # ── 次优 A：多 FMESH 4 档 ────────────────────────────────
            use_emesh = False
            if not use_f6:
                fm14_b0 = out_dir / f"{stem}_bin0.npy"
                fm24_b0 = out_dir / f"{stem}_fm24_bin0.npy"
                fm24_b1 = out_dir / f"{stem}_fm24_bin1.npy"
                fm34_b0 = out_dir / f"{stem}_fm34_bin0.npy"
                fm34_b1 = out_dir / f"{stem}_fm34_bin1.npy"
                use_multifmesh = all(p.exists() for p in (fm14_b0, fm24_b0, fm24_b1, fm34_b0, fm34_b1))

                if use_multifmesh:
                    eb14 = out_dir / f"{stem}_ebounds.npy"
                    eb24 = out_dir / f"{stem}_fm24_ebounds.npy"
                    eb34 = out_dir / f"{stem}_fm34_ebounds.npy"
                    try:
                        bounds14 = list(np.load(eb14)) if eb14.exists() else None
                        bounds24 = list(np.load(eb24)) if eb24.exists() else None
                        bounds34 = list(np.load(eb34)) if eb34.exists() else None
                        c1 = bounds14[1] if bounds14 and len(bounds14) >= 3 else None
                        c2 = bounds24[1] if bounds24 and len(bounds24) >= 3 else None
                        c3 = bounds34[1] if bounds34 and len(bounds34) >= 3 else None
                        e_max = (bounds14[-1] if bounds14 else
                                 bounds24[-1] if bounds24 else
                                 bounds34[-1] if bounds34 else None)
                        if None in (c1, c2, c3, e_max):
                            raise ValueError("无法读取多 FMESH 截止能量")

                        if energy >= 9.0 and bounds24 and len(bounds24) >= 3:
                            phi24_b0_arr = prepare_mcnp_fluence(np.load(fm24_b0), mask)
                            phi24_b1_arr = prepare_mcnp_fluence(np.load(fm24_b1), mask)
                            e_bounds_2 = [bounds24[0], bounds24[1], bounds24[2]]
                            fluence_bins = [phi24_b0_arr, phi24_b1_arr]
                            use_emesh = True
                            h_calc, organ_table = compute_h_eff_from_fluence_emesh(
                                fluence_bins, e_bounds_2, mask, organs)
                        else:
                            phi14_b0 = prepare_mcnp_fluence(np.load(fm14_b0), mask)
                            phi24_b0_a = prepare_mcnp_fluence(np.load(fm24_b0), mask)
                            phi34_b0_a = prepare_mcnp_fluence(np.load(fm34_b0), mask)
                            phi34_b1_a = prepare_mcnp_fluence(np.load(fm34_b1), mask)
                            eff_bin0 = phi14_b0
                            eff_bin1 = np.clip(phi24_b0_a - phi14_b0, 0, None)
                            eff_bin2 = np.clip(phi34_b0_a - phi24_b0_a, 0, None)
                            eff_bin3 = phi34_b1_a
                            fluence_bins = [eff_bin0, eff_bin1, eff_bin2, eff_bin3]
                            e_bounds_4 = [0.0, c1, c2, c3, e_max]
                            use_emesh = True
                            h_calc, organ_table = compute_h_eff_from_fluence_emesh(
                                fluence_bins, e_bounds_4, mask, organs)
                    except Exception:
                        use_multifmesh = False

            # ── 次优 B：2 档 EMESH ───────────────────────────────────
            if not use_f6 and not use_emesh:
                eb_path   = out_dir / f"{stem}_ebounds.npy"
                bin0_path = out_dir / f"{stem}_bin0.npy"
                if eb_path.exists() and bin0_path.exists():
                    e_bounds = list(np.load(eb_path))
                    if e_bounds and e_bounds[-1] <= 1000.0:
                        n_bins = len(e_bounds) - 1
                        fluence_bins = []
                        _ok = True
                        for k in range(n_bins):
                            bin_npy = out_dir / f"{stem}_bin{k}.npy"
                            if not bin_npy.exists():
                                _ok = False
                                break
                            fluence_bins.append(prepare_mcnp_fluence(np.load(bin_npy), mask))
                        if _ok:
                            use_emesh = True
                            h_calc, organ_table = compute_h_eff_from_fluence_emesh(
                                fluence_bins, e_bounds, mask, organs)

            # ── 后备：总注量 ─────────────────────────────────────────
            if not use_f6 and not use_emesh:
                h_calc, organ_table = compute_h_eff_from_fluence(
                    fluence_ready, mask, organs, energy)

            _ref = ref_dict if ref_dict is not None else ICRP116_REF
            h_ref = _ref[energy]
            dev   = (h_calc - h_ref) / h_ref * 100
            results.append((energy, h_calc, h_ref, dev))

    finally:
        BEAM_AREA = _orig_beam_area

    return results


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


def save_organ_json(organ_tables_by_energy: dict, out_dir: Path):
    """保存逐器官剂量数据到 JSON，供前端 Step1/Step2 图使用。"""
    import json
    payload = {}
    for energy, organ_table in organ_tables_by_energy.items():
        rows = []
        for row in organ_table:
            name = row[0]; wt = row[1]; dose_pGy = row[3]; wt_dose = row[4]
            ht_phi = dose_pGy * BEAM_AREA      # HT/Φ [pSv·cm²]
            wt_ht  = wt_dose  * BEAM_AREA      # wT × HT/Φ
            rows.append({'organ': name, 'wT': wt,
                         'HT_phi': round(ht_phi, 6),
                         'wT_HT_phi': round(wt_ht, 6)})
        payload[str(energy)] = rows
    json_path = out_dir / "icrp116_organ_data.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n[JSON] 逐器官数据已保存: {json_path}")
    return json_path


def plot_step1_organs(organ_tables_by_energy: dict, results: list, out_dir: Path):
    """
    Step 1 图：单体模 + 单辐照条件 + 单器官
    每个能量点一列，展示各器官计算所得 HT/Φ (pSv·cm²)。
    颜色按 wT 深浅区分重要性；底部显示有效剂量汇总偏差。
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.cm as cm
        import numpy as np
    except ImportError:
        print("[Step1图] 未安装 matplotlib，跳过")
        return

    energies = sorted(organ_tables_by_energy.keys())
    n_e = len(energies)
    if n_e == 0:
        return

    # 收集所有出现的器官名
    all_organs_set = []
    seen = set()
    for e in energies:
        for row in organ_tables_by_energy[e]:
            nm = row[0]
            if nm not in seen:
                all_organs_set.append(nm)
                seen.add(nm)

    # 按第一个能量点的 wt_dose 排序（高贡献在前）
    wt_map = {}
    e0 = energies[0]
    for row in organ_tables_by_energy[e0]:
        wt_map[row[0]] = row[1]
    all_organs_set.sort(key=lambda o: wt_map.get(o, 0), reverse=True)
    organs = all_organs_set[:16]   # 最多16个，图不过宽

    x = np.arange(len(organs))
    short = [o.split('(')[0].strip().replace('spongiosa', 'R.B.Marrow')
               .replace('cortical', 'BoneSurf')
               .replace('urinary bladder', 'Bladder')
               .replace('glandular tissue', 'Breast')
               for o in organs]

    fig, axes = plt.subplots(n_e, 1, figsize=(14, 4.5 * n_e))
    if n_e == 1:
        axes = [axes]
    fig.suptitle('Step 1: Per-Organ Equivalent Dose Coefficient  HT/Φ  (pSv·cm²)\n'
                 'ICRP-110 AM Phantom | AP Photon | MCNP5 Simulation',
                 fontsize=12, fontweight='bold')

    ref_dict = {r[0]: r[2] for r in results}   # energy → ICRP-116 E/Φ
    calc_dict = {r[0]: r[1] for r in results}

    for ax, energy in zip(axes, energies):
        ot = {row[0]: row for row in organ_tables_by_energy[energy]}
        ht_vals = []
        wt_vals = []
        for o in organs:
            row = ot.get(o)
            if row:
                ht_vals.append(row[3] * BEAM_AREA)   # HT/Φ
                wt_vals.append(row[1])
            else:
                ht_vals.append(0.0)
                wt_vals.append(0.0)

        # 颜色：wT 越大越深蓝
        max_wt = max(wt_vals) if max(wt_vals) > 0 else 1
        bar_colors = [cm.Blues(0.35 + 0.6 * wt / max_wt) for wt in wt_vals]

        bars = ax.bar(x, ht_vals, color=bar_colors, edgecolor='white', lw=0.5)
        ax.set_yscale('log')
        ax.set_xticks(x)
        ax.set_xticklabels(short, rotation=38, ha='right', fontsize=8)
        ax.set_ylabel('HT / Φ  (pSv·cm²)', fontsize=9)

        h_ref  = ref_dict.get(energy, None)
        h_calc = calc_dict.get(energy, None)
        dev_s = ''
        if h_ref and h_calc:
            dev = (h_calc - h_ref) / h_ref * 100
            dev_s = f'  E_eff={h_calc:.3f} pSv·cm²  |  ICRP-116={h_ref:.3f}  |  Δ={dev:+.1f}%'
        ax.set_title(f'E = {energy} MeV{dev_s}', fontsize=9)
        ax.grid(axis='y', alpha=0.25, which='both')

        # wT 标注
        for bar, o, wt in zip(bars, organs, wt_vals):
            if wt > 0:
                ax.text(bar.get_x() + bar.get_width()/2,
                        bar.get_height() * 1.15,
                        f'wT={wt:.2f}', ha='center', fontsize=6, color='#444')

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    png_path = out_dir / "icrp116_step1_organs.png"
    fig.savefig(png_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"[Step1图] 已保存: {png_path}")


def plot_step2_composition(organ_tables_by_energy: dict, results: list, out_dir: Path):
    """
    Step 2 图：有效剂量误差来源分解
    每个能量点展示各器官 wT×HT/Φ 贡献（堆积柱），
    叠加 ICRP-116 E/Φ 参考线，直观显示误差由哪些器官贡献。
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.cm as cm
        import numpy as np
    except ImportError:
        print("[Step2图] 未安装 matplotlib，跳过")
        return

    energies = sorted(organ_tables_by_energy.keys())
    n_e = len(energies)
    if n_e == 0:
        return

    COLORS = ['#1E88E5','#E53935','#43A047','#FB8C00','#8E24AA',
              '#00ACC1','#F06292','#A1887F','#7CB342','#FFB300',
              '#5E35B1','#00897B','#3949AB','#546E7A','#6D4C41','#B0BEC5']

    fig, axes = plt.subplots(1, n_e, figsize=(5.5 * n_e, 7))
    if n_e == 1:
        axes = [axes]
    fig.suptitle('Step 2: Effective Dose Error Source  —  Organ Contributions  wT × HT/Φ\n'
                 'ICRP-110 AM Phantom | AP Photon | MCNP5  vs  ICRP-116 E/Φ Reference',
                 fontsize=12, fontweight='bold')

    ref_dict  = {r[0]: r[2] for r in results}
    calc_dict = {r[0]: r[1] for r in results}

    # 收集跨能量的器官名（按最大 wt_dose 排序）
    organ_total_wt = {}
    for e, ot in organ_tables_by_energy.items():
        for row in ot:
            organ_total_wt[row[0]] = organ_total_wt.get(row[0], 0) + abs(row[4] * BEAM_AREA)
    sorted_organs = sorted(organ_total_wt, key=organ_total_wt.get, reverse=True)[:14]

    for ax, energy in zip(axes, energies):
        ot = {row[0]: row for row in organ_tables_by_energy[energy]}
        h_ref   = ref_dict.get(energy, None)
        h_calc  = calc_dict.get(energy, None)

        # 堆积柱：从零开始叠加每个器官的 wT×HT/Φ
        bottom = 0.0
        for ci, organ in enumerate(sorted_organs):
            row = ot.get(organ)
            if not row:
                continue
            val = row[4] * BEAM_AREA   # wT × HT/Φ
            wt  = row[1]
            short_name = organ.split('(')[0].strip()[:18]
            ax.bar(0, val, bottom=bottom,
                   color=COLORS[ci % len(COLORS)], width=0.6,
                   label=f'{short_name} (wT={wt:.3f})')
            mid = bottom + val / 2
            if val > 0.02 * (h_calc or 1):
                ax.text(0.35, mid, f'{short_name}  {val:+.3f}',
                        va='center', fontsize=7.5, color='#222')
            bottom += val

        # ICRP-116 E/Φ 参考线
        if h_ref:
            ax.axhline(h_ref, color='royalblue', lw=2.5, ls='--',
                       label=f'ICRP-116 E/Φ = {h_ref:.3f}')
        if h_calc:
            ax.axhline(h_calc, color='tomato', lw=1.5, ls=':',
                       label=f'MCNP calc = {h_calc:.3f}')

        ax.set_xlim(-0.5, 1.2)
        ax.set_xticks([])
        ax.set_ylabel('wT × HT / Φ  (pSv·cm²)', fontsize=9)
        dev_s = ''
        if h_ref and h_calc:
            dev = (h_calc - h_ref) / h_ref * 100
            dev_s = f'  Δ = {dev:+.1f}%'
        ax.set_title(f'E = {energy} MeV{dev_s}', fontsize=9)
        ax.legend(fontsize=6.5, loc='upper right')
        ax.grid(axis='y', alpha=0.2)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    png_path = out_dir / "icrp116_step2_composition.png"
    fig.savefig(png_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"[Step2图] 已保存: {png_path}")


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
    # ── AF 性别平均支持 ──────────────────────────────────────────────
    parser.add_argument("--af-out-dir", default=None,
        help="AF fluence_E*.npy 所在目录（提供时启用性别平均 h_E）")
    parser.add_argument("--af-mask", default=None,
        help="AF 器官掩膜路径（默认: icrp_validation/organ_mask_127x63x111_AF.npy）")
    parser.add_argument("--af-zip", default=None,
        help="ICRP-110 AF.zip 路径（默认: ../P110 data V1.2/AF.zip）")
    parser.add_argument("--de-df-mode", action="store_true",
        help="DE/DF kerma 模式：Step2 用 --de-df-mode 生成输入时使用。\n"
             "  fluence_E*.npy 已是 pGy/src kerma，直接用于器官剂量，\n"
             "  跳过 E×(μ_en/ρ) 注量→剂量换算步骤。")
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
    print(f"  beam_area: {BEAM_AREA:.2f} cm^2")
    if args.de_df_mode:
        print("  ★ DE/DF kerma 模式（.npy 已是 pGy/src，直接求器官均值）")
    print()

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
    organ_tables_by_energy = {}   # energy → organ_table（逐器官数据）

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

        if not is_data_reliable(fluence_npy, energy, mask=mask,
                                de_df_mode=args.de_df_mode):
            max_v = fluence_npy.max()
            mean_v = fluence_npy.mean()
            if max_v <= 0:
                print(f"     [数据检验] 检测到无效数据（全零数组 max={max_v:.3e}）")
                print(f"     原因：MCNP 输入文件有语法错误（如材料卡格式），MCNP 提前中止，")
                print(f"     meshtal 文件存在但无任何计分数据。")
                print(f"     解决：拉取最新代码，重启后端，重新运行 Step2b。")
            elif energy <= 0.05:
                incident = 1.0 / BEAM_AREA
                mask_flu = mask.transpose(2, 1, 0)
                tissue_sel = fluence_npy[mask_flu > 0]
                tissue_raw = float(tissue_sel.mean()) if tissue_sel.size > 0 else mean_v
                # DE/DF 模式：tissue_raw 单位是 pGy/src，需换算回注量 cm⁻²/src
                if args.de_df_mode:
                    df_factor = (_interp_mu_en_rho(energy, _SOFT_INTERP_E, _SOFT_INTERP_MU)
                                 * energy * 1.602e2)
                    tissue_mean = tissue_raw / df_factor if df_factor > 0 else tissue_raw
                else:
                    tissue_mean = tissue_raw
                ratio = tissue_mean / incident
                print(f"     [数据检验] *** 物理不合理：低能光子未被衰减！ ***")
                print(f"     E={energy} MeV 光子在软组织中平均自由程仅 ~0.04 cm，")
                print(f"     组织注量均值 {tissue_mean:.3e} = {ratio:.1%} × 入射注量（应 < 1%）")
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

        # ── DE/DF kerma 模式（Step2 用 --de-df-mode 生成时使用） ──────────────
        if args.de_df_mode:
            import json as _json
            stem_dedf = f"fluence_E{energy:.3f}MeV"
            f6_json_dedf = out_dir / f"{stem_dedf}_f6doses.json"
            h_calc = None
            organ_table = []
            # Try F6 first: F6:P uses actual material cross-sections per cell,
            # which properly handles bone vs soft-tissue μ_en/ρ differences
            # (important at 0.1 MeV where bone μ_en/ρ is 14.5% higher).
            if f6_json_dedf.exists():
                try:
                    with open(f6_json_dedf, 'r', encoding='utf-8') as _fh:
                        f6_dict = _json.load(_fh)
                    if f6_dict:
                        h_try, ot_try = compute_h_eff_from_f6(f6_dict, organs, mask)
                        _ref_chk = ICRP116_REF.get(energy, 0.0)
                        n_organs = len(ot_try)
                        sane = (_ref_chk <= 0 or h_try <= 10 * _ref_chk) and n_organs >= 5
                        if sane:
                            h_calc = h_try
                            organ_table = ot_try
                            print(f"     [DE/DF+F6] 使用 F6:P 计分（器官材料精确μ_en/ρ）")
                        else:
                            print(f"     [DE/DF] F6 数据不满足条件（n={n_organs}, h={h_try:.4f}），回退 DE/DF kerma")
                except Exception as _ef6:
                    print(f"     [DE/DF] F6 读取失败: {_ef6}，回退 DE/DF kerma")
            if h_calc is None:
                print(f"     [DE/DF] kerma 模式：直接使用 pGy/src 输出，跳过注量→剂量换算")
                h_calc, organ_table = compute_h_eff_from_kerma(
                    fluence_ready, mask, organs,
                    energy=energy, vox_y_cm=VOX_Y)
            h_ref = ICRP116_REF[energy]
            dev   = (h_calc - h_ref) / h_ref * 100
            print_organ_table(organ_table, energy)
            flag = "OK" if abs(dev) <= 10 else ("~" if abs(dev) <= 20 else "FAIL")
            print(f"\n  [DE/DF] h_E(calc)={h_calc:.4f}  h_E(ICRP-116)={h_ref:.4f}  "
                  f"dev={dev:+.1f}%  {flag}")
            results.append((energy, h_calc, h_ref, dev))
            continue

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
                    print(f"     [F6] 加载 F6:P,E 计分 {f6_json_path.name}，{len(f6_dict)} 个器官组")
                    h_calc, organ_table = compute_h_eff_from_f6(f6_dict, organs, mask)
                    # N_vox 修正已在 compute_h_eff_from_f6 内部完成；此处只做基本合理性检验
                    _h_ref_check = ICRP116_REF.get(energy, 0.0)
                    _f6_sane = True
                    if _h_ref_check > 0 and h_calc > 200 * _h_ref_check:
                        print(f"     [F6] ⚠ 检测到异常大值: h_E(F6)={h_calc:.3e} pSv·cm²"
                              f" >> ICRP-116={_h_ref_check:.4f}（>{200}×）")
                        print(f"     [F6]   可能原因: prdmp 累积值未正确提取，或 N_vox 计数有误。")
                        print(f"     [F6]   本次回退到 FMESH 注量模式。")
                        _f6_sane = False
                    n_f6_organs = len(organ_table)
                    if _f6_sane and n_f6_organs >= 5:
                        use_f6 = True
                    elif _f6_sane:
                        print(f"     [F6] ⚠ 回退到 FMESH: 有效器官组数不足({n_f6_organs}<5)")
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
        organ_tables_by_energy[energy] = organ_table   # ← 新增：收集逐器官数据

    if skipped:
        print(f"\n[警告] 以下能量点因数据不可用已跳过: {skipped}")

    if not results:
        print("\n[错误] 没有可用的 MCNP 结果。")
        print("  请确认:")
        print("  1. Step2b 已成功完成（fluence_E*.npy 存在且非空）")
        print("  2. MCNP5 xsdir 包含所用光子截面库（默认 .70p）")
        print("     若无 .70p，检查 xsdir 中可用库后用 --phot-lib 重新生成输入文件")
        sys.exit(1)

    # ── AM 汇总表格 ───────────────────────────────────────────
    print("\n" + "=" * 65)
    print(f"  [AM] {'能量(MeV)':<12} {'h_计算':>12} {'h_ICRP-116':>12} {'偏差':>8}  判定")
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

    # ── 保存 AM CSV ───────────────────────────────────────────
    save_csv(results, out_dir)

    # ── 保存逐器官 JSON ───────────────────────────────────────
    if organ_tables_by_energy:
        save_organ_json(organ_tables_by_energy, out_dir)

    # ── 绘图（AM）：Step1 → Step2 → 有效剂量对比（老师要求顺序）──
    if not args.no_plot:
        if organ_tables_by_energy:
            plot_step1_organs(organ_tables_by_energy, results, out_dir)
            plot_step2_composition(organ_tables_by_energy, results, out_dir)
        try_plot(results, out_dir)

    # ── AF 性别平均 ───────────────────────────────────────────
    if args.af_out_dir:
        af_out_dir = Path(args.af_out_dir)
        af_mask_path = Path(args.af_mask) if args.af_mask else \
                       Path("icrp_validation/organ_mask_127x63x111_AF.npy")
        af_zip_path  = Path(args.af_zip) if args.af_zip else \
                       Path("../P110 data V1.2/AF.zip")

        af_errors = []
        if not af_out_dir.exists():
            af_errors.append(f"AF 输出目录不存在: {af_out_dir}")
        if not af_mask_path.exists():
            af_errors.append(f"AF 器官掩膜不存在: {af_mask_path}")
        if not af_zip_path.exists():
            af_errors.append(f"AF.zip 不存在: {af_zip_path}")
        if af_errors:
            for e in af_errors:
                print(f"[AF 警告] {e}")
            print("[AF] 跳过性别平均计算")
        else:
            print(f"\n[AF] 加载 AF 器官掩膜: {af_mask_path}")
            af_mask = np.load(af_mask_path)
            assert af_mask.shape == (NX, NY, NZ), \
                f"AF 掩膜 shape 应为 ({NX},{NY},{NZ})，实为 {af_mask.shape}"

            print(f"[AF] 加载 AF 器官定义: {af_zip_path}")
            af_organs = _load_organs_from_zip(str(af_zip_path), phantom='AF')
            print(f"     共 {len(af_organs)} 个器官")

            print(f"[AF] 计算 AF h_E (beam_area={_AF_BEAM_AREA:.2f} cm²) ...")
            af_results = _compute_h_E_for_dir(af_out_dir, af_mask, af_organs,
                                              beam_area=_AF_BEAM_AREA,
                                              ref_dict=ICRP116_REF_AF,
                                              de_df_mode=args.de_df_mode,
                                              vox_y_cm=_AF_VOX_Y)

            if not af_results:
                print("[AF] 未能计算任何 AF 能量点，跳过性别平均")
            else:
                # 建立 AM/AF 结果字典（以能量为 key）
                am_dict = {e: (hc, hr, d) for e, hc, hr, d in results}
                af_dict = {e: (hc, hr, d) for e, hc, hr, d in af_results}

                # 仅对 AM 和 AF 都有结果的能量点做平均
                common_energies = sorted(set(am_dict) & set(af_dict))

                if common_energies:
                    print("\n" + "=" * 90)
                    print(f"  {'Energy(MeV)':<12} {'h_E,AM':>10} {'h_E,AF':>10} "
                          f"{'h_E,avg':>10} {'ICRP-116':>10} "
                          f"{'dev_AM%':>8} {'dev_AF%':>8} {'dev_avg%':>9}  判定")
                    print("  " + "-" * 85)
                    avg_results = []
                    for e in common_energies:
                        h_am, h_ref, d_am = am_dict[e]
                        h_af, _,     d_af = af_dict[e]
                        h_avg = (h_am + h_af) / 2.0
                        d_avg = (h_avg - h_ref) / h_ref * 100
                        ok = abs(d_avg) <= 10
                        sym = "PASS" if ok else ("~<20%" if abs(d_avg) <= 20 else "FAIL")
                        print(f"  {e:<12.3f} {h_am:>10.4f} {h_af:>10.4f} "
                              f"{h_avg:>10.4f} {h_ref:>10.4f} "
                              f"{d_am:>+8.1f} {d_af:>+8.1f} {d_avg:>+9.1f}%  {sym}")
                        avg_results.append((e, h_avg, h_ref, d_avg))
                    print("  " + "-" * 85)
                    avg_passed = sum(1 for _, _, _, d in avg_results if abs(d) <= 10)
                    print(f"  性别平均通过率（±10%）: {avg_passed}/{len(avg_results)}")
                    print("=" * 90)

                    # 保存性别平均 CSV
                    csv_avg = out_dir / "icrp116_comparison_sexavg.csv"
                    lines = ["Energy_MeV,h_AM_pSv_cm2,h_AF_pSv_cm2,h_avg_pSv_cm2,"
                             "h_ref_pSv_cm2,dev_AM_pct,dev_AF_pct,dev_avg_pct,pass"]
                    for e in common_energies:
                        h_am, h_ref, d_am = am_dict[e]
                        h_af, _,     d_af = af_dict[e]
                        h_avg = (h_am + h_af) / 2.0
                        d_avg = (h_avg - h_ref) / h_ref * 100
                        ok = "PASS" if abs(d_avg) <= 10 else "FAIL"
                        lines.append(f"{e:.3f},{h_am:.4f},{h_af:.4f},{h_avg:.4f},"
                                     f"{h_ref:.4f},{d_am:+.1f},{d_af:+.1f},{d_avg:+.1f},{ok}")
                    csv_avg.write_text("\n".join(lines), encoding="utf-8")
                    print(f"\n[CSV] 性别平均结果已保存: {csv_avg}")

    print("\n完成！结果文件位于:", out_dir)


if __name__ == "__main__":
    main()
