#!/usr/bin/env python3
"""
BNCT全身风险评估 - 完整处理流程
Complete BNCT Whole-Body Risk Assessment Pipeline

整合所有模块，提供从CT影像到风险报告的端到端处理

Author: BNCT Team
Date: 2026-02-11
"""

import numpy as np
import sys
from pathlib import Path
from typing import Dict, Optional
import json
import time

# 添加路径
sys.path.append(str(Path(__file__).parent))

# 导入所有模块（根据实际路径调整）
try:
    from icrp110_phantom_loader import ICRP110Phantom
    from phantom_scaling import PhantomScaler
    
    # 优先使用简化版CT融合（不需要nibabel）
    try:
        from ct_phantom_fusion_simple import CTPhantomFusion
        print("使用简化版CT融合（无nibabel依赖）", file=sys.stderr)
    except ImportError:
        from ct_phantom_fusion import CTPhantomFusion
        print("使用完整版CT融合", file=sys.stderr)
    
    from mcnp5_generator import MCNP5InputGenerator
    from beir7_risk_engine import BEIRVII_RiskEngine
except ImportError as e:
    print(f"错误: 模块导入失败 - {e}", file=sys.stderr)
    print("请确保所有模块文件在同一目录", file=sys.stderr)
    sys.exit(1)  # 导入失败直接退出


