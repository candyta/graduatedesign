#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
MCNP ICRP-110 验证 — Step 2b：在 Windows 上运行 MCNP5（4个能量点）
====================================================================
复用现有 g5.bat + extract_dose_from_mcnp.py 基础设施，
对 Step2 生成的 4 个 AP 光子输入文件逐一调用 MCNP5，
提取 meshtal → npy，保存到 icrp_validation/mcnp_outputs/。

【运行方法】
  将此脚本复制到 Windows 机器（与 run_batch.py 同目录），执行：
    D:\python.exe mcnp_icrp_step2b_run_mcnp.py

  也可指定参数：
    D:\python.exe mcnp_icrp_step2b_run_mcnp.py ^
        --inp-dir  "C:\my-app3\web\backend\icrp_validation\mcnp_inputs" ^
        --out-dir  "C:\my-app3\web\backend\icrp_validation\mcnp_outputs" ^
        --g5-bat   "D:\LANL\g5.bat" ^
        --work-dir "C:\i"

【输出】（icrp_validation/mcnp_outputs/）
  fluence_E0.010MeV.npy
  fluence_E0.100MeV.npy
  fluence_E1.000MeV.npy
  fluence_E10.000MeV.npy
  run_log.txt
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# ─── 前置步骤脚本 / 数据路径（相对于 backend 目录） ─────────────
STEP1_SCRIPT  = "mcnp_icrp_step1_organ_mask.py"
STEP2_SCRIPT  = "mcnp_icrp_step2_gen_input.py"
ICRP110_ZIP   = os.path.join("..", "P110 data V1.2", "AM.zip")
ORGAN_MASK    = os.path.join("icrp_validation", "organ_mask_127x63x111.npy")

# ─── AF 体模路径 ──────────────────────────────────────────────────
AF_ORGAN_MASK  = os.path.join("icrp_validation", "organ_mask_127x63x111_AF.npy")
AF_ICRP110_ZIP = os.path.join("..", "P110 data V1.2", "AF.zip")

# ─── 默认路径（与现有 run_batch.py / g5.bat 体系一致） ───────────
DEFAULT_G5_BAT    = r"D:\LANL\g5.bat"
DEFAULT_XSDIR     = r"D:\LANL\xsdir"  # MCNP5 截面目录文件
DEFAULT_WORK_DIR  = r"C:\i"            # MCNP5 工作目录（输入/输出）
DEFAULT_BACKEND   = r"C:\my-app3\web\backend"
DEFAULT_INP_DIR   = os.path.join(DEFAULT_BACKEND,
                       r"icrp_validation\mcnp_inputs")
DEFAULT_OUT_DIR   = os.path.join(DEFAULT_BACKEND,
                       r"icrp_validation\mcnp_outputs")

# MCNP5 超时（秒）
# AP 光子 10^7 粒子 + FMESH 888K 体素，单 CPU 约 2~6 小时 / 能量点
# 1 MeV 光子产生大量 Compton 级联，粒子数可达 10^8，需约 10-15 小时
WAIT_TIMEOUT   = 12 * 3600   # 12 小时（足以覆盖 1 MeV 慢速情况）
WAIT_INTERVAL  = 30           # 每 30 s 检查一次

# 4 个验证能量点（AM）
ENERGY_CASES = [
    {"energy": 0.010, "inp_name": "ap_photon_E0.010MeV.inp", "mcnp_base": "icrp01"},
    {"energy": 0.100, "inp_name": "ap_photon_E0.100MeV.inp", "mcnp_base": "icrp02"},
    {"energy": 1.000, "inp_name": "ap_photon_E1.000MeV.inp", "mcnp_base": "icrp03"},
    {"energy": 10.00, "inp_name": "ap_photon_E10.000MeV.inp","mcnp_base": "icrp04"},
]

