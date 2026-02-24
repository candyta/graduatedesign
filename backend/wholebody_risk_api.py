#!/usr/bin/env python3
"""
全身风险评估API封装
用于从Node.js调用Python风险评估功能

使用方式:
python wholebody_risk_api.py --session-dir <session_directory> --icrp-path <icrp_data_path>

Author: BNCT Team
Date: 2026-02-11
"""

import sys
import json
import argparse
from pathlib import Path
import traceback

# 导入核心模块
try:
    from icrp110_phantom_loader import ICRP110Phantom
    from bnct_complete_pipeline import BNCTRiskAssessmentPipeline
except ImportError as e:
    print(f"ERROR: 无法导入必要模块: {e}", file=sys.stderr)
    print("请确保所有Python模块文件在同一目录", file=sys.stderr)
    sys.exit(1)


def update_status(session_dir: Path, step: str, progress: int, message: str):
    """更新评估状态（供前端查询）"""
    status = {
        'step': step,
        'progress': progress,
        'message': message,
        'timestamp': Path(session_dir / 'status.json').stat().st_mtime if (session_dir / 'status.json').exists() else None
    }
    
    with open(session_dir / 'status.json', 'w') as f:
        json.dump(status, f, indent=2)
    
    print(f"[{step}] {progress}% - {message}")


def run_assessment(session_dir: str, icrp_data_path: str):
    """
    运行完整的风险评估流程
    
    Parameters:
    -----------
    session_dir : str
        会话目录路径
    icrp_data_path : str
        ICRP 110数据路径
    """
    session_dir = Path(session_dir)
    
    try:
        # 读取患者信息
        update_status(session_dir, 'loading', 10, '读取患者信息...')
        
        patient_info_path = session_dir / 'patient_info.json'
        if not patient_info_path.exists():
            raise FileNotFoundError(f"患者信息文件不存在: {patient_info_path}")
        
        with open(patient_info_path, 'r') as f:
            patient_data = json.load(f)
        
        # 准备患者参数
        patient_params = {
            'age': patient_data['age'],
            'gender': patient_data['gender'],
            'height': patient_data['height'],
            'weight': patient_data['weight'],
            'tumor_location': patient_data.get('tumor_location', 'brain')
        }
        
        print(f"患者参数: {patient_params}")
        
        # 初始化评估管道
        update_status(session_dir, 'initializing', 20, '初始化评估系统...')
        
        pipeline = BNCTRiskAssessmentPipeline(
            icrp_data_path=icrp_data_path,
            output_dir=str(session_dir)
        )
        
        # CT文件路径（如果提供）
        ct_path = patient_data.get('ct_path')
        tumor_mask_path = patient_data.get('tumor_mask_path')
        
        # 运行评估
        update_status(session_dir, 'assessing', 30, '开始风险评估...')
        
        results = pipeline.run_complete_assessment(
            patient_params=patient_params,
            ct_path=ct_path,
            tumor_mask_path=tumor_mask_path,
            skip_mcnp=True  # 默认使用模拟剂量
        )
        
        update_status(session_dir, 'generating_viz', 80, '生成可视化数据...')
        
        # 生成可视化数据
        viz_data = pipeline.generate_visualization_data()
        
        update_status(session_dir, 'completed', 100, '评估完成！')
        
        # 输出成功信息
        output = {
            'success': True,
            'message': '风险评估完成',
            'total_risk': results['risk_results']['total']['lar_percent'],
            'output_files': {
                'report': str(session_dir / 'risk_assessment_report.txt'),
                'results': str(session_dir / 'complete_results.json'),
                'visualization': str(session_dir / 'visualization_data.json')
            }
        }
        
        # 输出JSON到stdout（供Node.js读取）
        print("\n=== ASSESSMENT_RESULT ===")
        print(json.dumps(output, ensure_ascii=False))
        print("=== END_RESULT ===\n")
        
        return 0
        
    except Exception as e:
        error_msg = f"评估失败: {str(e)}"
        print(f"ERROR: {error_msg}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        
        # 更新失败状态
        update_status(session_dir, 'failed', 0, error_msg)
        
        # 输出错误JSON
        error_output = {
            'success': False,
            'error': error_msg,
            'traceback': traceback.format_exc()
        }
        print("\n=== ASSESSMENT_RESULT ===")
        print(json.dumps(error_output, ensure_ascii=False))
        print("=== END_RESULT ===\n")
        
        return 1


def test_modules():
    """测试所有模块是否可以导入"""
    print("测试模块导入...")
    
    modules_to_test = [
        'icrp110_phantom_loader',
        'phantom_scaling',
        'ct_phantom_fusion',
        'mcnp5_generator',
        'beir7_risk_engine',
        'bnct_complete_pipeline'
    ]
    
    all_ok = True
    for module_name in modules_to_test:
        try:
            __import__(module_name)
            print(f"✓ {module_name}")
        except ImportError as e:
            print(f"✗ {module_name}: {e}")
            all_ok = False
    
    if all_ok:
        print("\n✓ 所有模块导入成功！")
        return 0
    else:
        print("\n✗ 部分模块导入失败")
        return 1


def quick_test(icrp_data_path: str):
    """快速测试评估流程"""
    print("运行快速测试...")
    
    # 创建临时会话目录
    import tempfile
    import time
    
    temp_dir = Path(tempfile.gettempdir()) / f"bnct_test_{int(time.time())}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建测试患者信息
    test_patient = {
        'age': 10,
        'gender': 'female',
        'height': 140,
        'weight': 35,
        'tumor_location': 'brain'
    }
    
    with open(temp_dir / 'patient_info.json', 'w') as f:
        json.dump(test_patient, f)
    
    print(f"测试会话目录: {temp_dir}")
    
    # 运行评估
    result = run_assessment(str(temp_dir), icrp_data_path)
    
    if result == 0:
        print("\n✓ 快速测试成功！")
        print(f"结果已保存到: {temp_dir}")
    else:
        print("\n✗ 快速测试失败")
    
    return result


def main():
    parser = argparse.ArgumentParser(description='BNCT全身风险评估API')
    
    parser.add_argument('--session-dir', type=str,
                       help='会话目录路径（包含patient_info.json）')
    
    parser.add_argument('--icrp-path', type=str,
                       help='ICRP 110数据路径')
    
    parser.add_argument('--test', action='store_true',
                       help='测试模块导入')
    
    parser.add_argument('--quick-test', action='store_true',
                       help='运行快速测试')
    
    args = parser.parse_args()
    
    # 测试模式
    if args.test:
        return test_modules()
    
    # 快速测试模式
    if args.quick_test:
        if not args.icrp_path:
            print("错误: --quick-test 需要提供 --icrp-path", file=sys.stderr)
            return 1
        return quick_test(args.icrp_path)
    
    # 正常评估模式
    if not args.session_dir or not args.icrp_path:
        print("错误: 需要提供 --session-dir 和 --icrp-path", file=sys.stderr)
        parser.print_help()
        return 1
    
    return run_assessment(args.session_dir, args.icrp_path)


if __name__ == '__main__':
    sys.exit(main())
