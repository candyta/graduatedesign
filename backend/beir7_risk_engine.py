#!/usr/bin/env python3
"""
BEIR VII 二次癌风险评估引擎
BEIR VII Secondary Cancer Risk Assessment Engine

基于BEIR VII报告的终生归因风险（LAR）模型
计算BNCT治疗后各器官的二次癌症风险

参考：
- BEIR VII Report (2006)
- ICRP Publication 103
- 张欣欣硕士论文第三、四章

Author: BNCT Team
Date: 2026-02-11
"""

import numpy as np
from typing import Dict, Tuple, Optional
import json
from pathlib import Path


class BEIRVII_RiskEngine:
    """
    BEIR VII 风险评估引擎
    
    功能：
    1. 计算器官剂量当量
    2. 应用ERR/EAR模型
    3. 计算终生归因风险（LAR）
    4. 考虑年龄、性别调整
    """
    
    # ERR (Excess Relative Risk) 模型参数
    # 来源：BEIR VII Table 12-2D and 12-2E
    ERR_PARAMETERS = {
        'stomach': {
            'male': {'beta': 0.21, 'gamma': -0.30, 'eta': 5.0},
            'female': {'beta': 0.48, 'gamma': -0.41, 'eta': 5.0}
        },
        'colon': {
            'male': {'beta': 0.63, 'gamma': -0.41, 'eta': 2.8},
            'female': {'beta': 0.43, 'gamma': -0.41, 'eta': 2.8}
        },
        'liver': {
            'male': {'beta': 0.32, 'gamma': -0.30, 'eta': 5.0},
            'female': {'beta': 0.32, 'gamma': -0.30, 'eta': 5.0}
        },
        'lung': {
            'male': {'beta': 0.32, 'gamma': -0.40, 'eta': 5.7},
            'female': {'beta': 1.40, 'gamma': -0.40, 'eta': 5.7}
        },
        'breast': {
            'female': {'beta': 0.51, 'gamma': -0.51, 'eta': 0.0}
        },
        'ovary': {
            'female': {'beta': 0.38, 'gamma': -0.22, 'eta': 10.0}
        },
        'bladder': {
            'male': {'beta': 0.50, 'gamma': -0.50, 'eta': 4.0},
            'female': {'beta': 1.20, 'gamma': -0.50, 'eta': 4.0}
        },
        'thyroid': {
            'male': {'beta': 0.53, 'gamma': -1.50, 'eta': 0.0},
            'female': {'beta': 1.05, 'gamma': -0.72, 'eta': 0.0}
        },
        'brain': {
            'male': {'beta': 0.24, 'gamma': -0.30, 'eta': 15.0},
            'female': {'beta': 0.24, 'gamma': -0.30, 'eta': 15.0}
        },
        'leukemia': {
            'male': {'beta': 1.50, 'gamma': -0.32, 'eta': 0.0},
            'female': {'beta': 2.20, 'gamma': -0.24, 'eta': 0.0}
        }
    }
    
    # EAR (Excess Absolute Risk) 模型参数
    # 来源：BEIR VII Table 12-2D and 12-2E
    EAR_PARAMETERS = {
        'stomach': {
            'male': {'beta': 4.90, 'gamma': -0.41, 'eta': 5.0},
            'female': {'beta': 10.20, 'gamma': -0.41, 'eta': 5.0}
        },
        'colon': {
            'male': {'beta': 3.20, 'gamma': -0.41, 'eta': 2.8},
            'female': {'beta': 1.60, 'gamma': -0.41, 'eta': 2.8}
        },
        'liver': {
            'male': {'beta': 2.70, 'gamma': -0.30, 'eta': 5.0},
            'female': {'beta': 2.20, 'gamma': -0.30, 'eta': 5.0}
        },
        'lung': {
            'male': {'beta': 5.50, 'gamma': -0.40, 'eta': 5.7},
            'female': {'beta': 9.60, 'gamma': -0.40, 'eta': 5.7}
        },
        'breast': {
            'female': {'beta': 10.80, 'gamma': -0.51, 'eta': 0.0}
        },
        'ovary': {
            'female': {'beta': 1.20, 'gamma': -0.22, 'eta': 10.0}
        },
        'bladder': {
            'male': {'beta': 1.00, 'gamma': -0.50, 'eta': 4.0},
            'female': {'beta': 1.60, 'gamma': -0.50, 'eta': 4.0}
        },
        'thyroid': {
            'male': {'beta': 0.40, 'gamma': -1.50, 'eta': 0.0},
            'female': {'beta': 2.00, 'gamma': -0.72, 'eta': 0.0}
        }
    }
    
    # 基线癌症发病率（中国数据，每10万人年）
    # 来源：中国肿瘤登记年报
    BASELINE_INCIDENCE = {
        'stomach': {'male': 41.4, 'female': 19.2},
        'colon': {'male': 28.6, 'female': 22.1},
        'liver': {'male': 38.8, 'female': 14.3},
        'lung': {'male': 60.2, 'female': 28.5},
        'breast': {'female': 42.6},
        'ovary': {'female': 7.8},
        'bladder': {'male': 9.8, 'female': 3.5},
        'thyroid': {'male': 3.2, 'female': 11.4},
        'esophagus': {'male': 22.1, 'female': 10.2},
        'pancreas': {'male': 10.8, 'female': 8.3},
        'kidney': {'male': 9.5, 'female': 5.2},
        'brain': {'male': 5.2, 'female': 3.8},
        'leukemia': {'male': 5.8, 'female': 4.2}
    }
    
    # 潜伏期（年）
    LATENCY_PERIOD = {
        'solid_cancer': 5,
        'leukemia': 2
    }
    
    # DDREF (Dose and Dose-Rate Effectiveness Factor)
    DDREF = 1.5  # 用于低剂量（< 100 mGy）
    
    def __init__(self, patient_age: int, patient_gender: str):
        """
        初始化风险评估引擎
        
        Parameters:
        -----------
        patient_age : int
            患者照射时的年龄
        patient_gender : str
            患者性别 ('male' or 'female')
        """
        self.patient_age = patient_age
        self.patient_gender = patient_gender.lower()
        
        if self.patient_gender not in ['male', 'female']:
            raise ValueError("Gender must be 'male' or 'female'")
        
        print(f"初始化BEIR VII风险评估引擎")
        print(f"患者年龄: {patient_age} 岁")
        print(f"患者性别: {patient_gender}")
    
    def calculate_err(self,
                     organ: str,
                     dose_sv: float,
                     age_at_exposure: int) -> float:
        """
        计算超额相对风险（ERR）
        
        ERR(D, e) = β × D × exp(γ × (e-30)/10)
        
        其中：
        D = 剂量（Sv）
        e = 照射时年龄
        
        Parameters:
        -----------
        organ : str
            器官名称
        dose_sv : float
            器官剂量当量（Sv）
        age_at_exposure : int
            照射时年龄
            
        Returns:
        --------
        float
            ERR值
        """
        if organ not in self.ERR_PARAMETERS:
            return 0.0
        
        gender_params = self.ERR_PARAMETERS[organ].get(self.patient_gender)
        if gender_params is None:
            return 0.0
        
        beta = gender_params['beta']
        gamma = gender_params['gamma']
        eta = gender_params['eta']
        
        # 应用DDREF（如果剂量 < 0.1 Sv）
        if dose_sv < 0.1:
            dose_sv = dose_sv / self.DDREF
        
        # 年龄调整
        age_factor = np.exp(gamma * (age_at_exposure - 30) / 10)
        
        # 计算ERR
        err = beta * dose_sv * age_factor
        
        return err
    
    def calculate_ear(self,
                     organ: str,
                     dose_sv: float,
                     age_at_exposure: int,
                     attained_age: int) -> float:
        """
        计算超额绝对风险（EAR）
        
        EAR(D, e, a) = β × D × exp(γ × (e-30)/10) × ((a/60)^η)
        
        其中：
        D = 剂量（Sv）
        e = 照射时年龄
        a = 达到年龄
        
        Parameters:
        -----------
        organ : str
            器官名称
        dose_sv : float
            器官剂量当量（Sv）
        age_at_exposure : int
            照射时年龄
        attained_age : int
            达到年龄
            
        Returns:
        --------
        float
            EAR值（每10,000人年）
        """
        if organ not in self.EAR_PARAMETERS:
            return 0.0
        
        gender_params = self.EAR_PARAMETERS[organ].get(self.patient_gender)
        if gender_params is None:
            return 0.0
        
        beta = gender_params['beta']
        gamma = gender_params['gamma']
        eta = gender_params['eta']
        
        # 应用DDREF
        if dose_sv < 0.1:
            dose_sv = dose_sv / self.DDREF
        
        # 年龄调整因子
        age_at_exp_factor = np.exp(gamma * (age_at_exposure - 30) / 10)
        attained_age_factor = (attained_age / 60) ** eta
        
        # 计算EAR（每10,000人年）
        ear = beta * dose_sv * age_at_exp_factor * attained_age_factor
        
        return ear
    
    def calculate_lar(self,
                     organ: str,
                     dose_sv: float,
                     survival_function: Optional[callable] = None,
                     life_expectancy: int = 85) -> float:
        """
        计算终生归因风险（LAR）
        
        LAR = ∫[e+L to L] ERR(D,e) × λ₀(a) × S(a|e) da
        
        或
        
        LAR = ∫[e+L to L] EAR(D,e,a) × S(a|e) da / 10,000
        
        其中：
        e = 照射时年龄
        L = 终生（通常85岁）
        L = 潜伏期
        λ₀(a) = 基线发病率
        S(a|e) = 从年龄e生存到年龄a的概率
        
        Parameters:
        -----------
        organ : str
            器官名称
        dose_sv : float
            器官剂量当量（Sv）
        survival_function : callable, optional
            生存函数 S(age)
        life_expectancy : int
            预期寿命
            
        Returns:
        --------
        float
            LAR（百分比）
        """
        # 确定潜伏期
        if organ == 'leukemia':
            latency = self.LATENCY_PERIOD['leukemia']
        else:
            latency = self.LATENCY_PERIOD['solid_cancer']
        
        # 积分起始和终止年龄
        start_age = self.patient_age + latency
        end_age = life_expectancy
        
        if start_age >= end_age:
            return 0.0
        
        # 如果没有提供生存函数，使用简化模型
        if survival_function is None:
            # 简化：假设恒定的年死亡率
            annual_mortality = 0.01  # 1%每年
            def survival_function(age):
                return np.exp(-annual_mortality * (age - self.patient_age))
        
        # 获取基线发病率
        baseline = self.BASELINE_INCIDENCE.get(organ, {}).get(self.patient_gender, 0)
        baseline_rate = baseline / 100000  # 转换为比率
        
        # 数值积分（简化为求和）
        lar = 0.0
        
        # 使用ERR模型
        for age in range(start_age, end_age + 1):
            err = self.calculate_err(organ, dose_sv, self.patient_age)
            
            # ERR贡献
            risk_at_age = err * baseline_rate * survival_function(age)
            
            lar += risk_at_age
        
        # 转换为百分比
        lar_percent = lar * 100
        
        return lar_percent
    
    def assess_all_organs(self,
                         organ_doses: Dict[str, float],
                         life_expectancy: int = 85) -> Dict[str, Dict]:
        """
        评估所有器官的二次癌风险
        
        Parameters:
        -----------
        organ_doses : dict
            器官剂量字典 {organ_name: dose_sv}
        life_expectancy : int
            预期寿命
            
        Returns:
        --------
        dict
            风险评估结果
        """
        print(f"\n评估全身器官二次癌风险...")
        print(f"患者年龄: {self.patient_age} 岁, 性别: {self.patient_gender}")
        print(f"预期寿命: {life_expectancy} 岁")
        
        results = {}
        total_risk = 0.0
        
        # 器官名称映射（简化版）
        organ_mapping = {
            'stomach': ['stomach'],
            'colon': ['colon', 'ascending', 'descending', 'transverse', 'sigmoid', 'rectum'],
            'liver': ['liver'],
            'lung': ['lung'],
            'breast': ['breast'],
            'ovary': ['ovary'],
            'bladder': ['bladder'],
            'thyroid': ['thyroid'],
            'esophagus': ['esophagus'],
            'pancreas': ['pancreas'],
            'kidney': ['kidney'],
            'brain': ['brain'],
            'leukemia': ['bone', 'marrow']
        }
        
        for cancer_site, organ_keywords in organ_mapping.items():
            # 找到匹配的器官
            site_dose = 0.0
            matched_organs = []
            
            for organ_name, dose in organ_doses.items():
                organ_lower = organ_name.lower()
                if any(keyword in organ_lower for keyword in organ_keywords):
                    site_dose += dose
                    matched_organs.append(organ_name)
            
            if site_dose > 0 and len(matched_organs) > 0:
                # 平均剂量
                avg_dose = site_dose / len(matched_organs)
                
                # 计算LAR
                lar = self.calculate_lar(
                    cancer_site,
                    avg_dose,
                    life_expectancy=life_expectancy
                )
                
                if lar > 0:
                    results[cancer_site] = {
                        'organs': matched_organs,
                        'dose_sv': avg_dose,
                        'lar_percent': lar,
                        'err': self.calculate_err(cancer_site, avg_dose, self.patient_age)
                    }
                    
                    total_risk += lar
        
        # 添加总风险
        results['total'] = {
            'lar_percent': total_risk,
            'description': '全身累积二次癌风险'
        }
        
        print(f"\n✓ 风险评估完成")
        print(f"  评估器官/部位: {len(results) - 1}")
        print(f"  总体风险: {total_risk:.4f}%")
        
        return results
    
    def generate_risk_report(self,
                           risk_results: Dict,
                           output_path: str):
        """
        生成风险评估报告
        
        Parameters:
        -----------
        risk_results : dict
            风险评估结果
        output_path : str
            输出文件路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"\n生成风险评估报告: {output_path}")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("="*60 + "\n")
            f.write("BNCT 二次癌症风险评估报告\n")
            f.write("基于 BEIR VII 模型\n")
            f.write("="*60 + "\n\n")
            
            f.write(f"患者信息:\n")
            f.write(f"  年龄: {self.patient_age} 岁\n")
            f.write(f"  性别: {self.patient_gender}\n\n")
            
            f.write("="*60 + "\n")
            f.write("器官风险评估结果\n")
            f.write("="*60 + "\n\n")
            
            # 按风险从高到低排序
            sorted_results = sorted(
                [(k, v) for k, v in risk_results.items() if k != 'total'],
                key=lambda x: x[1].get('lar_percent', 0),
                reverse=True
            )
            
            f.write(f"{'部位':<15} {'剂量(Sv)':<12} {'LAR(%)':<12} {'ERR':<10}\n")
            f.write("-"*60 + "\n")
            
            for site, data in sorted_results:
                dose = data.get('dose_sv', 0)
                lar = data.get('lar_percent', 0)
                err = data.get('err', 0)
                
                f.write(f"{site:<15} {dose:>10.4f}  {lar:>10.6f}  {err:>8.4f}\n")
            
            f.write("\n" + "="*60 + "\n")
            f.write(f"总体风险（LAR）: {risk_results['total']['lar_percent']:.6f}%\n")
            f.write("="*60 + "\n")
            
            f.write("\n注释:\n")
            f.write("- LAR: Lifetime Attributable Risk (终生归因风险)\n")
            f.write("- ERR: Excess Relative Risk (超额相对风险)\n")
            f.write("- 风险值表示患者在余生中因辐射照射而患相应癌症的额外概率\n")
        
        # 同时保存JSON格式
        json_path = output_path.with_suffix('.json')
        with open(json_path, 'w') as f:
            json.dump(risk_results, f, indent=2, ensure_ascii=False)
        
        print(f"✓ 报告已生成:")
        print(f"  文本报告: {output_path}")
        print(f"  JSON数据: {json_path}")


def example_risk_assessment():
    """示例风险评估"""
    print("="*60)
    print("BEIR VII 风险评估示例")
    print("="*60)
    
    # 1. 初始化引擎
    engine = BEIRVII_RiskEngine(
        patient_age=10,
        patient_gender='female'
    )
    
    # 2. 示例器官剂量（Sv）
    organ_doses = {
        'Thyroid': 0.15,
        'Lung, left': 0.08,
        'Lung, right': 0.09,
        'Liver': 0.03,
        'Stomach wall': 0.05,
        'Colon': 0.04,
        'Esophagus': 0.12,
        'Bone marrow, head': 0.02,
        'Brain': 0.25
    }
    
    # 3. 评估所有器官
    risk_results = engine.assess_all_organs(organ_doses, life_expectancy=85)
    
    # 4. 生成报告
    # engine.generate_risk_report(
    #     risk_results,
    #     'output/risk_assessment_report.txt'
    # )
    
    # 5. 显示主要结果
    print("\n主要风险结果:")
    for site, data in sorted(risk_results.items(), 
                           key=lambda x: x[1].get('lar_percent', 0),
                           reverse=True)[:5]:
        if site != 'total':
            print(f"  {site}: {data['lar_percent']:.6f}%")
    
    print("\n" + "="*60)
    print("风险评估示例完成！")
    print("="*60)


if __name__ == "__main__":
    example_risk_assessment()
