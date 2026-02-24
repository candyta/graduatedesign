#!/usr/bin/env python3
"""
测试所有模块是否能正确导入
"""

import sys
from pathlib import Path

# 添加backend目录到路径
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

print("="*60)
print("测试模块导入")
print("="*60)

modules = [
    'icrp110_phantom_loader',
    'phantom_scaling',
    'ct_phantom_fusion',
    'mcnp5_generator',
    'beir7_risk_engine',
    'bnct_complete_pipeline'
]

success = []
failed = []

for module_name in modules:
    try:
        module = __import__(module_name)
        print(f"✓ {module_name}")
        success.append(module_name)
    except ImportError as e:
        print(f"✗ {module_name}: {e}")
        failed.append((module_name, str(e)))
    except Exception as e:
        print(f"✗ {module_name}: {type(e).__name__}: {e}")
        failed.append((module_name, str(e)))

print("\n" + "="*60)
print(f"成功: {len(success)}/{len(modules)}")
print(f"失败: {len(failed)}/{len(modules)}")

if failed:
    print("\n失败详情:")
    for name, error in failed:
        print(f"  {name}: {error}")
    sys.exit(1)
else:
    print("\n✓ 所有模块导入成功！")
    sys.exit(0)
