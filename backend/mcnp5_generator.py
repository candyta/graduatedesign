#!/usr/bin/env python3
"""
MCNP5全身输入文件生成器
MCNP5 Whole-Body Input File Generator

功能：
1. 从融合后的体模生成MCNP5几何
2. 定义材料和密度
3. 设置中子源
4. 配置计分卡（全身器官剂量）

Author: BNCT Team
Date: 2026-02-11
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import json


class MCNP5InputGenerator:
    """
    MCNP5输入文件生成器
    
    为全身BNCT剂量计算生成MCNP5输入文件
    """
    
    # BNCT相关的RBE/CBE因子
    RBE_CBE_FACTORS = {
        'tumor': {
            'boron': 3.8,
            'nitrogen': 3.2,
            'hydrogen': 3.2,
            'gamma': 1.0
        },
        'normal_tissue': {
            'boron': 1.35,
            'nitrogen': 3.2,
            'hydrogen': 3.2,
            'gamma': 1.0
        },
        'skin': {
            'boron': 2.5,
            'nitrogen': 3.2,
            'hydrogen': 3.2,
            'gamma': 1.0
        }
    }
    
    # 硼浓度（ppm）
    BORON_CONCENTRATIONS = {
        'tumor': 60.0,      # 肿瘤
        'skin': 25.0,       # 皮肤
        'blood': 25.0,      # 血液
        'normal': 18.0      # 正常组织
    }
    
    def __init__(self, phantom_data: np.ndarray,
                 voxel_size: Tuple[float, float, float],
                 organ_info: Dict):
        """
        初始化生成器
        
        Parameters:
        -----------
        phantom_data : np.ndarray
            体模数据（器官ID）
        voxel_size : tuple
            体素尺寸 (mm)
        organ_info : dict
            器官信息字典
        """
        self.phantom_data = phantom_data
        self.voxel_size = voxel_size
        self.organ_info = organ_info
        
        self.cell_cards = []
        self.surface_cards = []
        self.data_cards = []
        
        print("初始化MCNP5输入文件生成器")
        print(f"体模尺寸: {phantom_data.shape}")
        print(f"体素尺寸: {voxel_size} mm")
        print(f"器官数: {len(np.unique(phantom_data))}")
    
    def generate_voxel_geometry(self,
                               lattice_method: str = 'rpp') -> List[str]:
        """
        生成体素化几何
        
        使用RPP (Rectangular ParallelePiped) 或 lattice
        
        Parameters:
        -----------
        lattice_method : str
            几何方法 ('rpp', 'lattice')
            
        Returns:
        --------
        list
            几何定义卡片
        """
        print("\n生成MCNP5几何...")
        
        if lattice_method == 'lattice':
            return self._generate_lattice_geometry()
        else:
            return self._generate_rpp_geometry()
    
    def _generate_lattice_geometry(self) -> List[str]:
        """
        使用Lattice生成几何（推荐用于大型体模）
        
        Returns:
        --------
        list
            Cell和Surface卡片
        """
        cards = []
        
        nx, ny, nz = self.phantom_data.shape
        vx, vy, vz = self.voxel_size
        
        # 转换为cm
        vx_cm, vy_cm, vz_cm = vx/10, vy/10, vz/10
        
        cards.append("c ====== Lattice Geometry ======")
        cards.append("c Universe 1: Unit cell for lattice")
        
        # 为每个唯一的器官ID创建一个universe
        unique_organs = np.unique(self.phantom_data)
        
        # Cell cards for lattice
        cards.append("c --- Cell Cards ---")
        
        # Lattice fill cell
        cards.append(f"1 0 -1 lat=1 u=2 imp:n=1")
        cards.append(f"     fill=-{nx//2}:{nx//2-1} -{ny//2}:{ny//2-1} -{nz//2}:{nz//2-1}")
        
        # Universe definitions for each organ
        for organ_id in unique_organs:
            if organ_id == 0:  # 空气/真空
                mat_id = 0
            else:
                mat_id = organ_id
            
            cards.append(f"{100+organ_id} {mat_id} -1.0 -10{organ_id} u={organ_id} imp:n=1")
        
        # Surface cards
        cards.append("c --- Surface Cards ---")
        
        # Lattice boundaries
        cards.append(f"1 rpp {-vx_cm/2} {vx_cm/2} {-vy_cm/2} {vy_cm/2} {-vz_cm/2} {vz_cm/2}")
        
        # Unit cell surfaces for each organ
        for organ_id in unique_organs:
            cards.append(f"10{organ_id} rpp {-vx_cm/2} {vx_cm/2} {-vy_cm/2} {vy_cm/2} {-vz_cm/2} {vz_cm/2}")
        
        self.cell_cards.extend(cards)
        
        print(f"✓ Lattice几何生成完成")
        print(f"  Lattice尺寸: {nx} × {ny} × {nz}")
        print(f"  单元尺寸: {vx_cm:.4f} × {vy_cm:.4f} × {vz_cm:.4f} cm")
        
        return cards
    
    def _generate_rpp_geometry(self) -> List[str]:
        """
        使用RPP直接定义几何（适用于简化模型）
        
        这里为每个器官区域创建一个cell
        """
        cards = []
        cards.append("c ====== RPP Geometry (Simplified) ======")
        cards.append("c --- Cell Cards ---")
        
        # 为主要器官创建bounding box
        unique_organs = np.unique(self.phantom_data[self.phantom_data > 0])
        
        cell_id = 1
        surf_id = 1
        
        for organ_id in unique_organs[:20]:  # 限制数量以避免过大
            # 找到器官的边界
            coords = np.where(self.phantom_data == organ_id)
            if len(coords[0]) == 0:
                continue
            
            x_min, x_max = coords[0].min(), coords[0].max()
            y_min, y_max = coords[1].min(), coords[1].max()
            z_min, z_max = coords[2].min(), coords[2].max()
            
            # 转换为物理坐标（cm）
            x_min_cm = x_min * self.voxel_size[0] / 10
            x_max_cm = (x_max + 1) * self.voxel_size[0] / 10
            y_min_cm = y_min * self.voxel_size[1] / 10
            y_max_cm = (y_max + 1) * self.voxel_size[1] / 10
            z_min_cm = z_min * self.voxel_size[2] / 10
            z_max_cm = (z_max + 1) * self.voxel_size[2] / 10
            
            # Cell card
            mat_id = organ_id
            organ_name = self.organ_info.get(organ_id, {}).get('name', f'Organ{organ_id}')
            density = self.organ_info.get(organ_id, {}).get('density', 1.0)
            
            cards.append(f"c {organ_name}")
            cards.append(f"{cell_id} {mat_id} {-density:.3f} -{surf_id} imp:n=1")
            
            # Surface card (RPP)
            self.surface_cards.append(
                f"{surf_id} rpp {x_min_cm:.3f} {x_max_cm:.3f} "
                f"{y_min_cm:.3f} {y_max_cm:.3f} {z_min_cm:.3f} {z_max_cm:.3f}"
            )
            
            cell_id += 1
            surf_id += 1
        
        # 外部空气
        cards.append(f"c External void")
        cards.append(f"{cell_id} 0 {surf_id} imp:n=0")
        self.surface_cards.append(f"{surf_id} so 1000")  # 大球包围
        
        self.cell_cards.extend(cards)
        
        print(f"✓ RPP几何生成完成")
        print(f"  器官数: {len(unique_organs[:20])}")
        
        return cards
    
    def generate_materials(self, media_info: Dict) -> List[str]:
        """
        生成材料定义
        
        Parameters:
        -----------
        media_info : dict
            介质组成信息
            
        Returns:
        --------
        list
            材料卡片
        """
        print("\n生成材料定义...")
        
        cards = []
        cards.append("c ====== Material Cards ======")
        
        # 为每个器官定义材料
        unique_organs = np.unique(self.phantom_data)
        
        for organ_id in unique_organs:
            if organ_id == 0:
                continue
            
            organ_name = self.organ_info.get(organ_id, {}).get('name', f'Organ{organ_id}')
            tissue_num = self.organ_info.get(organ_id, {}).get('tissue_number', 1)
            
            # 获取组织的元素组成
            if tissue_num in media_info:
                composition = media_info[tissue_num]['composition']
            else:
                # 默认软组织组成
                composition = {
                    'H': 0.102,   # 10.2%
                    'C': 0.143,   # 14.3%
                    'N': 0.034,   # 3.4%
                    'O': 0.708,   # 70.8%
                    'Na': 0.002,
                    'P': 0.003,
                    'S': 0.003,
                    'Cl': 0.002,
                    'K': 0.003
                }
            
            cards.append(f"c {organ_name}")
            cards.append(f"m{organ_id}")
            
            # 添加硼-10（BNCT关键）
            boron_conc = self._get_boron_concentration(organ_id)
            if boron_conc > 0:
                # 硼浓度转换为原子分数
                boron_fraction = boron_conc * 1e-6 * 10.0 / 11.0  # 简化计算
                cards.append(f"      5010.80c {boron_fraction:.6e}  $ B-10")
            
            # 添加其他元素
            element_zaid = {
                'H': '1001.80c',
                'C': '6000.80c',
                'N': '7014.80c',
                'O': '8016.80c',
                'Na': '11023.80c',
                'Mg': '12000.80c',
                'P': '15031.80c',
                'S': '16032.80c',
                'Cl': '17000.80c',
                'K': '19000.80c',
                'Ca': '20000.80c',
                'Fe': '26000.55c',
                'I': '53127.80c'
            }
            
            for elem, fraction in composition.items():
                if elem in element_zaid and fraction > 0:
                    cards.append(f"      {element_zaid[elem]} {-fraction:.6f}")
        
        self.data_cards.extend(cards)
        
        print(f"✓ 材料定义生成完成")
        print(f"  材料数: {len(unique_organs) - 1}")  # 排除空气
        
        return cards
    
    def _get_boron_concentration(self, organ_id: int) -> float:
        """获取器官的硼浓度"""
        if organ_id == 999:  # 肿瘤
            return self.BORON_CONCENTRATIONS['tumor']
        
        organ_name = self.organ_info.get(organ_id, {}).get('name', '').lower()
        
        if 'skin' in organ_name:
            return self.BORON_CONCENTRATIONS['skin']
        elif 'blood' in organ_name:
            return self.BORON_CONCENTRATIONS['blood']
        else:
            return self.BORON_CONCENTRATIONS['normal']
    
    def generate_source(self,
                       source_type: str = 'epithermal_neutron',
                       beam_params: Optional[Dict] = None) -> List[str]:
        """
        生成中子源定义
        
        Parameters:
        -----------
        source_type : str
            源类型 ('epithermal_neutron', 'thermal_neutron')
        beam_params : dict, optional
            束流参数
            
        Returns:
        --------
        list
            源定义卡片
        """
        print(f"\n生成中子源（类型: {source_type}）...")
        
        cards = []
        cards.append("c ====== Source Definition ======")
        
        if source_type == 'epithermal_neutron':
            # 超热中子束（BNCT常用）
            cards.append("sdef pos=0 0 100 axs=0 0 -1 ext=0 rad=d1 erg=d2 par=1")
            cards.append("si1 0 5  $ beam radius distribution (cm)")
            cards.append("sp1 -21 1  $ uniform over area")
            cards.append("c Epithermal neutron energy spectrum")
            cards.append("si2 L 0.5e-6 1e-6 10e-6 100e-6 1e-3 0.01 0.1 1.0 10")
            cards.append("sp2 D 0 0.05 0.15 0.25 0.25 0.15 0.1 0.04 0.01")
        
        self.data_cards.extend(cards)
        
        print("✓ 中子源定义完成")
        
        return cards
    
    def generate_tallies(self, organs_of_interest: Optional[List[int]] = None) -> List[str]:
        """
        生成计分卡（全身器官剂量）
        
        Parameters:
        -----------
        organs_of_interest : list, optional
            关注的器官ID列表，None表示所有器官
            
        Returns:
        --------
        list
            计分卡定义
        """
        print("\n生成计分卡...")
        
        cards = []
        cards.append("c ====== Tally Cards ======")
        cards.append("c Organ dose tallies")
        
        # F6 tally: Energy deposition (MeV/g)
        if organs_of_interest is None:
            organs_of_interest = np.unique(self.phantom_data[self.phantom_data > 0])
        
        tally_id = 6
        cards.append(f"f{tally_id}:n ")
        
        # 为每个器官添加cell
        for organ_id in organs_of_interest[:100]:  # 限制数量
            cards.append(f"     {organ_id}")
        
        # 剂量转换因子
        cards.append(f"c Dose conversion factors")
        cards.append(f"de{tally_id} 0.01 0.1 1.0 10.0")
        cards.append(f"df{tally_id} 1.0 1.0 1.0 1.0")
        
        self.data_cards.extend(cards)
        
        print(f"✓ 计分卡生成完成")
        print(f"  监测器官数: {len(organs_of_interest[:100])}")
        
        return cards
    
    def write_input_file(self, output_path: str,
                        title: str = "BNCT Whole-Body Dose Calculation"):
        """
        写入MCNP5输入文件
        
        Parameters:
        -----------
        output_path : str
            输出文件路径
        title : str
            计算标题
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"\n写入MCNP5输入文件: {output_path}")
        
        with open(output_path, 'w') as f:
            # Title
            f.write(f"{title}\n")
            f.write("c " + "="*60 + "\n")
            f.write("c Generated by BNCT Whole-Body Risk Assessment Platform\n")
            f.write("c " + "="*60 + "\n\n")
            
            # Cell cards
            f.write("c " + "-"*60 + "\n")
            f.write("c CELL CARDS\n")
            f.write("c " + "-"*60 + "\n")
            for card in self.cell_cards:
                f.write(card + "\n")
            f.write("\n")
            
            # Surface cards
            f.write("c " + "-"*60 + "\n")
            f.write("c SURFACE CARDS\n")
            f.write("c " + "-"*60 + "\n")
            for card in self.surface_cards:
                f.write(card + "\n")
            f.write("\n")
            
            # Data cards
            f.write("c " + "-"*60 + "\n")
            f.write("c DATA CARDS\n")
            f.write("c " + "-"*60 + "\n")
            for card in self.data_cards:
                f.write(card + "\n")
            f.write("\n")
            
            # Physics and control
            f.write("c " + "-"*60 + "\n")
            f.write("c PHYSICS AND CONTROL\n")
            f.write("c " + "-"*60 + "\n")
            f.write("mode n\n")
            f.write("phys:n 20 0 0 -1 -1\n")
            f.write("nps 1000000  $ number of particles\n")
            f.write("prdmp 100000 100000 1 1\n")
        
        print(f"✓ MCNP5输入文件已生成")
        print(f"  文件大小: {output_path.stat().st_size / 1024:.2f} KB")


def example_mcnp_generation():
    """示例MCNP5文件生成"""
    print("="*60)
    print("MCNP5输入文件生成示例")
    print("="*60)
    
    # 创建示例数据
    phantom_data = np.random.randint(0, 140, (254, 127, 222), dtype=np.int16)
    voxel_size = (2.137, 2.137, 8.0)
    
    # 示例器官信息
    organ_info = {
        i: {'name': f'Organ_{i}', 'tissue_number': 1, 'density': 1.0}
        for i in range(1, 141)
    }
    
    # 初始化生成器
    generator = MCNP5InputGenerator(phantom_data, voxel_size, organ_info)
    
    # 生成几何
    generator.generate_voxel_geometry(lattice_method='rpp')
    
    # 生成材料
    media_info = {}
    generator.generate_materials(media_info)
    
    # 生成源
    generator.generate_source()
    
    # 生成计分卡
    generator.generate_tallies()
    
    # 写入文件
    # generator.write_input_file('output/bnct_whole_body.inp')
    
    print("\n" + "="*60)
    print("MCNP5文件生成完成！")
    print("="*60)


if __name__ == "__main__":
    example_mcnp_generation()