# 4 个验证能量点（AF）— 使用不同 mcnp_base 避免文件名冲突
AF_ENERGY_CASES = [
    {"energy": 0.010, "inp_name": "af_photon_E0.010MeV.inp", "mcnp_base": "icrp05"},
    {"energy": 0.100, "inp_name": "af_photon_E0.100MeV.inp", "mcnp_base": "icrp06"},
    {"energy": 1.000, "inp_name": "af_photon_E1.000MeV.inp", "mcnp_base": "icrp07"},
    {"energy": 10.00, "inp_name": "af_photon_E10.000MeV.inp","mcnp_base": "icrp08"},
]

# ─────────────────────────────────────────────────────────────────


def detect_phot_lib(xsdir_path: str) -> str:
    """
    扫描 MCNP5 xsdir，使用正则表达式匹配真实的光子截面库条目。
    只匹配行首的 ZAID.LLp 格式（避免误匹配注释/路径名中的字符串）。
    优先级: .70p > .12p > .04p > .24p
    """
    import re
    preferred = ['.70p', '.12p', '.04p', '.24p']
    try:
        with open(xsdir_path, 'r', errors='ignore') as f:
            content = f.read()
        found = set(re.findall(r'^\s*\d+\.(\d{2,3})p\s', content, re.MULTILINE))
        for suffix in preferred:
            digits = suffix.lstrip('.').rstrip('p')  # '.04p' -> '04'
            if digits in found:
                return suffix
    except OSError:
        pass
    return None


def log(msg, log_fh=None):
    ts = time.strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        safe = line.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        )
        print(safe, flush=True)
    if log_fh:
        log_fh.write(line + "\n")
        log_fh.flush()


def wait_for_file(path: str, timeout: int, interval: int, log_fh=None) -> bool:
    """等待文件出现，返回是否成功。"""
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(path):
            return True
        elapsed = int(time.time() - start)
        log(f"  等待中 ... {elapsed}s / {timeout}s  ({path})", log_fh)
        time.sleep(interval)
    return False


