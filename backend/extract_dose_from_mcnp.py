#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从MCNP输出文件提取剂量数据

支持两种格式：
1. Mesh Tally输出 (xxxm.msht)
2. 标准输出文件 (xxx.o) 中的tally数据
"""

# 修复Windows编码
import sys
import os
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    os.environ['PYTHONIOENCODING'] = 'utf-8'

import numpy as np
import re
from pathlib import Path


def extract_mesh_tally(mesh_file: str, grid_shape: tuple = None,
                       tally_num: int = 14) -> dict:
    """
    从Mesh Tally文件提取数据，自动检测是否有 EMESH 能量分档。

    Parameters
    ----------
    mesh_file  : meshtal 文件路径
    grid_shape : 备用网格尺寸 (nx, ny, nz)，解析失败时使用
    tally_num  : FMESH tally 编号，默认 14（FMESH14）；多 FMESH 方案时可为 24/34

    返回 dict:
      'total'  : np.ndarray shape (nz, ny, nx)  — 全能量合计注量
      'bins'   : list of np.ndarray (nz,ny,nx)  — 各能量档注量（无 EMESH 时为空列表）
      'e_bounds': list of float  — 能量档边界 (MeV)（无 EMESH 时为空列表）
      'n_ebins': int             — 能量档数量（无 EMESH 时为 0）
      'nx','ny','nz': int

    MCNP5 meshtal 格式（含 EMESH 时）:
      每行: X_center Y_center Z_center E_upper Result Rel_Error
      外层循环 Z(慢) → Y → X → E(快)
    """
    tnum_str = str(tally_num)

    def _is_target_tally(line):
        """判断该行是否是目标 tally 的 'Mesh Tally Number N' 行。"""
        if 'Mesh Tally Number' not in line:
            return False
        parts = line.split()
        return parts and parts[-1] == tnum_str

    print(f"\n[从Mesh Tally {tally_num} 提取]")
    print(f"文件: {mesh_file}")

    if not Path(mesh_file).exists():
        raise FileNotFoundError(f"Mesh tally文件不存在: {mesh_file}")

    with open(mesh_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    # ===== 第一遍：从meshtal头部解析网格尺寸 + 能量分档 =====
    in_target = False
    parsing_dir = None
    dir_values  = {'X': [], 'Y': [], 'Z': []}
    e_bounds    = []   # 能量档边界

    for i, line in enumerate(lines):
        if _is_target_tally(line):
            in_target = True
            print(f"OK 找到Mesh Tally {tally_num} 在第{i+1}行")
            continue
        if in_target and 'Mesh Tally Number' in line and not _is_target_tally(line):
            break
        if not in_target:
            continue

        stripped = line.strip()

        # 解析 "X direction:" / "Y direction:" / "Z direction:" 行
        matched_dir = False
        for axis in ('X', 'Y', 'Z'):
            if stripped.lower().startswith(f'{axis.lower()} direction'):
                parsing_dir = axis
                rest = stripped.split(':', 1)[-1].strip()
                for tok in rest.split():
                    try:
                        dir_values[axis].append(float(tok))
                    except ValueError:
                        pass
                matched_dir = True
                break

        if not matched_dir:
            # 解析能量档边界行 "Energy bin boundaries: ..."
            if 'energy bin' in stripped.lower() or 'energy boundaries' in stripped.lower():
                parsing_dir = 'E'
                rest = stripped.split(':', 1)[-1].strip()
                for tok in rest.split():
                    try:
                        e_bounds.append(float(tok))
                    except ValueError:
                        pass
            elif parsing_dir and stripped and not any(
                    k in stripped.lower() for k in
                    ('direction', 'result', 'tally', '===', '---', 'number')):
                if stripped.lower().startswith(('x ', 'y ', 'z ')):
                    parsing_dir = None
                else:
                    target = dir_values[parsing_dir] if parsing_dir in ('X', 'Y', 'Z') else e_bounds
                    for tok in stripped.split():
                        try:
                            target.append(float(tok))
                        except ValueError:
                            pass

        # 遇到数据表头停止头部解析
        if 'Result' in stripped and 'Rel' in stripped:
            break

    in_mesh14 = in_target  # 别名，供下方第二遍扫描复用

    # 确定网格尺寸
    if dir_values['X'] and dir_values['Y'] and dir_values['Z']:
        nx = len(dir_values['X']) - 1
        ny = len(dir_values['Y']) - 1
        nz = len(dir_values['Z']) - 1
        print(f"OK 从meshtal头部读取网格: {nx}×{ny}×{nz}")
    elif grid_shape is not None:
        nx, ny, nz = grid_shape
        print(f"[警告] 使用传入的 grid_shape: {nx}×{ny}×{nz}")
    else:
        nx, ny, nz = 127, 63, 111
        print(f"[警告] 使用默认fallback网格: {nx}×{ny}×{nz}")

    # MCNP5 EMESH 在 meshtal 头部只写上界（无隐含下界 0.0）。
    # 补全下界使 e_bounds 满足 len = n_bins + 1，与 Step3 约定一致。
    if e_bounds and e_bounds[0] > 0:
        e_bounds.insert(0, 0.0)

    # MCNP5 1.14 即使没有 EMESH 卡也会在 meshtal 中写出默认的 2-bin 能量结构：
    #   [0.0, 0.001, 1e+36]  — 上界 1e36 是 MCNP5 内部"无穷大"哨兵值。
    # 这不是真正的用户自定义 EMESH，直接使用会导致 bin1 代表能量 = sqrt(0.001×1e36)
    # ≈ 3e16 MeV，造成剂量计算结果完全错误。检测并丢弃这类默认结构。
    if e_bounds and e_bounds[-1] > 1000.0:
        print(f"  [EMESH] 检测到 MCNP5 默认能量哨兵（上界={e_bounds[-1]:.0e} MeV），忽略 EMESH，使用总注量模式")
        e_bounds = []

    n_ebins = max(len(e_bounds) - 1, 0)
    if n_ebins > 0:
        print(f"OK 检测到 EMESH: {n_ebins} 个能量档，边界 = {e_bounds} MeV")
    else:
        print("  无 EMESH，提取全能量总注量")

    expected_voxels = nx * ny * nz
    # 含 EMESH 时，每个体素有 n_ebins 行数据
    expected_rows = expected_voxels * max(n_ebins, 1)
    print(f"网格: {nx}×{ny}×{nz} = {expected_voxels} 体素，期望数据行 = {expected_rows}")

    # ===== 第二遍：提取数据值 =====
    in_mesh14 = False
    values = []
    data_start_found = False

    for line in lines:
        if _is_target_tally(line):
            in_mesh14 = True
            data_start_found = False
            continue
        if in_mesh14 and 'Mesh Tally Number' in line and not _is_target_tally(line):
            break
        if not in_mesh14:
            continue

        if any(k in line for k in ['Result', 'Rel Error', 'Rel. Error']):
            data_start_found = True
            continue
        if not data_start_found:
            continue

        stripped = line.strip()
        if not stripped or stripped.startswith(('#', 'c', 'C')):
            continue

        parts = stripped.split()
        if len(parts) < 2:
            continue

        try:
            if len(parts) >= 6:
                result = float(parts[4])   # X Y Z Energy Result Error
            elif len(parts) >= 5:
                result = float(parts[3])   # X Y Z Result Error
            elif len(parts) >= 2:
                result = float(parts[0])
            else:
                continue
            if abs(result) > 1e30 or result < 0:
                result = 0.0
            values.append(result)
        except (ValueError, IndexError):
            continue

    print(f"提取值数量: {len(values)}")

    if len(values) == 0:
        print("[错误] 未提取到任何数据！")
        total = np.zeros((nz, ny, nx), dtype=np.float64)
        return {'total': total, 'bins': [], 'e_bounds': e_bounds,
                'n_ebins': 0, 'nx': nx, 'ny': ny, 'nz': nz}

    # ===== 重塑数据 =====
    # MCNP5 FMESH 输出顺序: Z(慢) → Y → X → E(快，仅 EMESH 时)
    if n_ebins > 0:
        # 有 EMESH: shape (nz, ny, nx, n_ebins)
        total_expected = expected_voxels * n_ebins
        if len(values) < total_expected:
            values.extend([0.0] * (total_expected - len(values)))
        elif len(values) > total_expected:
            values = values[:total_expected]
        arr = np.array(values, dtype=np.float64).reshape((nz, ny, nx, n_ebins))
        bins_list = [arr[:, :, :, k] for k in range(n_ebins)]
        total = arr.sum(axis=3)
    else:
        # 无 EMESH: shape (nz, ny, nx)
        if len(values) < expected_voxels:
            values.extend([0.0] * (expected_voxels - len(values)))
        elif len(values) > expected_voxels:
            values = values[:expected_voxels]
        total = np.array(values, dtype=np.float64).reshape((nz, ny, nx))
        bins_list = []

    non_zero = int(np.count_nonzero(total))
    print(f"\nOK 数组重塑完成  形状(nz,ny,nx)={total.shape}  "
          f"非零={non_zero}({non_zero/total.size*100:.1f}%)  "
          f"范围[{total.min():.2e}, {total.max():.2e}]  均值={total.mean():.2e}")

    return {'total': total, 'bins': bins_list, 'e_bounds': e_bounds,
            'n_ebins': n_ebins, 'nx': nx, 'ny': ny, 'nz': nz}


def _legacy_array_from_result(result: dict) -> np.ndarray:
    """向后兼容：从新格式 dict 返回旧格式 ndarray(nz,ny,nx)。"""
    return result['total']


def extract_from_standard_output(output_file: str) -> np.ndarray:
    """
    从标准.o文件中检查 MCNP 是否正常完成，并尝试提取 meshtal 数据。
    若未找到有效 tally 数据则抛出异常（不再返回随机数）。
    """
    print("\n[从标准输出检查]")
    print(f"文件: {output_file}")

    with open(output_file, 'r', errors='ignore') as f:
        content = f.read()

    # 检查常见 MCNP 失败标志
    fatal_lines = [ln.strip() for ln in content.splitlines()
                   if 'fatal error' in ln.lower() or 'cross-section' in ln.lower()
                   or 'cannot find' in ln.lower() or 'bad trouble' in ln.lower()]
    if fatal_lines:
        print("[错误] MCNP 输出包含致命错误:")
        for ln in fatal_lines[:5]:
            print(f"  {ln}")
        raise RuntimeError(
            "MCNP 运行失败（fatal error）。\n"
            "最可能原因：xsdir 中缺少所用光子截面库（如 .70p）。\n"
            "请检查 D:\\LANL\\xsdir，确认材料卡中的 ZAID 后缀在 xsdir 中存在，\n"
            "或通过 --phot-lib 参数指定实际可用的截面库后缀后重新运行 Step2b。"
        )

    # meshtal 应由 Step2b 直接读取；若走到此处说明 meshtal 未找到
    raise RuntimeError(
        f"在 {output_file} 中未找到有效 meshtal 数据。\n"
        "请确认 MCNP 工作目录中存在 meshtal 文件，并检查 FMESH tally 设置。"
    )


def extract_dose_from_mcnp(output_file: str,
                           grid_shape: tuple = (254, 127, 222)) -> dict:
    """
    主提取函数：自动选择合适的提取方法，支持 EMESH 能量分档。

    Parameters:
    -----------
    output_file : str  — MCNP输出文件路径 (xxx.o)
    grid_shape  : tuple — 网格形状 (nx, ny, nz)

    Returns:
    --------
    dict 含:
      'total'   : np.ndarray (nz,ny,nx)  全能量合计注量
      'bins'    : list of ndarray         各能量档注量（无 EMESH 时为空列表）
      'e_bounds': list of float           能量档边界 MeV
      'n_ebins' : int
    """
    print("=" * 60)
    print("MCNP剂量数据提取")
    print("=" * 60)
    print(f"输入文件: {output_file}")
    print(f"目标网格: {grid_shape[0]}×{grid_shape[1]}×{grid_shape[2]}")

    output_path = Path(output_file)

    possible_mesh_files = [
        output_path.parent / f"{output_path.stem}m.msht",
        output_path.parent / "meshtal",
        output_path.parent / f"mesh{output_path.stem}",
        output_path.parent / f"{output_path.stem}.meshtal",
    ]

    mesh_file = None
    for candidate in possible_mesh_files:
        if candidate.exists():
            mesh_file = candidate
            print(f"\n[成功] 找到Mesh Tally文件: {mesh_file}")
            break

    if mesh_file:
        try:
            result = extract_mesh_tally(str(mesh_file), grid_shape)
        except Exception as e:
            print(f"[警告] Mesh Tally提取失败: {e}")
            raise RuntimeError(f"meshtal 提取失败: {e}") from e
    else:
        print(f"\n[失败] 未找到Mesh Tally文件")
        for pf in possible_mesh_files:
            print(f"  - {pf}")
        extract_from_standard_output(output_file)   # 会抛出异常
        result = None  # 不会到达此行

    dose_array = result['total']
    print(f"\n[提取结果] 形状={dose_array.shape}  "
          f"范围=[{dose_array.min():.2e}, {dose_array.max():.2e}]  "
          f"均值={dose_array.mean():.2e}  "
          f"非零={np.count_nonzero(dose_array)/dose_array.size*100:.1f}%")
    if result['n_ebins'] > 0:
        print(f"  EMESH: {result['n_ebins']} 档，边界={result['e_bounds']} MeV")

    return result


def save_dose_npy(result, output_path: str):
    """
    保存提取结果为 .npy 文件（向后兼容 + EMESH 扩展）。

    - fluence_E*.npy          : 总注量 (nz,ny,nx)（始终保存）
    - fluence_E*_bin{k}.npy   : 第 k 档注量 (nz,ny,nx)（仅 EMESH 时保存）
    - fluence_E*_ebounds.npy  : 能量档边界 (nz,ny,nx) → 1D array（仅 EMESH 时保存）
    """
    # 向后兼容：允许直接传入 ndarray
    if isinstance(result, np.ndarray):
        result = {'total': result, 'bins': [], 'e_bounds': [], 'n_ebins': 0}

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    np.save(output_path, result['total'])
    print(f"\n[成功] 总注量已保存: {output_path}  ({output_path.stat().st_size/1024:.1f} KB)")

    if result['n_ebins'] > 0:
        stem = output_path.stem   # e.g. "fluence_E1.000MeV"
        suffix = output_path.suffix
        parent = output_path.parent
        for k, bin_arr in enumerate(result['bins']):
            bin_path = parent / f"{stem}_bin{k}{suffix}"
            np.save(bin_path, bin_arr)
            print(f"  bin{k}: {bin_path}  ({bin_path.stat().st_size/1024:.1f} KB)")
        eb_path = parent / f"{stem}_ebounds{suffix}"
        np.save(eb_path, np.array(result['e_bounds'], dtype=np.float64))
        print(f"  能量档边界: {eb_path}")


def parse_f6_tallies(output_file: str) -> dict:
    """
    从 MCNP .o 文件中解析 F6:P 计分结果（能量沉积，MeV/g/src）。

    返回 dict:
      {tally_num (int): {'value': float, 'rel_err': float}}

    MCNP5 .o 文件中 F6 计分的典型格式：
      1tally        16          nps = ...
                           tally type 6    energy deposition ...
       cell  96
             1.23456E-07   0.0012
       ...
       total
             1.78902E-07   0.0008
    """
    import json as _json

    result = {}
    try:
        with open(output_file, 'r', errors='ignore') as fh:
            lines = fh.readlines()
    except Exception:
        return result

    cur_tally = None
    in_tally6 = False

    for i, raw in enumerate(lines):
        line = raw.strip()

        # 识别 "1tally  N" 行（可能有多个空格）
        m = re.match(r'^1tally\s+(\d+)', line)
        if m:
            cur_tally = int(m.group(1))
            in_tally6 = False
            continue

        if cur_tally is None:
            continue

        # 检测是否为 type-6 tally
        if 'tally type 6' in line.lower() or 'energy deposition' in line.lower():
            in_tally6 = True
            continue

        if not in_tally6:
            continue

        # 找 "total" 行的数值
        # MCNP5 标准格式:  "total  MEAN  REL_ERR"       3列（strip 后 parts[0]='total'）
        # MCNP5 prdmp格式: "total  CUMSUM  MEAN  REL_ERR" 4列（prdmp 中间存档，每个检查点输出）
        # 某些 MCNP 版本:  "total"（单独一行，值在下一行）
        #
        # ⚠ prdmp 中间存档格式陷阱：启用 prdmp 后 MCNP5 在每个存档点输出一份完整的
        #   tally 统计表，格式为 "total  CUMSUM  MEAN  REL_ERR"（4 列），其中
        #   CUMSUM = NPS × MEAN。对小器官（N_vox 小）CUMSUM 可能仅为 10~1000，
        #   旧代码用幅度判断（v1 > 1e4）会漏判 → 误把 CUMSUM 当 MEAN 存储，再被
        #   物理上界过滤掉。正确做法：4 列即为 prdmp，3 列即为标准，无需幅度判断。
        #
        # 物理上界过滤（防御性）：MCNP5 lattice 模式下 F6:P 原始值 = N_vox × D_avg。
        # 最大器官（红骨髓 N_vox ≈ 2e4）× D_avg（≈0.1 MeV/g/src）≈ 2000，
        # 远低于 TFC 累计值（NPS × MEAN ≈ 1e7~1e8）。
        # 上界取 1e4 可安全区分器官 F6 值与 TFC 行。
        _F6_PHYS_MAX = 1e4  # MeV/g/src
        if re.match(r'^total\b', line, re.IGNORECASE):
            parts = line.split()
            val = None
            rel = 0.0
            if len(parts) >= 4:
                # prdmp 4列格式: total  CUMSUM  MEAN  REL_ERR → 取 parts[2], parts[3]
                try:
                    val = float(parts[2])
                    rel = float(parts[3])
                except (ValueError, IndexError):
                    pass
            elif len(parts) >= 3:
                # 标准 3列格式: total  MEAN  REL_ERR → 取 parts[1], parts[2]
                try:
                    val = float(parts[1])
                    rel = float(parts[2])
                except (ValueError, IndexError):
                    pass
            elif len(parts) == 1:
                # "total" 单独占一行，值在下一行
                for j in range(i + 1, min(i + 4, len(lines))):
                    nxt = lines[j].strip()
                    if not nxt:
                        continue
                    nxt_parts = nxt.split()
                    try:
                        val = float(nxt_parts[0])
                        rel = float(nxt_parts[1]) if len(nxt_parts) >= 2 else 0.0
                    except (ValueError, IndexError):
                        pass
                    break
            if val is not None:
                # MCNP5 prdmp TFC 输出 rel 为 (1 + sigma/mean) 格式，例如
                # 0.04% 误差输出为 1.0004。归一化为纯 sigma/mean 供后续使用。
                if rel > 1.0:
                    rel = rel - 1.0
                # 物理上界过滤：跳过不合理大值，保留已有的合理结果
                if val > _F6_PHYS_MAX:
                    print(f"  [F6] tally {cur_tally}: 跳过不合理大值 {val:.4e} MeV/g/src"
                          f"（>{_F6_PHYS_MAX} 物理上界，可能来自 TFC 段）")
                else:
                    result[cur_tally] = {'value': val, 'rel_err': rel}
                    print(f"  [F6] tally {cur_tally}: {val:.4e} ± {rel:.4f} (rel)")
            # 不在此处设置 in_tally6 = False，继续寻找同 tally 后续的合并 total。
            # 遇到下一个 "1tally N" 行时会自动重置 cur_tally 和 in_tally6。

    if result:
        print(f"[F6] 共解析 {len(result)} 个 F6:P 计分")
    else:
        print("[F6] 未找到 F6:P 计分结果（可能该运行未写 F6 tallies）")
    return result


def save_f6_json(f6_dict: dict, npy_path) -> None:
    """将 F6 计分结果保存为 JSON 文件（与 fluence npy 同目录，同前缀）。"""
    import json as _json
    npy_path = Path(npy_path)
    json_path = npy_path.parent / (npy_path.stem + '_f6doses.json')
    with open(json_path, 'w', encoding='utf-8') as fh:
        _json.dump(f6_dict, fh, indent=2)
    print(f"[F6] 计分已保存: {json_path}")


def save_extra_fmesh_bins(mesh_file: str, npy_path) -> None:
    """
    多 FMESH 方案：从 meshtal 中提取 FMESH24 和 FMESH34 的 bin 数据，
    保存为 {stem}_fm24_bin0.npy、{stem}_fm24_bin1.npy（以及 fm34）。

    仅当 meshtal 中实际存在对应 tally 时才保存；静默跳过不存在的 tally。
    """
    npy_path = Path(npy_path)
    stem   = npy_path.stem    # e.g. "fluence_E1.000MeV"
    parent = npy_path.parent

    for tnum in (24, 34):
        tag = f'fm{tnum}'
        try:
            r = extract_mesh_tally(mesh_file, tally_num=tnum)
            if r['n_ebins'] < 2:
                print(f"  [多FMESH] FMESH{tnum} 未检测到 2 个 EMESH 档，跳过")
                continue
            for k, bin_arr in enumerate(r['bins']):
                p = parent / f"{stem}_{tag}_bin{k}.npy"
                np.save(p, bin_arr)
                print(f"  [多FMESH] 保存 FMESH{tnum} bin{k}: {p.name}  "
                      f"({p.stat().st_size/1024:.1f} KB)")
            eb_path = parent / f"{stem}_{tag}_ebounds.npy"
            np.save(eb_path, np.array(r['e_bounds'], dtype=np.float64))
            print(f"  [多FMESH] 保存 FMESH{tnum} ebounds: {eb_path.name}")
        except Exception as exc:
            # meshtal 中没有该 tally 时正常（非错误）
            print(f"  [多FMESH] FMESH{tnum} 未找到或提取失败（{exc}），跳过")


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python extract_dose_from_mcnp.py <mcnp_output.o> [output.npy]")
        print("\n示例:")
        print("  python extract_dose_from_mcnp.py C:/o/w123456.o")
        print("  python extract_dose_from_mcnp.py C:/o/w123456.o dose_data.npy")
        sys.exit(1)

    output_file = sys.argv[1]

    # 输出路径
    if len(sys.argv) >= 3:
        npy_path = sys.argv[2]
    else:
        npy_path = Path(output_file).parent / "dose_data.npy"

    try:
        # 提取 FMESH 注量
        result = extract_dose_from_mcnp(output_file)

        # 保存为.npy（支持 EMESH 分档）
        save_dose_npy(result, npy_path)

        # 多 FMESH 方案：提取 FMESH24/34 的 bin 数据（若 INP 中有定义）
        output_path = Path(output_file)
        possible_mesh = [
            output_path.parent / f"{output_path.stem}m.msht",
            output_path.parent / "meshtal",
            output_path.parent / f"mesh{output_path.stem}",
            output_path.parent / f"{output_path.stem}.meshtal",
        ]
        found_mesh = next((p for p in possible_mesh if p.exists()), None)
        if found_mesh:
            save_extra_fmesh_bins(str(found_mesh), npy_path)

        # 提取并保存 F6 计分（散射正确的器官剂量）
        f6 = parse_f6_tallies(output_file)
        if f6:
            save_f6_json(f6, npy_path)

        print("\n" + "="*60)
        print("[成功] 完成！")
        print("="*60)

    except Exception as e:
        print(f"\n[错误] 错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()