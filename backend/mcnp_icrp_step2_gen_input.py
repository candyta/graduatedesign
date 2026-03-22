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

# FMESH EMESH 能量分档（用于 energy-resolved 注量→剂量换算，解决散射光子能量高估问题）
# 格式: {能量(MeV): [能量分档边界列表(MeV)]}
# 最后一个 bin 包含初级光子；前面 bins 捕获不同能量的散射光子
# 每个 bin 的代表性能量（用于 μ_en/ρ 查表）同时在 Step3 中定义
EMESH_BINS = {
    0.01:  [0.000, 0.012],                          # 1档: 10 keV Compton散射能量变化极小
    0.10:  [0.000, 0.050, 0.095, 0.110],            # 3档: 低能散射/中能散射/初级
    1.00:  [0.000, 0.200, 0.500, 0.800, 1.050],     # 4档: 逐步覆盖Compton散射光子
    10.00: [0.000, 1.000, 3.000, 7.000, 10.500],    # 4档: 对散射+湮灭光子分档
}

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


def load_data(mask_path: str, zip_path: str):
    """
    加载掩膜 + 器官/组织数据。

    Returns
    -------
    mask   : np.ndarray shape (127, 63, 111) uint8
    organs : {organ_id: (tissue_num, density, name)}
    media  : {tissue_num: (name, {Z: fraction})}
    """
    mask = np.load(mask_path)
    assert mask.shape == DS_SHAPE, f"掩膜 shape 应为 {DS_SHAPE}，实为 {mask.shape}"

    with zipfile.ZipFile(zip_path, 'r') as z:
        organs_text = z.read('AM/AM_organs.dat').decode('utf-8', errors='replace')
        media_text  = z.read('AM/AM_media.dat' ).decode('utf-8', errors='replace')

    organs = parse_organs(organs_text.splitlines())
    media  = parse_media(media_text.splitlines())
    print(f"  已加载掩膜 {mask.shape}，器官={len(organs)} 个，组织类型={len(media)} 种")
    return mask, organs, media


# ═══════════════════════════════════════════════════════════════
# MCNP5 输入文件生成
# ═══════════════════════════════════════════════════════════════

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
    hx, hy, hz = HALF_VOX
    f.write(f'c Unit voxel base cell (half-spacing = {hx:.4f}, {hy:.4f}, {hz:.4f} cm)\n')
    f.write(f'11  px   {hx:.4f}\n')
    f.write(f'12  px  -{hx:.4f}\n')
    f.write(f'13  py   {hy:.4f}\n')
    f.write(f'14  py  -{hy:.4f}\n')
    f.write(f'15  pz   {hz:.4f}\n')
    f.write(f'16  pz  -{hz:.4f}\n')
    f.write('c\n')
    # Use 4 decimal places so phantom surfaces equal the exact lattice extent.
    # With :.3f, PHANT_X=27.1399 rounds UP to 27.140, creating a 0.0001 cm gap
    # between the phantom bounding box and the lattice edge.  Source particles
    # born in that sliver have no valid lattice element → "zero lattice element
    # hit" → MCNP5 abort / hang.  Using :.4f gives 27.1399, exactly matching
    # the lattice, eliminating the gap entirely.
    f.write(f'c Phantom bounding box ({PHANT_X:.4f} x {PHANT_Y:.4f} x {PHANT_Z:.4f} cm)\n')
    f.write(f'111  px   {PHANT_X:.4f}\n')
    f.write(f'112  px  -{PHANT_X:.4f}\n')
    f.write(f'113  py   {PHANT_Y:.4f}\n')
    f.write(f'114  py  -{PHANT_Y:.4f}\n')
    f.write(f'115  pz   {PHANT_Z:.4f}\n')
    f.write(f'116  pz  -{PHANT_Z:.4f}\n')
    f.write('c\n')
    f.write('c World sphere\n')
    f.write('9999  so  300.0\n')


