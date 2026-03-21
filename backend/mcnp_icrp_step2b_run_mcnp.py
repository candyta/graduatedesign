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
ICRP110_ZIP   = os.path.join("P110 data V1.2", "AM.zip")
ORGAN_MASK    = os.path.join("icrp_validation", "organ_mask_127x63x111.npy")

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
WAIT_TIMEOUT   = 8 * 3600   # 8 小时
WAIT_INTERVAL  = 30          # 每 30 s 检查一次

# 4 个验证能量点
ENERGY_CASES = [
    {"energy": 0.010, "inp_name": "ap_photon_E0.010MeV.inp", "mcnp_base": "icrp01"},
    {"energy": 0.100, "inp_name": "ap_photon_E0.100MeV.inp", "mcnp_base": "icrp02"},
    {"energy": 1.000, "inp_name": "ap_photon_E1.000MeV.inp", "mcnp_base": "icrp03"},
    {"energy": 10.00, "inp_name": "ap_photon_E10.000MeV.inp","mcnp_base": "icrp04"},
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


def run_one(case: dict, args, log_fh):
    """运行单个能量点的完整流程。"""
    energy   = case["energy"]
    inp_name = case["inp_name"]
    base     = case["mcnp_base"]   # 短名：icrp01 … icrp04（无点，MCNP5 兼容）

    log(f"━━━ E = {energy:.3f} MeV  [{inp_name}] ━━━", log_fh)

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
        log(f"  [错误] MCNP5 超时 (>{WAIT_TIMEOUT}s)", log_fh)
        return False
    except Exception as e:
        log(f"  [错误] 调用 g5.bat 失败: {e}", log_fh)
        return False

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
    out_o = work / f"{base}.o"
    if not out_o.exists():
        log(f"  [错误] 未找到 {out_o}", log_fh)
        return False
    log(f"  找到输出文件: {out_o}", log_fh)

    # ── 5. 提取 meshtal → npy ─────────────────────────────────────
    out_dir = Path(args.out_dir)
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


def ensure_prerequisites(args, cases, log_fh) -> bool:
    """
    检查所需 .inp 文件是否存在；若缺失，自动运行 Step1 和/或 Step2 补全。
    返回 True 表示准备就绪，False 表示出错。
    """
    backend  = args.backend_dir
    inp_dir  = Path(args.inp_dir)
    needed   = [c["inp_name"] for c in cases]

    # 始终重新生成 .inp 文件，确保使用最新格式（避免旧文件超出 80 列）
    log(f"[准备] 将重新生成 {len(needed)} 个 .inp 文件（强制刷新）", log_fh)
    for n in needed:
        p = inp_dir / n
        if p.exists():
            p.unlink()

    missing  = needed  # 全部视为缺失，触发 Step2
    log("[准备] 将自动运行 Step1/Step2 生成输入文件 ...", log_fh)

    zip_path  = Path(backend) / ICRP110_ZIP
    mask_path = Path(backend) / ORGAN_MASK

    # ── 若 zip 不存在，尝试从 AM/ 目录自动打包 ────────────────────
    if not zip_path.exists():
        am_dir = Path(backend) / "AM"
        if not _try_build_zip(zip_path, am_dir, log_fh):
            log(f"[错误] 找不到 ICRP-110 数据包: {zip_path}", log_fh)
            log(f"  也未找到解压目录: {am_dir}", log_fh)
            log("  请将 AM.zip 放在 backend/P110 data V1.2/ 目录下", log_fh)
            log("  或将 AM.dat / AM_organs.dat / AM_media.dat 放在 backend/AM/ 目录下", log_fh)
            return False

    # ── Step 1：生成器官掩膜（仅当掩膜不存在时） ──────────────────
    if not mask_path.exists():
        if not zip_path.exists():
            log(f"[错误] 找不到 ICRP-110 数据包: {zip_path}", log_fh)
            return False

        log(f"[准备] Step1 → 生成器官掩膜: {mask_path}", log_fh)
        rc = run_subprocess_logged(
            [sys.executable,
             str(Path(backend) / STEP1_SCRIPT),
             "--data-zip", str(zip_path),
             "--out-dir",  str(mask_path.parent)],
            cwd=backend, log_fh=log_fh,
        )
        if rc != 0:
            log(f"[错误] Step1 失败 (退出码={rc})", log_fh)
            return False
    else:
        log(f"[准备] 器官掩膜已存在: {mask_path}", log_fh)

    # ── Step 2：生成 .inp 文件 ─────────────────────────────────────
    phot_lib = resolve_phot_lib(args, log_fh)
    if phot_lib is None:
        log("[致命] 无可用光子截面库，无法生成 MCNP 输入文件，终止运行", log_fh)
        return False
    log(f"[准备] Step2 → 生成 .inp 文件到: {inp_dir}  (光子库: {phot_lib})", log_fh)
    rc = run_subprocess_logged(
        [sys.executable,
         str(Path(backend) / STEP2_SCRIPT),
         "--mask",     str(mask_path),
         "--zip",      str(zip_path),
         "--out-dir",  str(inp_dir),
         "--phot-lib", phot_lib,
         "--xsdir",    args.xsdir],
        cwd=backend, log_fh=log_fh,
    )
    if rc != 0:
        log(f"[错误] Step2 失败 (退出码={rc})", log_fh)
        return False

    # 最终确认
    still_missing = [n for n in needed if not (inp_dir / n).exists()]
    if still_missing:
        log(f"[错误] Step2 完成后仍缺少文件: {still_missing}", log_fh)
        return False

    log("[准备] OK 所有 .inp 文件已生成", log_fh)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="ICRP-116 验证：批量运行 MCNP5（4 个 AP 光子能量点）"
    )
    parser.add_argument("--inp-dir",     default=DEFAULT_INP_DIR,
                        help="Step2 生成的 .inp 文件目录")
    parser.add_argument("--out-dir",     default=DEFAULT_OUT_DIR,
                        help="fluence npy 输出目录")
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
    args = parser.parse_args()

    # 创建日志文件
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(args.out_dir) / "run_log.txt"

    print(f"━━━ ICRP-116 AP 光子 MCNP5 验证运行 ━━━")
    print(f"  inp-dir   : {args.inp_dir}")
    print(f"  out-dir   : {args.out_dir}")
    print(f"  g5-bat    : {args.g5_bat}")
    print(f"  work-dir  : {args.work_dir}")
    print(f"  log       : {log_path}\n")

    # 检查 g5.bat
    if not Path(args.g5_bat).exists():
        print(f"[错误] 找不到 g5.bat: {args.g5_bat}")
        print("  请确认 MCNP5 已安装，并通过 --g5-bat 指定正确路径")
        sys.exit(1)

    cases = ENERGY_CASES
    if args.only:
        cases = [c for c in ENERGY_CASES if c["energy"] in args.only]
        if not cases:
            print(f"[错误] --only 指定的能量 {args.only} 在 ENERGY_CASES 中不存在")
            sys.exit(1)

    with open(log_path, "w", encoding="utf-8") as log_fh:
        log(f"开始运行，共 {len(cases)} 个能量点", log_fh)

        # 确保 .inp 文件存在（必要时自动运行 Step1 + Step2）
        if not ensure_prerequisites(args, cases, log_fh):
            log("[致命] 前置步骤失败，验证中止", log_fh)
            sys.exit(1)

        results = {}
        for case in cases:
            ok = run_one(case, args, log_fh)
            results[case["energy"]] = "OK" if ok else "FAILED"

        log("━━━ 汇总 ━━━", log_fh)
        for e, status in results.items():
            log(f"  E={e:.3f} MeV : {status}", log_fh)

        failed = [e for e, s in results.items() if s != "OK"]
        if failed:
            log(f"[警告] {len(failed)} 个能量点失败: {failed}", log_fh)
            log("  提示：检查 g5.bat 路径、MCNP5 核数据库、inp 文件格式", log_fh)
        else:
            log("OK 全部完成！运行第三步脚本进行 ICRP-116 对比分析。", log_fh)

    # 最终打印
    print("\n运行结果汇总:")
    for e, status in results.items():
        print(f"  E={e:.3f} MeV : {status}")

    if not failed:
        print(f"\nOK 所有 fluence npy 文件已保存到 {args.out_dir}")
        print("  下一步: python mcnp_icrp_step3_compare.py")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
