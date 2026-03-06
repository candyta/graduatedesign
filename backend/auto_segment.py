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

    # ── 运行分割 ──────────────────────────────────────────────
    os.makedirs(args.outdir, exist_ok=True)
    try:
        input_img = nib.load(args.ct)
        totalsegmentator(input_img, args.outdir, fast=args.fast, quiet=True)

        # 收集输出 mask 文件
        masks = sorted([
            f for f in os.listdir(args.outdir)
            if f.endswith('.nii') or f.endswith('.nii.gz')
        ])
        organ_names = [
            os.path.basename(m).replace('.nii.gz', '').replace('.nii', '')
            for m in masks
        ]
        mask_full_paths = [os.path.join(args.outdir, m) for m in masks]

        result = {
            'success': True,
            'outdir': args.outdir,
            'organs': organ_names,
            'mask_files': mask_full_paths
        }
        print(json.dumps(result, ensure_ascii=False))

    except Exception as e:
        result = {'success': False, 'error': str(e)}
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)


if __name__ == '__main__':
    main()