class BNCTRiskAssessmentPipeline:
    """
    BNCT全身风险评估完整流程
    
    流程步骤:
    1. 加载ICRP 110标准体模
    2. 根据患者参数缩放体模
    3. 融合患者CT影像
    4. 生成MCNP5输入文件
    5. 执行蒙特卡罗计算（外部调用）
    6. 解析剂量结果
    7. 计算二次癌风险
    8. 生成可视化报告
    """
    
    def __init__(self, 
                 icrp_data_path: str,
                 output_dir: str = "./output"):
        """
        初始化处理流程
        
        Parameters:
        -----------
        icrp_data_path : str
            ICRP 110数据路径，例如 "C:/my-app3/web/P110 data V1.2"
        output_dir : str
            输出目录
        """
        self.icrp_data_path = Path(icrp_data_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 处理状态
        self.phantom = None
        self.scaled_phantom = None
        self.fused_phantom = None
        self.organ_doses = None
        self.risk_results = None
        
        print("="*70)
        print("BNCT全身风险评估系统初始化")
        print("="*70)
        print(f"ICRP数据路径: {self.icrp_data_path}")
        print(f"输出目录: {self.output_dir}")
        
    def run_complete_assessment(self,
                               patient_params: Dict,
                               ct_path: Optional[str] = None,
                               tumor_mask_path: Optional[str] = None,
                               skip_mcnp: bool = True) -> Dict:
        """
        运行完整的风险评估流程
        
        Parameters:
        -----------
        patient_params : dict
            患者参数字典:
            {
                'age': int,
                'gender': 'male' or 'female',
                'height': float (cm),
                'weight': float (kg),
                'tumor_location': str (e.g., 'brain', 'lung')
            }
        ct_path : str, optional
            患者CT文件路径（NIfTI格式）
        tumor_mask_path : str, optional
            肿瘤掩膜路径
        skip_mcnp : bool
            是否跳过MCNP计算（用于测试）
            
        Returns:
        --------
        dict
            完整的评估结果
        """
        print("\n" + "="*70)
        print("开始完整风险评估流程")
        print("="*70)
        
        start_time = time.time()
        
        # 提取患者参数
        age = patient_params['age']
        gender = patient_params['gender']
        height = patient_params['height']
        weight = patient_params['weight']
        tumor_location = patient_params.get('tumor_location', 'brain')
        
        print(f"\n患者信息:")
        print(f"  年龄: {age} 岁")
        print(f"  性别: {gender}")
        print(f"  身高: {height} cm")
        print(f"  体重: {weight} kg")
        print(f"  肿瘤部位: {tumor_location}")
        
        results = {
            'patient_params': patient_params,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'steps_completed': []
        }
        
        # ===== Step 1: 加载标准体模 =====
        print("\n" + "-"*70)
        print("Step 1/6: 加载ICRP 110标准体模")
        print("-"*70)
        
        phantom_type = 'AM' if gender.lower() == 'male' else 'AF'
        self.phantom = ICRP110Phantom(str(self.icrp_data_path), phantom_type)
        self.phantom.load_all()
        
        results['steps_completed'].append('load_phantom')
        results['phantom_type'] = phantom_type
        results['phantom_dimensions'] = self.phantom.dims
        
        # ===== Step 2: 体模缩放 =====
        print("\n" + "-"*70)
        print("Step 2/6: 根据患者参数缩放体模")
        print("-"*70)
        
        scaler = PhantomScaler(phantom_type)
        scaling_factors = scaler.calculate_scaling_factors(height, weight)
        
        scaled_voxels, scale_params = scaler.scale_voxel_phantom(
            self.phantom.voxel_data,
            scaling_factors
        )
        
        self.scaled_phantom = scaled_voxels
        
        results['steps_completed'].append('scale_phantom')
        results['scaling_factors'] = scaling_factors
        results['scaled_dimensions'] = scale_params['dimensions']
        
        # 保存缩放体模
        scaled_phantom_path = self.output_dir / f"scaled_phantom_{phantom_type}.npy"
        np.save(scaled_phantom_path, scaled_voxels)
        print(f"\n✓ 缩放体模已保存: {scaled_phantom_path}")
        
        # ===== Step 3: CT融合（如果提供了CT） =====
        print("\n" + "-"*70)
        print("Step 3/6: CT影像与体模融合")
        print("-"*70)
        
        # 获取原始体素尺寸（在if外面定义，以便后续使用）
        orig_voxel_size = self.phantom.dims['voxel_size']
        
        if ct_path and Path(ct_path).exists():
            fusion = CTPhantomFusion()
            fusion.load_ct_image(ct_path)
            
            if tumor_mask_path and Path(tumor_mask_path).exists():
                fusion.load_tumor_mask(tumor_mask_path)
            
            # 计算新的体素尺寸
            new_voxel_size = (
                orig_voxel_size[0] * scaling_factors['x'],
                orig_voxel_size[1] * scaling_factors['y'],
                orig_voxel_size[2] * scaling_factors['z']
            )
            
            registration = fusion.register_ct_to_phantom(
                scaled_voxels,
                new_voxel_size,
                tumor_location
            )
            
            fused_voxels = fusion.fuse_ct_into_phantom(registration)
            self.fused_phantom = fused_voxels
            
            results['steps_completed'].append('ct_fusion')
            results['registration'] = registration
            
            # 保存融合体模
            fused_phantom_path = self.output_dir / f"fused_phantom_{phantom_type}.npy"
            np.save(fused_phantom_path, fused_voxels)
            print(f"\n✓ 融合体模已保存: {fused_phantom_path}")
            
            final_phantom = fused_voxels
        else:
            print("未提供CT影像，使用缩放后的标准体模")
            final_phantom = scaled_voxels
            results['steps_completed'].append('no_ct_fusion')
        
        # ===== Step 4: 生成MCNP5输入文件 =====
        print("\n" + "-"*70)
        print("Step 4/6: 生成MCNP5输入文件")
        print("-"*70)
        
        # 计算最终的体素尺寸
        final_voxel_size = (
            orig_voxel_size[0] * scaling_factors['x'],
            orig_voxel_size[1] * scaling_factors['y'],
            orig_voxel_size[2] * scaling_factors['z']
        )
        
        generator = MCNP5InputGenerator(
            final_phantom,
            final_voxel_size,
            self.phantom.organs
        )
        
        # 生成几何（使用简化的RPP方法）
        generator.generate_voxel_geometry(lattice_method='rpp')
        
        # 生成材料
        generator.generate_materials(self.phantom.media)
        
        # 生成中子源
        generator.generate_source(source_type='epithermal_neutron')
        
        # 生成计分卡
        generator.generate_tallies()
        
        # 写入文件
        mcnp_input_path = self.output_dir / "bnct_whole_body.inp"
        generator.write_input_file(str(mcnp_input_path))
        
        results['steps_completed'].append('generate_mcnp')
        results['mcnp_input_file'] = str(mcnp_input_path)
        
        # ===== Step 5: MCNP5计算 =====
        print("\n" + "-"*70)
        print("Step 5/6: MCNP5蒙特卡罗计算")
        print("-"*70)
        
        if skip_mcnp:
            print("⚠ 跳过MCNP计算（测试模式）")
            print("使用模拟剂量数据...")
            
            # 生成模拟的器官剂量数据
            self.organ_doses = self._generate_mock_organ_doses(
                tumor_location, 
                age
            )
            
            results['steps_completed'].append('mcnp_skipped')
        else:
            print("提示: 需要在外部运行MCNP5")
            print(f"命令: mcnp5 i={mcnp_input_path}")
            print("计算完成后，请使用 parse_mcnp_output() 解析结果")
            
            results['steps_completed'].append('mcnp_ready')
            # 这里需要实际调用MCNP或等待用户运行
            return results
        
        # ===== Step 6: 风险评估 =====
        print("\n" + "-"*70)
        print("Step 6/6: 二次癌风险评估")
        print("-"*70)
        
        risk_engine = BEIRVII_RiskEngine(age, gender)
        
        self.risk_results = risk_engine.assess_all_organs(
            self.organ_doses,
            life_expectancy=85
        )
        
        # 生成报告
        report_path = self.output_dir / "risk_assessment_report.txt"
        risk_engine.generate_risk_report(self.risk_results, str(report_path))
        
        results['steps_completed'].append('risk_assessment')
        results['risk_results'] = self.risk_results
        results['report_file'] = str(report_path)
        
        # ===== 完成 =====
        elapsed_time = time.time() - start_time
        
        print("\n" + "="*70)
        print("✓ 完整风险评估流程完成！")
        print("="*70)
        print(f"总耗时: {elapsed_time:.2f} 秒")
        print(f"\n输出文件:")
        print(f"  - 缩放体模: {scaled_phantom_path}")
        if ct_path:
            print(f"  - 融合体模: {fused_phantom_path}")
        print(f"  - MCNP输入: {mcnp_input_path}")
        print(f"  - 风险报告: {report_path}")
        print(f"  - JSON结果: {report_path.with_suffix('.json')}")
        
        results['total_time_seconds'] = elapsed_time
        
        # 保存完整结果
        results_path = self.output_dir / "complete_results.json"
        with open(results_path, 'w', encoding='utf-8') as f:
            # 转换numpy类型为Python原生类型
            results_serializable = self._make_json_serializable(results)
            json.dump(results_serializable, f, indent=2, ensure_ascii=False)
        
        print(f"  - 完整结果: {results_path}")
        
        return results
    
    def _generate_mock_organ_doses(self, tumor_location: str, age: int) -> Dict[str, float]:
        """
        生成模拟的器官剂量数据（用于测试）
        
        基于论文中的典型剂量分布
        """
        print("\n生成模拟器官剂量...")
        
        # 基础剂量（Sv）- 根据肿瘤位置调整
        base_doses = {
            'brain': {
                'Brain': 0.25,
                'Thyroid': 0.15,
                'Esophagus': 0.12,
                'Lung, left': 0.08,
                'Lung, right': 0.09,
                'Liver': 0.03,
                'Stomach wall': 0.05,
                'Colon': 0.04,
                'Bone marrow, head': 0.02,
                'Bone marrow, trunk': 0.015,
                'Skin, head': 0.18
            },
            'lung': {
                'Lung, left': 0.35,
                'Lung, right': 0.32,
                'Heart wall': 0.25,
                'Esophagus': 0.28,
                'Liver': 0.15,
                'Stomach wall': 0.12,
                'Thyroid': 0.10,
                'Brain': 0.05,
                'Colon': 0.08,
                'Bone marrow, trunk': 0.06,
                'Skin, trunk': 0.22
            },
            'liver': {
                'Liver': 0.40,
                'Stomach wall': 0.25,
                'Colon': 0.18,
                'Lung, left': 0.12,
                'Lung, right': 0.13,
                'Pancreas': 0.15,
                'Kidneys': 0.10,
                'Esophagus': 0.08,
                'Brain': 0.03,
                'Bone marrow, trunk': 0.08,
                'Skin, trunk': 0.20
            }
        }
        
        doses = base_doses.get(tumor_location, base_doses['brain'])
        
        # 年龄调整（年轻患者剂量稍高，因为治疗可能更激进）
        if age < 15:
            age_factor = 1.2
        elif age < 30:
            age_factor = 1.1
        else:
            age_factor = 1.0
        
        adjusted_doses = {k: v * age_factor for k, v in doses.items()}
        
        print(f"✓ 生成了 {len(adjusted_doses)} 个器官的剂量数据")
        
        return adjusted_doses
    
    def _make_json_serializable(self, obj):
        """将numpy类型转换为JSON可序列化类型"""
        if isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._make_json_serializable(item) for item in obj]
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return obj
    
    def generate_visualization_data(self) -> Dict:
        """
        生成用于前端可视化的数据
        
        Returns:
        --------
        dict
            可视化数据（JSON格式）
        """
        if self.risk_results is None:
            raise ValueError("请先运行风险评估")
        
        print("\n生成可视化数据...")
        
        viz_data = {
            'organ_risk_ranking': [],
            'dose_distribution': [],
            'risk_by_age': [],
            'total_risk': self.risk_results['total']['lar_percent']
        }
        
        # 器官风险排行
        for site, data in sorted(
            [(k, v) for k, v in self.risk_results.items() if k != 'total'],
            key=lambda x: x[1].get('lar_percent', 0),
            reverse=True
        ):
            viz_data['organ_risk_ranking'].append({
                'organ': site,
                'risk_percent': data.get('lar_percent', 0),
                'dose_sv': data.get('dose_sv', 0),
                'err': data.get('err', 0)
            })
        
        # 保存可视化数据
        viz_path = self.output_dir / "visualization_data.json"
        with open(viz_path, 'w', encoding='utf-8') as f:
            json.dump(viz_data, f, indent=2, ensure_ascii=False)
        
        print(f"✓ 可视化数据已保存: {viz_path}")
        
        return viz_data