def write_data_section(f, unique_ids, organs, media, energy_mev):
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
    f.write( 'SDEF  par=2\n')
    f.write(f'      erg={energy_mev:.4f}\n')
    f.write( '      dir=1  vec=0 1 0\n')
    f.write(f'      x=d1  y={SRC_Y:.4f}  z=d2\n')
    # Use 4 decimal places so source range matches lattice extent exactly.
    # With :.3f, SI1 would allow x up to 27.140, but the lattice only covers
    # |x| ≤ 27.1399.  Source particles born in the 0.0001 cm gap enter the
    # phantom container cell but find no lattice element → "zero lattice
    # element hit".  Using :.4f clamps the range to 27.1399 (exact lattice edge).
    f.write(f'SI1  {-PHANT_X:.4f}  {PHANT_X:.4f}\n')
    f.write( 'SP1  0  1\n')
    f.write(f'SI2  {-PHANT_Z:.4f}  {PHANT_Z:.4f}\n')
    f.write( 'SP2  0  1\n')
    f.write('c\n')

    # ── 计分卡：3-D 网格通量（含 EMESH 能量分档） ──
    # EMESH 将总注量分解到多个能量区间，允许 Step3 对每档用正确的 μ_en/ρ 换算剂量，
    # 避免用初级光子能量处理散射光子导致的系统性高估（在 1~10 MeV 可达 ~80%）。
    f.write('c 3D mesh tally: photon fluence per source particle, energy-resolved\n')
    f.write('c Post-process with mu_en/rho per energy bin for accurate organ absorbed dose\n')
    f.write('FMESH14:p  geom=XYZ\n')
    f.write(f'     origin={-PHANT_X:.3f} {-PHANT_Y:.3f} {-PHANT_Z:.3f}\n')
    f.write(f'     imesh={PHANT_X:.3f}  iints={NX}\n')
    f.write(f'     jmesh={PHANT_Y:.3f}  jints={NY}\n')
    f.write(f'     kmesh={PHANT_Z:.3f}  kints={NZ}\n')
    # 添加能量分档
    bins = EMESH_BINS.get(energy_mev)
    if bins and len(bins) >= 2:
        n_bins = len(bins) - 1
        bin_str = '  '.join(f'{b:.3f}' for b in bins)
        f.write(f'     EMESH={n_bins}  {bin_str}\n')
        f.write(f'c  EMESH: {n_bins} energy bins, boundaries = [{bin_str}] MeV\n')
    f.write('c\n')

    # ── NPS & time limit ──
    f.write('c Number of source histories\n')
    f.write('nps 10000000\n')
    f.write('prdmp 1000000 1000000 1\n')
    # ctme: computer-time limit in minutes.  If MCNP5 geometry issues stall a
    # run, it will still exit cleanly and write a partial output file rather
    # than hanging until the Python subprocess timeout (8 h).  360 min = 6 h.
    f.write('ctme 360\n')


def generate_input_file(mask: np.ndarray, organs: dict, media: dict,
                        energy_mev: float, out_path: Path):
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
        title = f'ICRP-110 AM AP Photon E={energy_mev:.3f}MeV  ICRP-116 Validation'
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
        write_data_section(f, unique_ids, organs, media, energy_mev)

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
    args = parser.parse_args()

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
    mask, organs, media = load_data(args.mask, args.zip)

    print(f'\n体模参数:')
    print(f'  shape       = {DS_SHAPE}')
    print(f'  voxel cm    = {DS_VOX_CM}')
    print(f'  phantom cm  = {2*PHANT_X:.3f} x {2*PHANT_Y:.3f} x {2*PHANT_Z:.3f}')
    print(f'  fill range  = {FILL_X} {FILL_Y} {FILL_Z}')
    print(f'  source Y    = {SRC_Y:.3f} cm\n')

    print('[Step2] 生成 MCNP5 输入文件 ...')
    for e in ENERGIES_MEV:
        fname = f'ap_photon_E{e:.3f}MeV.inp'
        out_path = out_dir / fname
        generate_input_file(mask, organs, media, e, out_path)

    print(f'\nOK 第二步完成，输入文件位于 {out_dir}/')
    print('  后续: 用 MCNP5 运行各文件，再执行第三步提取器官剂量并与 ICRP-116 对比。')


if __name__ == '__main__':
    main()
