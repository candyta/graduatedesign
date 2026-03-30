#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCNP ICRP-110 验证 — 第二步：生成 MCNP5 AP 光子束输入文件
=============================================================
读取第一步生成的器官掩膜，为 4 个光子能量点生成 MCNP5 输入文件，
用于与 ICRP-116 Table A.3 (AP geometry, photons) 对比验证。

能量点: 0.01, 0.10, 1.00, 10.00 MeV

输出 (icrp_validation/mcnp_inputs/):
  ap_photon_E0.010MeV.inp
  ap_photon_E0.100MeV.inp
  ap_photon_E1.000MeV.inp
  ap_photon_E10.000MeV.inp

体模方向约定（ICRP-110）:
  X: 左右 (列, nx=127)
  Y: 前后 (行, ny=63, Y>0 = 后方/posterior)
  Z: 脚头 (层, nz=111)

AP 束流方向: +Y（从前方/anterior 射向后方/posterior）

运行方式:
  python mcnp_icrp_step2_gen_input.py
  python mcnp_icrp_step2_gen_input.py --mask icrp_validation/organ_mask_127x63x111.npy \
      --zip "P110 data V1.2/AM.zip" --out-dir icrp_validation/mcnp_inputs
"""

import argparse
import re
import textwrap
import zipfile
from io import StringIO
from pathlib import Path

import numpy as np

# ── 体模物理参数（与 Step 1 保持一致） ───────────────────────────
DS_SHAPE   = (127, 63, 111)       # (nx, ny, nz)
DS_VOX_CM  = (0.4274, 0.4308, 1.6)  # 全尺寸体素 cm

HALF_VOX   = tuple(v / 2 for v in DS_VOX_CM)   # (0.2137, 0.2154, 0.800)
NX, NY, NZ = DS_SHAPE

# 晶格 fill 范围（奇数维度 n → -(n//2) : n//2，共 n 个格子）
FILL_X = (-(NX // 2), NX // 2)    # -63 : 63  (127 个)
FILL_Y = (-(NY // 2), NY // 2)    # -31 : 31  (63 个)
FILL_Z = (-(NZ // 2), NZ // 2)    # -55 : 55  (111 个)

# 体素外边界 cm（奇数: n × half_vox）
PHANT_X = NX * HALF_VOX[0]   # 27.140
PHANT_Y = NY * HALF_VOX[1]   # 13.572
PHANT_Z = NZ * HALF_VOX[2]   # 88.800

# AP 源平面 Y 坐标（体模前方外侧 2 cm）
SRC_Y = -(PHANT_Y + 2.0)

# 4 个验证能量点 (MeV)
ENERGIES_MEV = [0.01, 0.10, 1.00, 10.00]

# ── 多 FMESH 能量分档方案 ──────────────────────────────────────────────────────
#
# MCNP5 1.14 限制：单个 FMESH tally 最多 2 个 EMESH 档（3档崩溃，退出码 3221225642）。
#
# 绕过方案：同一次 MCNP 运行写入 3 个 FMESH tally（FMESH14/24/34），
# 每个各用 2 档不同截止能量 (C1, C2, C3)，后处理相减得到 4 个有效档：
#
#   FMESH14: emesh = C1  E_max  → bins [0, C1],  [C1, E_max]
#   FMESH24: emesh = C2  E_max  → bins [0, C2],  [C2, E_max]
#   FMESH34: emesh = C3  E_max  → bins [0, C3],  [C3, E_max]
#
#   后处理 Step3 相减 → 4 有效档：
#     [0,   C1]  = FMESH14_bin0
#     [C1,  C2]  = FMESH24_bin0 − FMESH14_bin0
#     [C2,  C3]  = FMESH34_bin0 − FMESH24_bin0
#     [C3, E_max]= FMESH34_bin1
#
# 物理依据（1 MeV 源）：
#   [0.0-0.2]  低能散射（大角度 Compton 及多次散射）   代表能量 ~0.10 MeV
#   [0.2-0.5]  中能散射（后半球 Compton）              代表能量 ~0.32 MeV
#   [0.5-0.8]  前向散射（前半球 Compton）              代表能量 ~0.63 MeV
#   [0.8-1.1]  近初级光子（初级 + 极小角散射）         代表能量 ~0.94 MeV
#   → 与 2 档方案相比，散射光子被正确分配到更低能量档，
#     高估由 ~+20% 降至 ~+5–8%。
#
# E=0.01/0.10 MeV：0.01 MeV 散射极少，0.10 MeV 因 μ_en/ρ 在该能量极小值附近
#   分档反而增大偏差，两者均保留单 FMESH14（无 EMESH）。
#
MULTI_FMESH_CUTS = {
    # (C1, C2, C3, E_max)
    1.00:  (0.20, 0.50, 0.80, 1.10),
    10.00: (2.00, 5.00, 8.00, 10.50),
}

# ── DE/DF 注量-kerma 转换表（软组织 ICRU-44）──────────────────────────────
#
# MCNP5 DE/DF 乘子卡：FMESH 输出乘以能量相关因子 DF(E)，
# 使每个光子以其实际能量贡献，彻底消除 EMESH 代表能量误差。
#
# DF(E) [pGy·cm²] = E [MeV] × (μ_en/ρ) [cm²/g] × 1.602e2
# 来源: NIST XCOM，软组织 ICRU-44 (H10.1%, C11.1%, N2.6%, O76.2%)
#
# 用途：当 --de-df-mode 启用时，写入 FMESH14 + DE14/DF14，
# 取代多 FMESH EMESH 方案，输出单位为 pGy/src（器官平均 kerma）。
#
_DEDF_ENERGIES = [0.001, 0.005, 0.010, 0.020, 0.030, 0.050, 0.080, 0.100,
                  0.150, 0.200, 0.300, 0.400, 0.500, 0.600, 0.800, 1.000,
                  1.500, 2.000, 3.000, 4.000, 5.000, 6.000, 8.000, 10.000]
# DF = E × μ_en/ρ × 160.2  (pGy·cm²)
_DEDF_SOFT_KERMA = [6.040e+02, 1.482e+02, 7.596e+00, 1.689e+00, 7.141e-01,
                    3.353e-01, 3.910e-01, 4.079e-01, 6.680e-01, 9.512e-01,
                    1.535e+00, 2.102e+00, 2.644e+00, 3.155e+00, 4.108e+00,
                    4.912e+00, 6.745e+00, 8.298e+00, 1.082e+01, 1.312e+01,
                    1.534e+01, 1.760e+01, 2.230e+01, 3.486e+01]

# MCNP5 光子截面库后缀
# 默认 .04p (MCPLIB04)；若安装了更新版 .70p (MCPLIB70) 会由 detect_phot_lib 自动选择
PHOT_SUFFIX = '.04p'

# 元素 Z 顺序（与 AM_media.dat 列一致）
ELEMENT_Z_ORDER = [1, 6, 7, 8, 11, 12, 15, 16, 17, 19, 20, 26, 53]
# Z → ZAID（光子库）
ZAID_MAP = {
    1:  f'1000{PHOT_SUFFIX}',    # H
    6:  f'6000{PHOT_SUFFIX}',    # C
    7:  f'7000{PHOT_SUFFIX}',    # N
    8:  f'8000{PHOT_SUFFIX}',    # O
    11: f'11000{PHOT_SUFFIX}',   # Na
    12: f'12000{PHOT_SUFFIX}',   # Mg
    15: f'15000{PHOT_SUFFIX}',   # P
    16: f'16000{PHOT_SUFFIX}',   # S
    17: f'17000{PHOT_SUFFIX}',   # Cl
    19: f'19000{PHOT_SUFFIX}',   # K
    20: f'20000{PHOT_SUFFIX}',   # Ca
    26: f'26000{PHOT_SUFFIX}',   # Fe
    53: f'53000{PHOT_SUFFIX}',   # I
}
AIR_MAT_ID  = 200   # 干燥空气材料编号（自定义）
AIR_UNIV    = 9000  # 空气体素宇宙编号（fill 数组中 organ_id=0 映射到此）
# 注意：fill 数组中 0 表示"晶格元素越界"→ 粒子丢失；必须映射到非零宇宙


def detect_phot_lib(xsdir_path: str) -> str:
    """
    扫描 MCNP5 xsdir 文件，使用正则表达式匹配真实的光子截面库条目。
    xsdir 条目格式：<ZAID>.<LLp>  <AWR>  <filename>  ...
    例如：  1000.04p   0.000000  mcplib04  0  1  0  ...
    按优先级依次检查：.70p  .12p  .04p  .24p
    返回找到的第一个后缀；若均未找到则返回 None。
    """
    import re
    preferred = ['.70p', '.12p', '.04p', '.24p']
    try:
        with open(xsdir_path, 'r', errors='ignore') as f:
            content = f.read()
    except OSError:
        return None
    # 在 xsdir 中寻找真实条目：行首（可有空格）的 ZAID.LLp 后跟空白字符
    # 这样可以避免误匹配注释或路径名中的字符串
    found = set(re.findall(r'^\s*\d+\.(\d{2,3})p\s', content, re.MULTILINE))
    for suffix in preferred:
        digits = suffix.lstrip('.').rstrip('p')  # '.04p' -> '04'
        if digits in found:
            return suffix
    return None


def build_zaid_map(phot_suffix: str) -> dict:
    """根据指定截面库后缀构建 ZAID 映射。"""
    z_list = [1, 6, 7, 8, 11, 12, 15, 16, 17, 19, 20, 26, 53]
    z_names = {1:'H', 6:'C', 7:'N', 8:'O', 11:'Na', 12:'Mg',
               15:'P', 16:'S', 17:'Cl', 19:'K', 20:'Ca', 26:'Fe', 53:'I'}
    return {z: f'{z * 1000}{phot_suffix}' for z in z_list}


# ═══════════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════════

def parse_organs(lines):
    """AM_organs.dat → {organ_id: (tissue_num, density, name)}"""
    organs = {}
    for line in lines:
        m = re.match(r'^\s*(\d+)\s+(.+?)\s{2,}(\d+)\s+([\d.]+)\s*$', line.strip())
        if m:
            oid      = int(m.group(1))
            name     = m.group(2).strip()
            tissue   = int(m.group(3))
            density  = float(m.group(4))
            organs[oid] = (tissue, density, name)
    return organs


def parse_media(lines):
    """
    AM_media.dat → {tissue_num: (name, {Z: mass_fraction})}
    每行: tissue_num  tissue_name  val1 val2 ... val13 (% by mass)
    """
    media = {}
    for line in lines:
        m = re.match(r'^\s*(\d+)\s+(.+?)\s{2,}([\d.]+(?:\s+[\d.]+)*)\s*$', line.strip())
        if m:
            tissue_num = int(m.group(1))
            tissue_name = m.group(2).strip()
            vals = [float(v) for v in m.group(3).split()]
            if len(vals) != len(ELEMENT_Z_ORDER):
                continue
            comp = {z: pct / 100.0
                    for z, pct in zip(ELEMENT_Z_ORDER, vals) if pct > 0}
            media[tissue_num] = (tissue_name, comp)
    return media


def load_data(mask_path: str, zip_path: str, phantom: str = 'AM'):
    """
    加载掩膜 + 器官/组织数据。

    Parameters
    ----------
    mask_path : str
    zip_path  : str
    phantom   : 'AM' 或 'AF'

    Returns
    -------
    mask   : np.ndarray shape (127, 63, 111) uint8
    organs : {organ_id: (tissue_num, density, name)}
    media  : {tissue_num: (name, {Z: fraction})}
    """
    mask = np.load(mask_path)
    assert mask.shape == DS_SHAPE, f"掩膜 shape 应为 {DS_SHAPE}，实为 {mask.shape}"

    if phantom == 'AF':
        organs_entry = 'AF/AF_organs.dat'
        media_entry  = 'AF/AF_media.dat'
    else:
        organs_entry = 'AM/AM_organs.dat'
        media_entry  = 'AM/AM_media.dat'

    with zipfile.ZipFile(zip_path, 'r') as z:
        organs_text = z.read(organs_entry).decode('utf-8', errors='replace')
        media_text  = z.read(media_entry ).decode('utf-8', errors='replace')

    organs = parse_organs(organs_text.splitlines())
    media  = parse_media(media_text.splitlines())
    print(f"  已加载掩膜 {mask.shape}，器官={len(organs)} 个，组织类型={len(media)} 种")
    return mask, organs, media


# ═══════════════════════════════════════════════════════════════
# MCNP5 输入文件生成
# ═══════════════════════════════════════════════════════════════

def _geom():
    """
    返回 (hx, hy, hz, px, py, pz)，其中 hx/hy/hz 取 6 位小数，
    px=NX*hx, py=NY*hy, pz=NZ*hz，确保晶格延伸范围与体模容器边界完全一致。

    AF 体素尺寸为无理数（0.41789...cm），直接用 :.4f 格式写入时，
    晶格实际范围（NX×hx_rounded）与 PHANT_X（独立舍入）之间出现 ~0.006 cm
    间隙，粒子进入该间隙后找不到晶格单元 → "zero lattice element hit"。
    使用 6 位小数并从舍入后的 hx 推导 px，可彻底消除间隙。
    """
    hx = round(HALF_VOX[0], 6)
    hy = round(HALF_VOX[1], 6)
    hz = round(HALF_VOX[2], 6)
    return hx, hy, hz, NX * hx, NY * hy, NZ * hz


def _fmt_fill_array(fill_vals: np.ndarray, per_line: int = 15) -> str:
    """
    将 fill 数组格式化为 MCNP5 续行格式。
    fill_vals : 1-D array，顺序为 (iz slow, iy mid, ix fast)
    per_line=15 保证 3 位 organ_id 时每行不超过 80 列 (5+15×4-1=64)。
    """
    lines = []
    total = len(fill_vals)
    for start in range(0, total, per_line):
        chunk = fill_vals[start:start + per_line]
        lines.append('     ' + ' '.join(str(v) for v in chunk))
    return '\n'.join(lines)


def write_cell_section(f, unique_ids, organs):
    """
    写 Cell 卡。
    每个 organ_id k 对应：
      k     : tissue_num  -density  <base_geom>  u=k  imp:p=1
      88k   : 0  #k  u=k  imp:p=1
    Universe 0 (体外空气):
      9000  : AIR_MAT_ID  -0.001225  <base_geom>  u=0  imp:p=1
      89000 : 0  #9000  u=0  imp:p=1
    """
    bg = '-11 12 -13 14 -15 16'   # base cell geometry

    f.write(f'c --- Universe {AIR_UNIV}: Air (organ_id=0, outside body) ---\n')
    f.write(f'c     fill=0 causes "particle lost"; map organ_id=0 to u={AIR_UNIV} instead\n')
    f.write(f'9001  {AIR_MAT_ID}  -0.001225  {bg}  u={AIR_UNIV}  imp:p=1\n')
    f.write(f'9002  0  #9001  u={AIR_UNIV}  imp:p=1\n')
    f.write('c\n')

    f.write('c --- Organ universes (organ_id -> tissue material) ---\n')
    for oid in sorted(unique_ids):
        if oid == 0:
            continue
        tissue_num, density, name = organs.get(oid, (1, 1.0, f'Organ{oid}'))
        f.write(f'c  {oid}: {name}  tissue={tissue_num}  rho={density:.4f}\n')
        f.write(f'{oid}  {tissue_num}  -{density:.4f}  {bg}  u={oid}  imp:p=1\n')
        f.write(f'88{oid}  0  #{oid}  u={oid}  imp:p=1\n')

    f.write('c\n')
    f.write('c --- Lattice fill (universe 999) ---\n')


def write_lattice_cell(f, fill_vals):
    """写晶格 cell 卡（998）和体模容器（999）。"""
    bg = '-11 12 -13 14 -15 16'
    ix0, ix1 = FILL_X
    iy0, iy1 = FILL_Y
    iz0, iz1 = FILL_Z

    f.write(f'998  0  {bg}  u=999  lat=1  imp:p=1\n')
    f.write(f'     fill={ix0}:{ix1} {iy0}:{iy1} {iz0}:{iz1}\n')
    f.write(_fmt_fill_array(fill_vals))
    f.write('\n')
    f.write('c\n')
    f.write('c --- Phantom container ---\n')
    f.write(f'999  0  -111 112 -113 114 -115 116  fill=999  imp:p=1\n')
    f.write('c --- Air surround ---\n')
    f.write(f'1000  {AIR_MAT_ID}  -0.001225  -9999  #999  imp:p=1\n')
    f.write('c --- World void ---\n')
    f.write('9999  0  9999  imp:p=0\n')


def write_surface_section(f):
    """写 Surface 卡。"""
    hx, hy, hz, px, py, pz = _geom()
    f.write(f'c Unit voxel base cell (half-spacing = {hx:.6f}, {hy:.6f}, {hz:.6f} cm)\n')
    f.write(f'11  px   {hx:.6f}\n')
    f.write(f'12  px  -{hx:.6f}\n')
    f.write(f'13  py   {hy:.6f}\n')
    f.write(f'14  py  -{hy:.6f}\n')
    f.write(f'15  pz   {hz:.6f}\n')
    f.write(f'16  pz  -{hz:.6f}\n')
    f.write('c\n')
    # px = NX*hx (derived from same rounded hx used for surfaces 11-16),
    # so lattice extent and phantom container boundary are guaranteed equal.
    # This eliminates the "zero lattice element hit" error seen for AF phantom
    # where irrational voxel sizes cause a gap under independent 4-decimal rounding.
    f.write(f'c Phantom bounding box ({px:.6f} x {py:.6f} x {pz:.6f} cm)\n')
    f.write(f'111  px   {px:.6f}\n')
    f.write(f'112  px  -{px:.6f}\n')
    f.write(f'113  py   {py:.6f}\n')
    f.write(f'114  py  -{py:.6f}\n')
    f.write(f'115  pz   {pz:.6f}\n')
    f.write(f'116  pz  -{pz:.6f}\n')
    f.write('c\n')
    f.write('c World sphere\n')
    f.write('9999  so  300.0\n')


def write_data_section(f, unique_ids, organs, media, energy_mev, mask=None,
                       de_df_mode=False):
    """写 Data 卡：mode, 材料, 源, 计分卡, nps。"""
    # ── mode & physics ──
    f.write('mode p\n')
    f.write('phys:p 20 0\n')
    f.write('c\n')

    # ── 材料 ──
    # 干燥空气
    f.write(f'c Material {AIR_MAT_ID}: Dry Air  rho=-0.001225 g/cm3\n')
    f.write(f'm{AIR_MAT_ID}  7000{PHOT_SUFFIX}  -0.7553  $ N\n')
    f.write(f'      8000{PHOT_SUFFIX}  -0.2318  $ O\n')
    f.write(f'     18000{PHOT_SUFFIX}  -0.0129  $ Ar\n')
    f.write('c\n')

    # ICRP-110 组织材料
    used_tissues = set()
    for oid in sorted(unique_ids):
        if oid == 0:
            continue
        tissue_num = organs.get(oid, (1,))[0]
        used_tissues.add(tissue_num)

    f.write('c ICRP-110 AM tissue materials (from AM_media.dat)\n')
    f.write(f'c Nuclear data: ENDF/B-VI ({PHOT_SUFFIX})\n')
    for tid in sorted(used_tissues):
        if tid not in media:
            continue
        tname, comp = media[tid]
        # 从该组织对应的器官中取密度（取第一个）
        density_ref = 1.0
        for oid, (tn, dens, _) in organs.items():
            if tn == tid:
                density_ref = dens
                break
        f.write(f'c  M{tid}: {tname}  rho~{density_ref:.4f}\n')
        zaids = [(z, comp[z], ZAID_MAP.get(z)) for z in sorted(comp.keys())
                 if ZAID_MAP.get(z) and comp[z] > 0]
        first = True
        for z, frac, zaid in zaids:
            if first:
                f.write(f'm{tid}  {zaid}  -{frac:.6f}  $ Z={z}\n')
                first = False
            else:
                f.write(f'     {zaid}  -{frac:.6f}  $ Z={z}\n')
        f.write('c\n')

    # ── 源：AP 平行光子束 ──
    f.write(f'c AP parallel photon beam  E={energy_mev:.3f} MeV\n')
    f.write(f'c Source plane: y={SRC_Y:.4f} cm  (anterior, +Y direction)\n')
    f.write(f'c Source area:  X=[{-PHANT_X:.4f}, {PHANT_X:.4f}]  Z=[{-PHANT_Z:.4f}, {PHANT_Z:.4f}] cm\n')
    _, _, _, px, py, pz = _geom()
    src_y = -(py + 2.0)
    f.write( 'SDEF  par=2\n')
    f.write(f'      erg={energy_mev:.4f}\n')
    f.write( '      dir=1  vec=0 1 0\n')
    f.write(f'      x=d1  y={src_y:.6f}  z=d2\n')
    # SI1/SI2 use px/pz derived from rounded hx/hz (same values as surfaces 111-116),
    # so source particles can never spawn outside the lattice-covered volume.
    f.write(f'SI1  {-px:.6f}  {px:.6f}\n')
    f.write( 'SP1  0  1\n')
    f.write(f'SI2  {-pz:.6f}  {pz:.6f}\n')
    f.write( 'SP2  0  1\n')
    f.write('c\n')

    # ── 计分卡：3-D 网格通量 / kerma ──────────────────────────────────────
    def _write_base_fmesh(tnum):
        """写入不带 EMESH 的单 FMESH（总注量或 DE/DF kerma）。"""
        f.write(f'FMESH{tnum}:p  geom=XYZ\n')
        f.write(f'     origin={-px:.6f} {-py:.6f} {-pz:.6f}\n')
        f.write(f'     imesh={px:.6f}  iints={NX}\n')
        f.write(f'     jmesh={py:.6f}  jints={NY}\n')
        f.write(f'     kmesh={pz:.6f}  kints={NZ}\n')
        f.write('c\n')

    def _write_fmesh(tnum, c_lo, e_max):
        """写入单个 FMESH tally 卡（2 EMESH 档：[0,c_lo] 和 [c_lo,e_max]）。"""
        f.write(f'c FMESH{tnum}: bins [0,{c_lo:.2f}] and [{c_lo:.2f},{e_max:.3f}] MeV\n')
        f.write(f'FMESH{tnum}:p  geom=XYZ\n')
        f.write(f'     origin={-px:.6f} {-py:.6f} {-pz:.6f}\n')
        f.write(f'     imesh={px:.6f}  iints={NX}\n')
        f.write(f'     jmesh={py:.6f}  jints={NY}\n')
        f.write(f'     kmesh={pz:.6f}  kints={NZ}\n')
        f.write(f'     emesh={c_lo:.3f}  {e_max:.3f}\n')
        f.write('c\n')

    def _write_dedf_cards(tnum):
        """写入 DE/DF 注量-kerma 转换乘子卡（软组织 ICRU-44）。
        MCNP5 对 FMESH 输出乘以 DF(E) [pGy·cm²]，结果单位 pGy/src。
        """
        # 每行最多 6 个值（保证 80 列限制）
        def _fmt_vals(vals, per_line=6):
            out = []
            for i in range(0, len(vals), per_line):
                chunk = vals[i:i + per_line]
                out.append('     ' + '  '.join(f'{v:.4e}' for v in chunk))
            return '\n'.join(out)

        f.write(f'c DE{tnum}/DF{tnum}: fluence-to-kerma conversion (soft tissue ICRU-44)\n')
        f.write(f'c   DF [pGy·cm²] = E x (mu_en/rho) x 160.2  (NIST XCOM)\n')
        f.write(f'c   FMESH output [pGy/src] = integral[ Phi(E) x DF(E) dE ]\n')
        f.write(f'DE{tnum}\n')
        f.write(_fmt_vals(_DEDF_ENERGIES))
        f.write('\n')
        f.write(f'DF{tnum}\n')
        f.write(_fmt_vals(_DEDF_SOFT_KERMA))
        f.write('\n')
        f.write('c\n')

    if de_df_mode:
        # DE/DF 模式：单 FMESH14（无 EMESH）+ DE14/DF14 乘子
        # MCNP5 以每个光子的实际能量加权，消除 EMESH 代表能量误差
        f.write('c 3D mesh tally: photon kerma per source particle (DE/DF mode)\n')
        f.write('c   Output unit: pGy/src per voxel  (FMESH14 x DF14)\n')
        f.write('c   Step3 use --de-df-mode to treat .npy as kerma (skip fluence->dose)\n')
        _write_base_fmesh(14)
        _write_dedf_cards(14)
    else:
        cuts = MULTI_FMESH_CUTS.get(energy_mev)
        if cuts:
            c1, c2, c3, e_max = cuts
            f.write('c 3D mesh tallies: multi-FMESH 4-bin energy resolution\n')
            f.write(f'c  Effective bins: [0,{c1}] [{c1},{c2}] [{c2},{c3}] [{c3},{e_max}] MeV\n')
            _write_fmesh(14, c1, e_max)
            _write_fmesh(24, c2, e_max)
            _write_fmesh(34, c3, e_max)
        else:
            # 0.01/0.10 MeV：单 FMESH14，无 EMESH（总注量）
            f.write('c 3D mesh tally: photon fluence per source particle (no EMESH)\n')
            _write_base_fmesh(14)

    # ── F6:P 器官核能沉积计分（散射光子能量自动正确处理） ──────────────────
    # F6:P 直接统计单位质量内能量沉积 (MeV/g/src)，不需要 EMESH 能量分档，
    # 散射光子以其实际能量贡献，消除总注量×E_source 带来的高估（1 MeV 时约 78%）。
    # 计分号 = (WT_RULES 索引 + 1) × 10 + 6 → 16, 26, 36, ...（需与 step3 一致）
    # WT_RULES（必须与 mcnp_icrp_step3_compare.py 中 WT_RULES 完全一致，顺序相同）
    _W_F6 = 0.12 / 14
    _WT_RULES_F6 = [
        (['testes', 'testis'],                               0.08),
        (['ovaries', 'ovary'],                               0.08),
        (['colon', 'large intestine', 'rectum'],             0.12),
        (['lung'],                                           0.12),
        (['stomach wall', 'stomach'],                        0.12),
        (['red bone marrow', 'red marrow', 'spongiosa'],     0.12),
        (['breast', 'mammary', 'glandular tissue'],          0.12),
        (['urinary bladder', 'bladder wall', 'bladder'],     0.04),
        (['oesophagus', 'esophagus'],                        0.04),
        (['liver'],                                          0.04),
        (['thyroid'],                                        0.04),
        (['bone surface', 'endosteum', 'cortical'],          0.01),
        (['brain'],                                          0.01),
        (['salivary gland', 'salivary'],                     0.01),
        (['skin'],                                           0.01),
        (['adrenal'],                                        _W_F6),
        (['extrathoracic', 'et region', 'nasal passage'],    _W_F6),
        (['gallbladder', 'gall bladder'],                    _W_F6),
        (['heart wall', 'heart muscle', 'heart'],            _W_F6),
        (['kidney'],                                         _W_F6),
        (['lymph node', 'lymph'],                            _W_F6),
        (['muscle'],                                         _W_F6),
        (['oral mucosa'],                                    _W_F6),
        (['pancreas'],                                       _W_F6),
        (['prostate'],                                       _W_F6),
        (['small intestine'],                                _W_F6),
        (['spleen'],                                         _W_F6),
        (['thymus'],                                         _W_F6),
        (['uterus', 'cervix'],                               _W_F6),
    ]
    from collections import defaultdict as _dd
    _rule_groups = _dd(list)
    for _oid in sorted(unique_ids):
        if _oid == 0 or _oid not in organs:
            continue
        _, _, _name = organs[_oid]
        _nlc = _name.lower()
        for _idx, (_kws, _wt) in enumerate(_WT_RULES_F6):
            if any(_k in _nlc for _k in _kws):
                _rule_groups[_idx].append(_oid)
                break
    if _rule_groups:
        f.write('c F6:P organ kerma tallies (MeV/g/src) - scatter-correct photon energy deposition\n')
        f.write('c Tally index = (wT_rule_index+1)*10+6  -> same mapping used in step3\n')
        f.write('c NOTE: MCNP5 lattice F6 sums over all N_vox copies but divides by ONE voxel mass,\n')
        f.write('c       so raw value = N_vox * D_organ_avg. Step3 divides by N_vox to get D_avg.\n')
        f.write('c NOTE: FM cards intentionally omitted - MCNP5 ignores/misapplies FM on lattice F6.\n')
        for _ridx in sorted(_rule_groups.keys()):
            _oids = _rule_groups[_ridx]
            _kws, _wt = _WT_RULES_F6[_ridx]
            _tnum = (_ridx + 1) * 10 + 6
            _ostr = ' '.join(str(_o) for _o in _oids)
            # n_vox 写入注释，供 step3 后处理除以 N_vox 还原器官均值
            _n_vox = int(np.sum(np.isin(mask, _oids))) if mask is not None else 0
            _nv_str = f'  n_vox={_n_vox}' if _n_vox > 0 else '  n_vox=unknown'
            f.write(f'c  F{_tnum}: {_kws[0]}  wT={_wt:.5f}  oids={_oids[:3]}{"..." if len(_oids)>3 else ""}{_nv_str}\n')
            f.write(f'F{_tnum}:P  {_ostr}\n')
            # FM 卡不写 —— MCNP5 lattice F6 中 FM 被忽略或产生错误结果（输出 ~1 MeV/g/src）
            # N_vox 修正在 step3 post-processing 中通过掩膜计数完成
        f.write('c\n')

    # ── NPS & time limit ──
    # 默认使用 10^7；可通过 generate_input_file 的 nps 参数覆盖。
    # 预计运行时间：0.01 MeV ~2 h，0.1 MeV ~4 h，1 MeV ~20 h，10 MeV ~8 h。
    if not hasattr(write_data_section, '_nps'):
        write_data_section._nps = 10_000_000
    nps = write_data_section._nps
    prdmp_interval = max(500_000, nps // 10)
    ctme = 1800 if nps >= 50_000_000 else 720
    f.write('c Number of source histories\n')
    f.write(f'nps {nps}\n')
    f.write(f'prdmp {prdmp_interval} {prdmp_interval} 1\n')
    # ctme: computer-time limit in minutes.  Safety valve — if nps completes
    # first, ctme is ignored.  Set generously to avoid premature termination.
    f.write(f'ctme {ctme}\n')


def generate_input_file(mask: np.ndarray, organs: dict, media: dict,
                        energy_mev: float, out_path: Path,
                        phantom: str = 'AM', de_df_mode: bool = False):
    """为指定能量生成一个 MCNP5 输入文件。"""

    # 1. 找掩膜中实际出现的 organ_id
    unique_ids = set(int(v) for v in np.unique(mask))
    print(f'  能量 {energy_mev:.3f} MeV  → unique organ_ids: {len(unique_ids)} 个')

    # 2. 构建 fill 数组
    #    MCNP5 fill 顺序: iz 最慢, iy 中, ix 最快
    #    mask shape: (nx=127, ny=63, nz=111) → transpose → (nz, ny, nx) → flatten
    raw = mask.transpose(2, 1, 0).flatten().astype(np.int32)
    # fill=0 in MCNP5 lattice means "outside" → particle lost; remap to air universe
    fill_vals = np.where(raw == 0, AIR_UNIV, raw)
    assert len(fill_vals) == NX * NY * NZ

    # 3. 写文件
    with open(out_path, 'w', encoding='ascii') as f:
        # Title（第一行，≤80 字符）
        title = f'ICRP-110 {phantom} AP Photon E={energy_mev:.3f}MeV  ICRP-116 Validation'
        f.write(title[:80] + '\n')
        f.write('c\n')
        f.write(f'c  Source area: {2*PHANT_X:.2f} x {2*PHANT_Z:.2f} cm\n')
        f.write(f'c  Voxel cm:    {DS_VOX_CM}\n')
        f.write(f'c  Phantom cm:  {2*PHANT_X:.2f} x {2*PHANT_Y:.2f} x {2*PHANT_Z:.2f}\n')
        f.write('c\n')

        # ── Cell 块 ──
        write_cell_section(f, unique_ids, organs)
        write_lattice_cell(f, fill_vals)

        f.write('\n')   # 空行分隔 Cell / Surface

        # ── Surface 块 ──
        write_surface_section(f)

        f.write('\n')   # 空行分隔 Surface / Data

        # ── Data 块 ──
        write_data_section(f, unique_ids, organs, media, energy_mev, mask,
                           de_df_mode=de_df_mode)

    size_mb = out_path.stat().st_size / 1e6
    print(f'    写入 {out_path.name}  ({size_mb:.2f} MB)')


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='ICRP-110 验证 Step2: 生成 MCNP5 AP 输入')
    parser.add_argument('--mask',     default='icrp_validation/organ_mask_127x63x111.npy')
    parser.add_argument('--zip',      default='../P110 data V1.2/AM.zip')
    parser.add_argument('--out-dir',  default='icrp_validation/mcnp_inputs')
    parser.add_argument('--phot-lib', default=None,
        help='MCNP 光子截面库后缀，例如 .70p .12p .04p .24p；'
             '若不指定则自动从 xsdir 检测，检测失败则用默认 .04p (MCPLIB04)')
    parser.add_argument('--xsdir',    default=r'D:\LANL\xsdir',
        help='MCNP5 xsdir 文件路径，用于自动检测可用光子库')
    parser.add_argument('--phantom',  default='AM', choices=['AM', 'AF'],
        help='体模类型: AM (成年男性) 或 AF (成年女性)')
    parser.add_argument('--nps',      default=10_000_000, type=int,
        help='MCNP5 源粒子数 (默认: 10_000_000)')
    parser.add_argument('--de-df-mode', action='store_true',
        help='使用 DE/DF 注量-kerma 转换模式（推荐 MCNP5）：\n'
             '  写入单 FMESH14 + DE14/DF14 软组织 kerma 乘子，\n'
             '  取代多 FMESH EMESH 方案，消除代表能量误差。\n'
             '  运行后须配合 Step3 --de-df-mode 使用。')
    args = parser.parse_args()

    phantom = args.phantom

    # ── 若为 AF 体模，覆盖模块级物理常数 ────────────────────────────
    global DS_VOX_CM, HALF_VOX, PHANT_X, PHANT_Y, PHANT_Z, SRC_Y, FILL_X, FILL_Y, FILL_Z
    if phantom == 'AF':
        # AF phantom constants (downsampled to 127x63x111)
        _AF_FULL_X_CM = 299 * 1.775 / 10   # 53.0725 cm
        _AF_FULL_Y_CM = 137 * 1.775 / 10   # 24.3175 cm
        _AF_FULL_Z_CM = 348 * 4.84  / 10   # 168.432 cm
        NX_DS, NY_DS, NZ_DS = DS_SHAPE
        DS_VOX_CM = (
            _AF_FULL_X_CM / NX_DS,   # 0.41789 cm
            _AF_FULL_Y_CM / NY_DS,   # 0.38569 cm
            _AF_FULL_Z_CM / NZ_DS,   # 1.51741 cm
        )
        HALF_VOX = tuple(v / 2 for v in DS_VOX_CM)
        PHANT_X  = NX_DS * HALF_VOX[0]
        PHANT_Y  = NY_DS * HALF_VOX[1]
        PHANT_Z  = NZ_DS * HALF_VOX[2]
        SRC_Y    = -(PHANT_Y + 2.0)
        FILL_X   = (-(NX_DS // 2), NX_DS // 2)
        FILL_Y   = (-(NY_DS // 2), NY_DS // 2)
        FILL_Z   = (-(NZ_DS // 2), NZ_DS // 2)
        print(f'[Step2] AF 体模物理常数:')
        print(f'  DS_VOX_CM = {DS_VOX_CM}')
        print(f'  PHANT XYZ = {PHANT_X:.4f} x {PHANT_Y:.4f} x {PHANT_Z:.4f} cm')
        print(f'  SRC_Y     = {SRC_Y:.4f} cm')

    # ── 配置 NPS ─────────────────────────────────────────────────────
    write_data_section._nps = args.nps
    print(f'[Step2] nps = {args.nps:,}')

    # ── 确定光子截面库后缀 ───────────────────────────────────
    global PHOT_SUFFIX, ZAID_MAP
    if args.phot_lib:
        PHOT_SUFFIX = args.phot_lib
        print(f'[Step2] 使用指定光子库后缀: {PHOT_SUFFIX}')
    else:
        detected = detect_phot_lib(args.xsdir)
        if detected:
            PHOT_SUFFIX = detected
            print(f'[Step2] 从 xsdir 自动检测到光子库: {PHOT_SUFFIX}  ({args.xsdir})')
        else:
            print(f'[Step2] 警告: 未能检测 xsdir ({args.xsdir})，使用默认: {PHOT_SUFFIX} (MCPLIB04)')
            print(f'[Step2] 若您的安装使用其他库，请用 --phot-lib 指定后缀')
    ZAID_MAP = build_zaid_map(PHOT_SUFFIX)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print('[Step2] 加载数据 ...')
    mask, organs, media = load_data(args.mask, args.zip, phantom=phantom)

    print(f'\n体模参数 (phantom={phantom}):')
    print(f'  shape       = {DS_SHAPE}')
    print(f'  voxel cm    = {DS_VOX_CM}')
    print(f'  phantom cm  = {2*PHANT_X:.3f} x {2*PHANT_Y:.3f} x {2*PHANT_Z:.3f}')
    print(f'  fill range  = {FILL_X} {FILL_Y} {FILL_Z}')
    print(f'  source Y    = {SRC_Y:.3f} cm\n')

    # ── 文件名前缀：AM → ap_，AF → af_ ───────────────────────
    prefix = 'af_' if phantom == 'AF' else 'ap_'

    de_df_mode = args.de_df_mode
    if de_df_mode:
        print('[Step2] ★ DE/DF 模式：FMESH14 + DE14/DF14 软组织 kerma 乘子（推荐 MCNP5）')
        print('        Step3 须同时加 --de-df-mode 参数')

    print('[Step2] 生成 MCNP5 输入文件 ...')
    for e in ENERGIES_MEV:
        fname = f'{prefix}photon_E{e:.3f}MeV.inp'
        out_path = out_dir / fname
        generate_input_file(mask, organs, media, e, out_path,
                            phantom=phantom, de_df_mode=de_df_mode)

    print(f'\nOK 第二步完成 (phantom={phantom})，输入文件位于 {out_dir}/')
    if de_df_mode:
        print('  后续: 用 MCNP5 运行各文件，再执行:')
        print('    python mcnp_icrp_step3_compare.py --de-df-mode')
    else:
        print('  后续: 用 MCNP5 运行各文件，再执行第三步提取器官剂量并与 ICRP-116 对比。')


if __name__ == '__main__':
    main()
