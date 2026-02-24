#!/usr/bin/env python3
"""
ICRP 110 Adult Reference Computational Phantom Data Loader
用于读取和处理ICRP Publication 110的成人参考体模数据

Author: Claude
Date: 2026-02-11
"""

import numpy as np
import os
from pathlib import Path
from typing import Dict, Tuple, Optional
import struct


class ICRP110Phantom:
    """ICRP 110体模数据加载和处理类"""
    
    # 体模维度 (根据README.txt)
    PHANTOM_DIMS = {
        'AM': {  # Adult Male
            'columns': 254,
            'rows': 127,
            'slices': 222,
            'voxel_size': (2.137, 2.137, 8.0),  # mm (x, y, z)
            'height': 176,  # cm
            'mass': 73  # kg
        },
        'AF': {  # Adult Female
            'columns': 299,
            'rows': 137,
            'slices': 348,
            'voxel_size': (1.775, 1.775, 4.84),  # mm (x, y, z)
            'height': 163,  # cm
            'mass': 60  # kg
        }
    }
    
    def __init__(self, data_dir: str, phantom_type: str = 'AM'):
        """
        初始化体模加载器
        
        Parameters:
        -----------
        data_dir : str
            ICRP 110数据目录路径
        phantom_type : str
            体模类型，'AM' (成人男性) 或 'AF' (成人女性)
        """
        self.data_dir = Path(data_dir)
        self.phantom_type = phantom_type.upper()
        
        if self.phantom_type not in ['AM', 'AF']:
            raise ValueError("phantom_type must be 'AM' or 'AF'")
        
        self.dims = self.PHANTOM_DIMS[self.phantom_type]
        self.phantom_dir = self.data_dir / self.phantom_type
        
        # 数据容器
        self.voxel_data = None  # 器官ID数组
        self.organs = {}  # 器官信息字典
        self.media = {}   # 介质信息字典
        self.spongiosa = {}  # 骨松质信息
        self.blood_ratios = {}  # 血液比例
        
        print(f"初始化 ICRP 110 {self.phantom_type} 体模加载器")
        print(f"体模尺寸: {self.dims['columns']} × {self.dims['rows']} × {self.dims['slices']}")
        print(f"体素尺寸: {self.dims['voxel_size']} mm")
        print(f"参考身高: {self.dims['height']} cm, 体重: {self.dims['mass']} kg")
    
    def load_all(self):
        """加载所有数据"""
        print("\n开始加载ICRP 110体模数据...")
        self.load_organs()
        self.load_media()
        self.load_voxel_data()
        self.load_spongiosa()
        self.load_blood_ratios()
        print("✓ 所有数据加载完成！")
        
    def load_organs(self):
        """读取器官定义文件"""
        organ_file = self.phantom_dir / f"{self.phantom_type}_organs.dat"
        print(f"\n加载器官定义: {organ_file}")
        
        with open(organ_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        # 跳过前4行标题
        for line in lines[4:]:
            line = line.strip()
            if not line or line.startswith('Organ'):
                continue
            
            parts = line.split()
            if len(parts) >= 4:
                try:
                    organ_id = int(parts[0])
                    density = float(parts[-1])
                    tissue_num = int(parts[-2])
                    
                    # 器官名称可能包含空格
                    name_parts = parts[1:-2]
                    organ_name = ' '.join(name_parts)
                    
                    self.organs[organ_id] = {
                        'name': organ_name,
                        'tissue_number': tissue_num,
                        'density': density
                    }
                except (ValueError, IndexError) as e:
                    continue
        
        print(f"✓ 加载了 {len(self.organs)} 个器官定义")
        
    def load_media(self):
        """读取介质组成定义文件"""
        media_file = self.phantom_dir / f"{self.phantom_type}_media.dat"
        print(f"\n加载介质定义: {media_file}")
        
        with open(media_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        # 解析元素列表（第一行）
        elements_line = lines[0]
        elements = []
        for part in elements_line.split():
            if part.strip().isalpha() and len(part) <= 2:
                elements.append(part.strip())
        
        # 跳过前3行标题
        for line in lines[3:]:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split()
            if len(parts) >= 3:
                try:
                    media_num = int(parts[0])
                    # 介质名称
                    name_end = -len(elements)
                    media_name = ' '.join(parts[1:name_end])
                    
                    # 元素组成（质量百分比）
                    composition = {}
                    mass_fractions = [float(x) for x in parts[name_end:]]
                    for elem, fraction in zip(elements, mass_fractions):
                        if fraction > 0:
                            composition[elem] = fraction / 100.0  # 转换为小数
                    
                    self.media[media_num] = {
                        'name': media_name,
                        'composition': composition
                    }
                except (ValueError, IndexError) as e:
                    continue
        
        print(f"✓ 加载了 {len(self.media)} 种介质定义")
    
    def load_voxel_data(self):
        """读取体素数据（器官ID数组）"""
        voxel_file = self.phantom_dir / f"{self.phantom_type}.dat"
        print(f"\n加载体素数据: {voxel_file}")
        print("这可能需要几秒钟...")
        
        ncol = self.dims['columns']
        nrow = self.dims['rows']
        nsli = self.dims['slices']
        
        # 初始化数组
        self.voxel_data = np.zeros((ncol, nrow, nsli), dtype=np.int16)
        
        # 读取文件
        with open(voxel_file, 'r') as f:
            all_numbers = []
            for line in f:
                numbers = [int(x) for x in line.split()]
                all_numbers.extend(numbers)
        
        # 填充数组（按照README说明的顺序）
        idx = 0
        for nsl in range(nsli):
            for nr in range(nrow):
                for nc in range(ncol):
                    if idx < len(all_numbers):
                        self.voxel_data[nc, nr, nsl] = all_numbers[idx]
                        idx += 1
        
        total_voxels = ncol * nrow * nsli
        print(f"✓ 加载了 {total_voxels:,} 个体素")
        print(f"  非零体素: {np.count_nonzero(self.voxel_data):,}")
        print(f"  唯一器官ID数: {len(np.unique(self.voxel_data))}")
        
    def load_spongiosa(self):
        """读取骨松质组成比例"""
        spongiosa_file = self.phantom_dir / f"{self.phantom_type}_spongiosa.dat"
        print(f"\n加载骨松质数据: {spongiosa_file}")
        
        with open(spongiosa_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        for line in lines[3:]:  # 跳过标题
            parts = line.split()
            if len(parts) >= 5:
                try:
                    organ_id = int(parts[0])
                    trabecular = float(parts[2])
                    red_marrow = float(parts[3])
                    yellow_marrow = float(parts[4])
                    
                    self.spongiosa[organ_id] = {
                        'trabecular_bone': trabecular,
                        'red_marrow': red_marrow,
                        'yellow_marrow': yellow_marrow
                    }
                except (ValueError, IndexError):
                    continue
        
        print(f"✓ 加载了 {len(self.spongiosa)} 个骨松质区域")
    
    def load_blood_ratios(self):
        """读取血液比例数据"""
        blood_file = self.phantom_dir / f"{self.phantom_type}_blood.dat"
        print(f"\n加载血液比例: {blood_file}")
        
        with open(blood_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        for line in lines[3:]:  # 跳过标题
            parts = line.split()
            if len(parts) >= 3:
                try:
                    organ_id = int(parts[0])
                    blood_ratio = float(parts[2])
                    
                    self.blood_ratios[organ_id] = blood_ratio
                except (ValueError, IndexError):
                    continue
        
        print(f"✓ 加载了 {len(self.blood_ratios)} 个器官的血液比例")
    
    def get_organ_volume(self, organ_id: int) -> float:
        """
        计算指定器官的体积（cm³）
        
        Parameters:
        -----------
        organ_id : int
            器官ID
            
        Returns:
        --------
        float
            器官体积（cm³）
        """
        if self.voxel_data is None:
            raise ValueError("请先加载体素数据")
        
        # 计算体素体积（mm³ -> cm³）
        voxel_volume = np.prod(self.dims['voxel_size']) / 1000.0
        
        # 计算器官体素数
        voxel_count = np.sum(self.voxel_data == organ_id)
        
        return voxel_count * voxel_volume
    
    def get_organ_mass(self, organ_id: int) -> float:
        """
        计算指定器官的质量（g）
        
        Parameters:
        -----------
        organ_id : int
            器官ID
            
        Returns:
        --------
        float
            器官质量（g）
        """
        volume = self.get_organ_volume(organ_id)
        
        if organ_id in self.organs:
            density = self.organs[organ_id]['density']
            return volume * density
        
        return volume * 1.0  # 默认密度
    
    def get_organ_name(self, organ_id: int) -> str:
        """获取器官名称"""
        if organ_id in self.organs:
            return self.organs[organ_id]['name']
        return f"Unknown (ID: {organ_id})"
    
    def get_voxel_position(self, i: int, j: int, k: int) -> Tuple[float, float, float]:
        """
        获取体素的物理位置（mm）
        
        Parameters:
        -----------
        i, j, k : int
            体素索引
            
        Returns:
        --------
        tuple
            (x, y, z) 物理坐标（mm）
        """
        vx, vy, vz = self.dims['voxel_size']
        x = i * vx
        y = j * vy
        z = k * vz
        return (x, y, z)
    
    def export_summary(self, output_file: str):
        """导出体模摘要信息"""
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"ICRP 110 {self.phantom_type} 体模摘要\n")
            f.write("="*60 + "\n\n")
            
            f.write(f"体模类型: {self.phantom_type}\n")
            f.write(f"参考身高: {self.dims['height']} cm\n")
            f.write(f"参考体重: {self.dims['mass']} kg\n")
            f.write(f"体模尺寸: {self.dims['columns']} × {self.dims['rows']} × {self.dims['slices']}\n")
            f.write(f"体素尺寸: {self.dims['voxel_size']} mm\n\n")
            
            f.write("器官列表和体积:\n")
            f.write("-"*60 + "\n")
            f.write(f"{'ID':<5} {'器官名称':<40} {'体积(cm³)':<12} {'质量(g)':<12}\n")
            f.write("-"*60 + "\n")
            
            for organ_id in sorted(self.organs.keys()):
                name = self.organs[organ_id]['name']
                volume = self.get_organ_volume(organ_id)
                mass = self.get_organ_mass(organ_id)
                if volume > 0:
                    f.write(f"{organ_id:<5} {name:<40} {volume:>10.2f}  {mass:>10.2f}\n")
        
        print(f"\n✓ 摘要已导出到: {output_file}")


def test_loader():
    """测试加载器"""
    print("="*60)
    print("ICRP 110 体模数据加载器测试")
    print("="*60)
    
    # 数据目录
    data_dir = "/home/claude/ICRP110_data/P110 data V1.2"
    
    # 加载成人男性体模
    print("\n【测试1】加载成人男性体模 (AM)")
    am_phantom = ICRP110Phantom(data_dir, 'AM')
    am_phantom.load_all()
    
    # 测试一些器官的体积
    print("\n【测试2】计算器官体积和质量")
    test_organs = [
        (77, "Liver"),
        (81, "Lung, left"),
        (82, "Lung, right"),
        (87, "Heart"),
    ]
    
    for organ_id, expected_name in test_organs:
        name = am_phantom.get_organ_name(organ_id)
        volume = am_phantom.get_organ_volume(organ_id)
        mass = am_phantom.get_organ_mass(organ_id)
        print(f"器官 {organ_id}: {name}")
        print(f"  体积: {volume:.2f} cm³")
        print(f"  质量: {mass:.2f} g")
    
    # 导出摘要
    print("\n【测试3】导出体模摘要")
    am_phantom.export_summary("/home/claude/ICRP110_AM_summary.txt")
    
    print("\n" + "="*60)
    print("测试完成！")
    print("="*60)


if __name__ == "__main__":
    test_loader()
