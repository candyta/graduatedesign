# -*- coding: utf-8 -*-
"""
auto_segment.py
使用 TotalSegmentator 对 CT NIfTI 图像自动勾画器官。

用法:
  python auto_segment.py --ct <input.nii> --outdir <output_dir> [--fast]

stdout: JSON 格式结果
  成功: {"success": true, "organs": [...], "mask_files": [...], "outdir": "..."}
  失败: {"success": false, "error": "...", "install_cmd": "pip install totalsegmentator"}
"""
import sys, os, json, argparse

# ── Windows PATH 修复 ──────────────────────────────────────────────────────────
# torch 启动时会遍历 PATH 并对每个目录调用 os.add_dll_directory()。
# 若 PATH 中存在格式有误的条目（如 "D:bin" 缺少反斜杠）会抛 WinError 87。
# 在此 patch os.add_dll_directory，跳过无效路径，避免 torch 初始化失败。
if sys.platform == 'win32':
    _orig_add_dll = os.add_dll_directory

    def _safe_add_dll(path):
        try:
            return _orig_add_dll(path)
        except OSError:
            pass  # 跳过格式有误的 PATH 条目

    os.add_dll_directory = _safe_add_dll


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ct',    required=True, help='CT NIfTI 文件路径')
    parser.add_argument('--outdir', required=True, help='输出目录')
    parser.add_argument('--fast',  action='store_true', default=True,
                        help='使用快速模式（精度略低但速度快，默认开启）')
    args = parser.parse_args()

    # ── 检查依赖 ──────────────────────────────────────────────
    try:
        from totalsegmentator.python_api import totalsegmentator
    except ImportError:
        result = {
            'success': False,
            'error': 'TotalSegmentator 未安装，请在后端环境运行安装命令。',
            'install_cmd': 'pip install totalsegmentator'
        }
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)

    try:
        import nibabel as nib
    except ImportError:
        result = {
            'success': False,
            'error': 'nibabel 未安装。',
            'install_cmd': 'pip install nibabel'
        }
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)

    # 临床关键器官（用于轮廓显示），按重要性排序
    KEY_ORGANS = [
        'liver', 'spleen', 'kidney_left', 'kidney_right',
        'lung_upper_lobe_left', 'lung_lower_lobe_left',
        'lung_upper_lobe_right', 'lung_lower_lobe_right', 'lung_middle_lobe_right',
        'heart', 'pancreas', 'stomach', 'colon', 'small_bowel',
        'urinary_bladder', 'prostate', 'brain',
        'spinal_cord', 'trachea', 'esophagus',
        'aorta', 'inferior_vena_cava',
        'thyroid_gland', 'gallbladder',
        'adrenal_gland_left', 'adrenal_gland_right',
    ]

    # ── 运行分割 ──────────────────────────────────────────────
    os.makedirs(args.outdir, exist_ok=True)
    try:
        input_img = nib.load(args.ct)
        totalsegmentator(input_img, args.outdir, fast=args.fast, quiet=True)

        # 收集输出 mask 文件（全部）
        all_masks = sorted([
            f for f in os.listdir(args.outdir)
            if f.endswith('.nii') or f.endswith('.nii.gz')
        ])
        all_names = [
            os.path.basename(m).replace('.nii.gz', '').replace('.nii', '')
            for m in all_masks
        ]

        # 优先展示关键器官，其余追加（关键器官放前面保证颜色分配优先）
        name_to_file = {n: os.path.join(args.outdir, m)
                        for n, m in zip(all_names, all_masks)}
        key_present   = [k for k in KEY_ORGANS if k in name_to_file]
        other_present = [n for n in all_names  if n not in KEY_ORGANS]
        ordered_names = key_present + other_present
        ordered_files = [name_to_file[n] for n in ordered_names]

        result = {
            'success': True,
            'outdir': args.outdir,
            'organs':     ordered_names,
            'mask_files': ordered_files,
            'key_organs': key_present,      # 建议默认显示的器官列表
        }
        print(json.dumps(result, ensure_ascii=False))

    except Exception as e:
        result = {'success': False, 'error': str(e)}
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)


if __name__ == '__main__':
    main()