def main():
    """主函数 - 示例用法"""
    print("="*70)
    print("BNCT全身风险评估系统 - 完整示例")
    print("="*70)
    
    # 初始化系统
    pipeline = BNCTRiskAssessmentPipeline(
        icrp_data_path="C:/my-app3/web/P110 data V1.2",
        output_dir="./bnct_output"
    )
    
    # 患者参数
    patient_params = {
        'age': 10,
        'gender': 'female',
        'height': 140,
        'weight': 35,
        'tumor_location': 'brain'
    }
    
    # 运行完整评估（测试模式 - 跳过MCNP）
    results = pipeline.run_complete_assessment(
        patient_params=patient_params,
        ct_path=None,  # 如果有CT文件，提供路径
        tumor_mask_path=None,
        skip_mcnp=True  # 测试模式
    )
    
    # 生成可视化数据
    viz_data = pipeline.generate_visualization_data()
    
    # 显示关键结果
    print("\n" + "="*70)
    print("关键评估结果")
    print("="*70)
    print(f"\n总体二次癌风险: {results['risk_results']['total']['lar_percent']:.4f}%")
    print("\n高风险器官（Top 5）:")
    for i, item in enumerate(viz_data['organ_risk_ranking'][:5], 1):
        print(f"  {i}. {item['organ']}: {item['risk_percent']:.6f}% "
              f"(剂量: {item['dose_sv']:.4f} Sv)")
    
    print("\n" + "="*70)
    print("✓ 示例运行完成！")
    print("="*70)


if __name__ == "__main__":
    main()