def run_one(case: dict, args, log_fh, out_dir: str = None):
    """运行单个能量点的完整流程。

    Parameters
    ----------
    case    : dict  — {"energy": float, "inp_name": str, "mcnp_base": str}
    args    : argparse.Namespace
    log_fh  : file handle
    out_dir : str or None — 覆盖 args.out_dir（AF 运行时传入 AF 输出目录）
    """
    energy   = case["energy"]
    inp_name = case["inp_name"]
    base     = case["mcnp_base"]   # 短名：icrp01 … icrp08（无点，MCNP5 兼容）

    if out_dir is None:
        out_dir = args.out_dir

    log(f"━━━ E = {energy:.3f} MeV  [{inp_name}] ━━━", log_fh)

    # 若输出 npy 已存在且非空，跳过重跑（防止页面刷新覆盖已完成的计算）
    npy_check = Path(out_dir) / f"fluence_E{energy:.3f}MeV.npy"
    force_rerun = getattr(args, 'force_rerun', False)
    if npy_check.exists() and npy_check.stat().st_size > 1000:
        if force_rerun:
            npy_check.unlink()
            log(f"  [强制重跑] 已删除旧 {npy_check.name}，将重新运行 MCNP。", log_fh)
        else:
            log(f"  [跳过] {npy_check.name} 已存在 ({npy_check.stat().st_size // 1024} KB)，"
                f"不重新运行 MCNP。如需重跑请勾选「强制重跑」或手动删除该文件。", log_fh)
            return True

    inp_src = Path(args.inp_dir) / inp_name
    if not inp_src.exists():
        log(f"  [错误] 输入文件不存在: {inp_src}", log_fh)
        return False

    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    # ── 1. 清理工作目录旧文件 ──────────────────────────────────────
    for ext in (".o", ".r", ".s", ".p", ".w", ".m", ""):
        old = work / (base + ext)
        if old.exists():
            old.unlink()
            log(f"  删除旧文件: {old.name}", log_fh)
    meshtal = work / "meshtal"
    if meshtal.exists():
        meshtal.unlink()
        log("  删除旧 meshtal", log_fh)

    # ── 2. 复制输入文件 ────────────────────────────────────────────
    dst_inp  = work / f"{base}.inp"
    dst_bare = work / base          # MCNP5 要求无扩展名副本
    shutil.copy(inp_src, dst_inp)
    shutil.copy(inp_src, dst_bare)
    log(f"  复制 → {dst_inp}", log_fh)

    # ── 3. 调用 g5.bat 运行 MCNP5 ─────────────────────────────────
    log(f"  执行: \"{args.g5_bat}\" \"{base}\"  (cwd={work})", log_fh)
    t0 = time.time()
    timed_out = False
    result = None
    try:
        result = subprocess.run(
            [args.g5_bat, base],
            cwd=str(work),
            shell=True,
            capture_output=True,
            text=False,            # 二进制，避免 Windows 编码问题
            timeout=WAIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        timed_out = True
        elapsed = time.time() - t0
        log(f"  [警告] MCNP5 超时 (>{WAIT_TIMEOUT}s, 实际={elapsed:.0f}s)", log_fh)
        log(f"  [警告] 检查 ctme 是否已写出部分结果 ...", log_fh)
    except Exception as e:
        log(f"  [错误] 调用 g5.bat 失败: {e}", log_fh)
        return False

    if result is not None:
        elapsed = time.time() - t0
        log(f"  g5.bat 返回码={result.returncode}  耗时={elapsed:.0f}s", log_fh)

        # 打印 g5.bat 输出（去掉乱码）
        if result.stdout:
            stdout = result.stdout.decode("utf-8", errors="ignore")
            ascii_out = stdout.encode("ascii", errors="ignore").decode("ascii").strip()
            if ascii_out:
                for line in ascii_out.splitlines():
                    log(f"  [MCNP] {line}", log_fh)

        if result.returncode != 0:
            log("  [错误] g5.bat 非零退出，跳过此能量点", log_fh)
            return False

    # ── 4. 确认 .o 文件存在 ───────────────────────────────────────
    # 即使超时，ctme 参数可能已让 MCNP5 优雅退出并写出结果文件
    out_o = work / f"{base}.o"
    if not out_o.exists():
        if timed_out:
            log(f"  [错误] 超时且未找到 {out_o.name}（MCNP 未能写出结果），放弃", log_fh)
        else:
            log(f"  [错误] 未找到 {out_o}", log_fh)
        return False
    if timed_out:
        log(f"  [INFO] 超时后找到 {out_o.name}，提取 ctme 部分结果", log_fh)
    else:
        log(f"  找到输出文件: {out_o}", log_fh)

    # ── 5. 提取 meshtal → npy ─────────────────────────────────────
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    npy_path = out_dir / f"fluence_E{energy:.3f}MeV.npy"

    extract_script = Path(args.backend_dir) / "extract_dose_from_mcnp.py"
    if not extract_script.exists():
        # 尝试同目录
        extract_script = Path(__file__).parent / "extract_dose_from_mcnp.py"

    log(f"  调用提取脚本: {extract_script}", log_fh)
    log(f"  meshtal 目标 npy: {npy_path}", log_fh)

    try:
        ext_result = subprocess.run(
            [sys.executable, str(extract_script), str(out_o), str(npy_path)],
            capture_output=True,
            text=False,
        )
        stdout = ext_result.stdout.decode("utf-8", errors="ignore")
        ascii_out = stdout.encode("ascii", errors="ignore").decode("ascii").strip()
        if ascii_out:
            for line in ascii_out.splitlines():
                log(f"  [extract] {line}", log_fh)
        if ext_result.returncode != 0:
            log("  [警告] 提取脚本返回非零，npy 可能不完整", log_fh)
    except Exception as e:
        log(f"  [警告] 提取脚本出错: {e}", log_fh)

    if npy_path.exists():
        size_kb = npy_path.stat().st_size / 1024
        log(f"  [OK] npy 保存成功: {npy_path}  ({size_kb:.0f} KB)", log_fh)
    else:
        log(f"  [错误] npy 未生成: {npy_path}", log_fh)
        return False

    # F6:P 计分 JSON（提取脚本自动保存，此处仅记录）
    f6_json = out_dir / f"{npy_path.stem}_f6doses.json"
    if f6_json.exists():
        log(f"  [OK] F6 计分保存: {f6_json.name}", log_fh)
    else:
        log(f"  [INFO] 未找到 F6 计分 JSON（可能该运行未包含 F6 tallies）", log_fh)

    # ── 6. 保存 meshtal 副本（带能量标签） ───────────────────────
    if meshtal.exists():
        dst_meshtal = out_dir / f"meshtal_E{energy:.3f}MeV"
        shutil.copy(meshtal, dst_meshtal)
        size_mb = dst_meshtal.stat().st_size / 1e6
        log(f"  [OK] meshtal 备份: {dst_meshtal}  ({size_mb:.1f} MB)", log_fh)

    log(f"  OK E={energy:.3f} MeV 完成\n", log_fh)
    return True


def _try_build_zip(zip_path: Path, am_dir: Path, log_fh) -> bool:
    """
    若 AM.zip 不存在，但 AM/ 目录已有解压文件，则自动打包（ZIP_STORED 无压缩）。
    需要: AM.dat, AM_organs.dat, AM_media.dat
    """
    needed = ["AM.dat", "AM_organs.dat", "AM_media.dat"]
    if not am_dir.is_dir() or not all((am_dir / f).exists() for f in needed):
        return False
    log(f"[准备] 找到 {am_dir}，自动打包为 {zip_path} ...", log_fh)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_STORED) as zf:
        for fname in needed:
            log(f"[准备]   打包: {fname}", log_fh)
            zf.write(str(am_dir / fname), f"AM/{fname}")
    log(f"[准备] OK 已生成 {zip_path}", log_fh)
    return True


