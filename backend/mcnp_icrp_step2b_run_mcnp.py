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
from pathlib import Path

# ─── 前置步骤脚本 / 数据路径（相对于 backend 目录） ─────────────
STEP1_SCRIPT  = "mcnp_icrp_step1_organ_mask.py"
STEP2_SCRIPT  = "mcnp_icrp_step2_gen_input.py"
ICRP110_ZIP   = os.path.join("P110 data V1.2", "AM.zip")
ORGAN_MASK    = os.path.join("icrp_validation", "organ_mask_127x63x111.npy")

# ─── 默认路径（与现有 run_batch.py / g5.bat 体系一致） ───────────
DEFAULT_G5_BAT    = r"D:\LANL\g5.bat"
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


def log(msg, log_fh=None):
    ts = time.strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
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
    for ext in (".o", ".r", ".s", ".p", ".w", ""):
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

    log(f"  ✓ E={energy:.3f} MeV 完成\n", log_fh)
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


def ensure_prerequisites(args, cases, log_fh) -> bool:
    """
    检查所需 .inp 文件是否存在；若缺失，自动运行 Step1 和/或 Step2 补全。
    返回 True 表示准备就绪，False 表示出错。
    """
    backend  = args.backend_dir
    inp_dir  = Path(args.inp_dir)
    needed   = [c["inp_name"] for c in cases]
    missing  = [n for n in needed if not (inp_dir / n).exists()]

    if not missing:
        log(f"[准备] 所有 {len(needed)} 个 .inp 文件已存在，跳过生成步骤", log_fh)
        return True

    log(f"[准备] 缺少 {len(missing)} 个 .inp 文件: {missing}", log_fh)
    log("[准备] 将自动运行 Step1/Step2 生成输入文件 ...", log_fh)

    zip_path  = Path(backend) / ICRP110_ZIP
    mask_path = Path(backend) / ORGAN_MASK

    # ── Step 1：生成器官掩膜（仅当掩膜不存在时） ──────────────────
    if not mask_path.exists():
        if not zip_path.exists():
            log(f"[错误] 找不到 ICRP-110 数据包: {zip_path}", log_fh)
            log("  请将 AM.zip 放在 backend/P110 data V1.2/ 目录下", log_fh)
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
    if not zip_path.exists():
        log(f"[错误] 找不到 ICRP-110 数据包: {zip_path}", log_fh)
        return False

    log(f"[准备] Step2 → 生成 .inp 文件到: {inp_dir}", log_fh)
    rc = run_subprocess_logged(
        [sys.executable,
         str(Path(backend) / STEP2_SCRIPT),
         "--mask",    str(mask_path),
         "--zip",     str(zip_path),
         "--out-dir", str(inp_dir)],
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

    log("[准备] ✓ 所有 .inp 文件已生成", log_fh)
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
            log("✓ 全部完成！运行第三步脚本进行 ICRP-116 对比分析。", log_fh)

    # 最终打印
    print("\n运行结果汇总:")
    for e, status in results.items():
        print(f"  E={e:.3f} MeV : {status}")

    if not failed:
        print(f"\n✓ 所有 fluence npy 文件已保存到 {args.out_dir}")
        print("  下一步: python mcnp_icrp_step3_compare.py")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