def run_subprocess_logged(cmd, cwd, log_fh) -> int:
    """运行子进程并将 stdout/stderr 合并实时记录，返回退出码。"""
    proc = subprocess.Popen(
        cmd, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout:
        log(line.rstrip(), log_fh)
    proc.wait()
    return proc.returncode


def resolve_phot_lib(args, log_fh):
    """
    确定实际使用的光子截面库后缀，并打印说明。
    若无法确认可用库，返回 None（调用方应中止运行）。
    """
    if args.phot_lib:
        log(f"[光子库] 使用指定后缀: {args.phot_lib}", log_fh)
        return args.phot_lib
    detected = detect_phot_lib(args.xsdir)
    if detected:
        log(f"[光子库] 从 xsdir 自动检测到可用库: {detected}  ({args.xsdir})", log_fh)
        return detected
    # 未找到任何光子截面库
    log(f"[致命] 在 xsdir ({args.xsdir}) 中未找到任何光子截面库条目！", log_fh)
    log(f"  xsdir 中未检出 .70p / .12p / .04p / .24p 格式的数据行。", log_fh)
    log(f"  MCNP5 光子输运需要安装光子截面库（如 MCPLIB04）。", log_fh)
    log(f"  请从 RSICC（https://rsicc.ornl.gov）获取 MCPLIB04 数据，", log_fh)
    log(f"  解压到 D:\\LANL\\，并在 xsdir 中添加相应条目后重试。", log_fh)
    return None


def ensure_prerequisites(args, cases, log_fh, phantom: str = 'AM') -> bool:
    """
    检查所需 .inp 文件是否存在；若缺失，自动运行 Step1 和/或 Step2 补全。

    Parameters
    ----------
    phantom : 'AM' 或 'AF'
    返回 True 表示准备就绪，False 表示出错。
    """
    backend  = args.backend_dir
    inp_dir  = Path(args.inp_dir)
    needed   = [c["inp_name"] for c in cases]

    # DE/DF 模式：删除已有 .inp，强制 Step2 以 DE/DF 卡重新生成
    if getattr(args, 'de_df_mode', False):
        for n in needed:
            p = inp_dir / n
            if p.exists():
                p.unlink()
                log(f"[准备-{phantom}] DE/DF 模式：已删除旧输入 {n}，将重新生成", log_fh)

    # 只生成缺失的 .inp 文件，保留已有文件（避免页面刷新时重跑覆盖已有计算）
    missing = [n for n in needed if not (inp_dir / n).exists()]
    if not missing:
        log(f"[准备-{phantom}] 所有 {len(needed)} 个 .inp 文件已存在，跳过重新生成", log_fh)
        return True
    log(f"[准备-{phantom}] 将生成 {len(missing)} 个缺失的 .inp 文件 ...", log_fh)

    if phantom == 'AF':
        zip_path  = Path(backend) / AF_ICRP110_ZIP
        mask_path = Path(backend) / AF_ORGAN_MASK
    else:
        zip_path  = Path(backend) / ICRP110_ZIP
        mask_path = Path(backend) / ORGAN_MASK

    # ── 若 zip 不存在（仅 AM 支持自动打包） ────────────────────────
    if not zip_path.exists():
        if phantom == 'AM':
            am_dir = Path(backend) / "AM"
            if not _try_build_zip(zip_path, am_dir, log_fh):
                log(f"[错误] 找不到 ICRP-110 数据包: {zip_path}", log_fh)
                log(f"  也未找到解压目录: {am_dir}", log_fh)
                log("  请将 AM.zip 放在 backend/P110 data V1.2/ 目录下", log_fh)
                log("  或将 AM.dat / AM_organs.dat / AM_media.dat 放在 backend/AM/ 目录下", log_fh)
                return False
        else:
            log(f"[错误] 找不到 ICRP-110 AF 数据包: {zip_path}", log_fh)
            log("  请将 AF.zip 放在 backend/P110 data V1.2/ 目录下", log_fh)
            return False

    # ── Step 1：生成器官掩膜（仅当掩膜不存在时） ──────────────────
    if not mask_path.exists():
        if not zip_path.exists():
            log(f"[错误] 找不到 ICRP-110 数据包: {zip_path}", log_fh)
            return False

        log(f"[准备-{phantom}] Step1 → 生成器官掩膜: {mask_path}", log_fh)
        step1_cmd = [sys.executable,
                     str(Path(backend) / STEP1_SCRIPT),
                     "--data-zip", str(zip_path),
                     "--out-dir",  str(mask_path.parent),
                     "--phantom",  phantom]
        rc = run_subprocess_logged(step1_cmd, cwd=backend, log_fh=log_fh)
        if rc != 0:
            log(f"[错误] Step1 ({phantom}) 失败 (退出码={rc})", log_fh)
            return False
    else:
        log(f"[准备-{phantom}] 器官掩膜已存在: {mask_path}", log_fh)

    # ── Step 2：生成 .inp 文件 ─────────────────────────────────────
    phot_lib = resolve_phot_lib(args, log_fh)
    if phot_lib is None:
        log("[致命] 无可用光子截面库，无法生成 MCNP 输入文件，终止运行", log_fh)
        return False
    log(f"[准备-{phantom}] Step2 → 生成 .inp 文件到: {inp_dir}  (光子库: {phot_lib})", log_fh)

    # 确定 nps 参数
    nps_arg = str(getattr(args, 'nps', 10_000_000))

    step2_cmd = [sys.executable,
                 str(Path(backend) / STEP2_SCRIPT),
                 "--mask",     str(mask_path),
                 "--zip",      str(zip_path),
                 "--out-dir",  str(inp_dir),
                 "--phot-lib", phot_lib,
                 "--xsdir",    args.xsdir,
                 "--phantom",  phantom,
                 "--nps",      nps_arg]
    if getattr(args, 'de_df_mode', False):
        step2_cmd.append("--de-df-mode")
    rc = run_subprocess_logged(step2_cmd, cwd=backend, log_fh=log_fh)
    if rc != 0:
        log(f"[错误] Step2 ({phantom}) 失败 (退出码={rc})", log_fh)
        return False

    # 最终确认
    still_missing = [n for n in needed if not (inp_dir / n).exists()]
    if still_missing:
        log(f"[错误] Step2 ({phantom}) 完成后仍缺少文件: {still_missing}", log_fh)
        return False

    log(f"[准备-{phantom}] OK 所有 .inp 文件已生成", log_fh)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="ICRP-116 验证：批量运行 MCNP5（4 个 AP 光子能量点）"
    )
    parser.add_argument("--inp-dir",     default=DEFAULT_INP_DIR,
                        help="Step2 生成的 .inp 文件目录")
    parser.add_argument("--out-dir",     default=DEFAULT_OUT_DIR,
                        help="fluence npy 输出目录（AM）")
    parser.add_argument("--g5-bat",      default=DEFAULT_G5_BAT,
                        help="g5.bat 完整路径")
    parser.add_argument("--work-dir",    default=DEFAULT_WORK_DIR,
                        help="MCNP5 工作目录（输入/输出临时目录）")
    parser.add_argument("--backend-dir", default=DEFAULT_BACKEND,
                        help="backend 目录（含 extract_dose_from_mcnp.py）")
    parser.add_argument("--only",        type=float, nargs="+",
                        help="只运行指定能量 MeV，如 --only 0.1 1.0")
    parser.add_argument("--phot-lib",    default=None,
                        help="光子截面库后缀，如 .70p .12p .04p .24p；"
                             "不指定则从 xsdir 自动检测")
    parser.add_argument("--xsdir",       default=DEFAULT_XSDIR,
                        help="MCNP5 xsdir 路径，用于自动检测可用光子库")
    # ── AF 支持 ──────────────────────────────────────────────────
    parser.add_argument("--run-af",      action="store_true", default=True,
                        help="同时运行 AF 体模（默认开启）；用 --no-run-af 关闭")
    parser.add_argument("--no-run-af",   dest="run_af", action="store_false",
                        help="不运行 AF 体模")
    parser.add_argument("--af-out-dir",  default=None,
                        help="AF fluence npy 输出目录（默认: --out-dir 值加 _AF 后缀）")
    parser.add_argument("--nps",         default=10_000_000, type=int,
                        help="MCNP5 源粒子数（传给 Step2，默认 10_000_000）")
    parser.add_argument("--force-rerun", action="store_true", default=False,
                        help="强制重跑：忽略已有 .npy 缓存，重新运行 MCNP5")
    parser.add_argument("--de-df-mode",  action="store_true", default=False,
                        help="DE/DF 模式：生成含 DE/DF 通量转kerma的单 FMESH 输入（消除 EMESH 代表能误差）")
    args = parser.parse_args()

    # 确定 AF 输出目录
    if args.af_out_dir is None:
        args.af_out_dir = args.out_dir.rstrip("/\\") + "_AF"

    # 创建日志文件
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(args.out_dir) / "run_log.txt"

    print(f"━━━ ICRP-116 AP 光子 MCNP5 验证运行 ━━━")
    print(f"  inp-dir    : {args.inp_dir}")
    print(f"  out-dir    : {args.out_dir}")
    print(f"  af-out-dir : {args.af_out_dir}")
    print(f"  run-af     : {args.run_af}")
    print(f"  g5-bat     : {args.g5_bat}")
    print(f"  work-dir   : {args.work_dir}")
    print(f"  nps        : {args.nps:,}")
    print(f"  force-rerun: {args.force_rerun}")
    print(f"  de-df-mode : {args.de_df_mode}")
    print(f"  log        : {log_path}\n")

    # 检查 g5.bat
    if not Path(args.g5_bat).exists():
        print(f"[错误] 找不到 g5.bat: {args.g5_bat}")
        print("  请确认 MCNP5 已安装，并通过 --g5-bat 指定正确路径")
        sys.exit(1)

    am_cases = ENERGY_CASES
    if args.only:
        am_cases = [c for c in ENERGY_CASES if c["energy"] in args.only]
        if not am_cases:
            print(f"[错误] --only 指定的能量 {args.only} 在 ENERGY_CASES 中不存在")
            sys.exit(1)

    af_cases = AF_ENERGY_CASES
    if args.only:
        af_cases = [c for c in AF_ENERGY_CASES if c["energy"] in args.only]

    with open(log_path, "w", encoding="utf-8") as log_fh:
        log(f"开始运行，AM 共 {len(am_cases)} 个能量点", log_fh)

        # ── AM: 确保 .inp 文件存在 ────────────────────────────────────
        if not ensure_prerequisites(args, am_cases, log_fh, phantom='AM'):
            log("[致命] AM 前置步骤失败，验证中止", log_fh)
            sys.exit(1)

        # ── AM: 运行 MCNP5 ───────────────────────────────────────────
        am_results = {}
        for case in am_cases:
            ok = run_one(case, args, log_fh, out_dir=args.out_dir)
            am_results[case["energy"]] = "OK" if ok else "FAILED"

        log("━━━ AM 汇总 ━━━", log_fh)
        for e, status in am_results.items():
            log(f"  E={e:.3f} MeV : {status}", log_fh)

        # ── AF: 确保 .inp 文件存在并运行 ─────────────────────────────
        af_results = {}
        if args.run_af and af_cases:
            log(f"\n[AF] 开始 AF 体模运行，共 {len(af_cases)} 个能量点", log_fh)
            Path(args.af_out_dir).mkdir(parents=True, exist_ok=True)

            if not ensure_prerequisites(args, af_cases, log_fh, phantom='AF'):
                log("[警告] AF 前置步骤失败，跳过 AF 运行", log_fh)
            else:
                for case in af_cases:
                    ok = run_one(case, args, log_fh, out_dir=args.af_out_dir)
                    af_results[case["energy"]] = "OK" if ok else "FAILED"

                log("━━━ AF 汇总 ━━━", log_fh)
                for e, status in af_results.items():
                    log(f"  E={e:.3f} MeV : {status}", log_fh)

        am_failed = [e for e, s in am_results.items() if s != "OK"]
        af_failed = [e for e, s in af_results.items() if s != "OK"]

        if am_failed:
            log(f"[警告] AM: {len(am_failed)} 个能量点失败: {am_failed}", log_fh)
            log("  提示：检查 g5.bat 路径、MCNP5 核数据库、inp 文件格式", log_fh)
        if af_failed:
            log(f"[警告] AF: {len(af_failed)} 个能量点失败: {af_failed}", log_fh)
        if not am_failed and not af_failed:
            log("OK 全部完成！运行第三步脚本进行 ICRP-116 对比分析。", log_fh)

    # 最终打印
    print("\n运行结果汇总:")
    print("  [AM]")
    for e, status in am_results.items():
        print(f"    E={e:.3f} MeV : {status}")
    if af_results:
        print("  [AF]")
        for e, status in af_results.items():
            print(f"    E={e:.3f} MeV : {status}")

    am_failed = [e for e, s in am_results.items() if s != "OK"]
    if not am_failed:
        print(f"\nOK AM fluence npy 文件已保存到 {args.out_dir}")
        if af_results and not [e for e, s in af_results.items() if s != "OK"]:
            print(f"OK AF fluence npy 文件已保存到 {args.af_out_dir}")
        print("  下一步: python mcnp_icrp_step3_compare.py")
        if args.run_af:
            print(f"  (含 AF 平均: --af-out-dir {args.af_out_dir})")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
