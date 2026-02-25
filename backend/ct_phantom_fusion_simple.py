#!/usr/bin/env python3
"""
CT-体模混合拼接算法（简化版 - 无nibabel依赖）
CT-Phantom Fusion Module (Simplified - No nibabel dependency)

此版本使用numpy数组直接处理，不依赖nibabel
适用于预先转换为.npy格式的CT数据

Author: BNCT Team  
Date: 2026-02-11
"""

import numpy as np
from scipy import ndimage
from typing import Tuple, Dict, Optional
import json
from pathlib import Path


class CTPhantomFusion:
    """
    CT-体模融合器（简化版）
    
    将患者的局部CT影像精确地融合到缩放后的全身体模中
    使用numpy数组，避免nibabel依赖
    """
    
    def __init__(self):
        """初始化融合器"""
        print("初始化CT-体模融合器（简化版 - 无nibabel依赖）")
        self.ct_data = None
        self.ct_spacing = (1.0, 1.0, 1.0)  # 默认体素间距(mm)
        self.phantom_data = None
        self.tumor_mask = None
        self.fusion_result = None
        
    def load_ct_from_npy(self, npy_path: str, spacing: Tuple[float, float, float] = (1.0, 1.0, 1.0)):
        """
        从numpy数组加载CT影像
        
        Parameters:
        -----------
        npy_path : str
            .npy文件路径
        spacing : tuple
            体素间距 (x, y, z) in mm
        """
        print(f"\n从numpy文件加载CT影像: {npy_path}")
        
        self.ct_data = np.load(npy_path)
        self.ct_spacing = spacing
        
        print(f"✓ CT影像尺寸: {self.ct_data.shape}")
        print(f"  体素间距: {spacing} mm")
        print(f"  数值范围: [{self.ct_data.min():.1f}, {self.ct_data.max():.1f}]")
    
    def load_ct_array(self, ct_array: np.ndarray, spacing: Tuple[float, float, float] = (1.0, 1.0, 1.0)):
        """
        直接从numpy数组加载CT
        
        Parameters:
        -----------
        ct_array : np.ndarray
            CT数据数组
        spacing : tuple
            体素间距
        """
        print(f"\n从numpy数组加载CT影像")
        
        self.ct_data = ct_array
        self.ct_spacing = spacing
        
        print(f"✓ CT影像尺寸: {self.ct_data.shape}")
        print(f"  数值范围: [{self.ct_data.min():.1f}, {self.ct_data.max():.1f}]")
        
    def load_tumor_mask_npy(self, mask_path: str):
        """
        从numpy数组加载肿瘤掩膜
        
        Parameters:
        -----------
        mask_path : str
            掩膜.npy文件路径
        """
        print(f"\n加载肿瘤掩膜: {mask_path}")
        
        self.tumor_mask = np.load(mask_path).astype(bool)
        
        tumor_volume = np.sum(self.tumor_mask) * np.prod(self.ct_spacing) / 1000
        
        print(f"✓ 肿瘤掩膜尺寸: {self.tumor_mask.shape}")
        print(f"  肿瘤体积: {tumor_volume:.2f} cm³")
        print(f"  肿瘤体素数: {np.sum(self.tumor_mask)}")
        
    def register_ct_to_phantom(self,
                              phantom_data: np.ndarray,
                              phantom_voxel_size: Tuple[float, float, float],
                              tumor_location: str = 'brain',
                              registration_params: Optional[Dict] = None) -> Dict:
        """
        将CT配准到体模
        
        这里使用基于解剖位置的刚性配准
        
        Parameters:
        -----------
        phantom_data : np.ndarray
            体模数据
        phantom_voxel_size : tuple
            体模体素尺寸 (mm)
        tumor_location : str
            肿瘤位置 ('brain', 'lung', 'liver'等)
        registration_params : dict, optional
            配准参数
            
        Returns:
        --------
        dict
            配准变换参数
        """
        print(f"\n配准CT到体模（肿瘤位置: {tumor_location}）...")
        
        self.phantom_data = phantom_data
        
        # 定义解剖位置的大致范围（在体模中）
        ANATOMICAL_REGIONS = {
            'brain': {
                'z_range': (0.75, 0.95),
                'center_offset': (0, 0, 0)
            },
            'lung': {
                'z_range': (0.5, 0.7),
                'center_offset': (0, 0, 0)
            },
            'liver': {
                'z_range': (0.45, 0.6),
                'center_offset': (0.05, 0, 0)
            },
            'nasopharynx': {
                'z_range': (0.7, 0.8),
                'center_offset': (0, -0.1, 0)
            }
        }
        
        region = ANATOMICAL_REGIONS.get(tumor_location, ANATOMICAL_REGIONS['brain'])
        
        # 计算目标区域在体模中的位置
        phantom_shape = phantom_data.shape
        z_start = int(phantom_shape[2] * region['z_range'][0])
        z_end = int(phantom_shape[2] * region['z_range'][1])
        
        # CT的中心应该对应到这个区域的中心
        target_center = np.array([
            phantom_shape[0] // 2 + region['center_offset'][0] * phantom_shape[0],
            phantom_shape[1] // 2 + region['center_offset'][1] * phantom_shape[1],
            (z_start + z_end) // 2 + region['center_offset'][2] * phantom_shape[2]
        ])
        
        # CT影像的中心
        ct_center = np.array(self.ct_data.shape) / 2
        
        # 计算平移
        translation = target_center - ct_center
        
        # 计算缩放（匹配体素尺寸）
        ct_spacing_arr = np.array(self.ct_spacing)
        phantom_spacing = np.array(phantom_voxel_size)
        scaling = ct_spacing_arr / phantom_spacing
        
        registration = {
            'translation': translation.tolist(),
            'rotation': [0, 0, 0],
            'scaling': scaling.tolist(),
            'target_center': target_center.tolist(),
            'ct_center': ct_center.tolist(),
            'anatomical_region': tumor_location,
            'z_range': [z_start, z_end]
        }
        
        print(f"✓ 配准参数:")
        print(f"  平移: {translation}")
        print(f"  目标位置（体模坐标）: {target_center}")
        print(f"  Z轴范围: {z_start} - {z_end}")
        
        return registration
    
    def fuse_ct_into_phantom(self,
                            registration: Dict,
                            transition_width: int = 5) -> np.ndarray:
        """
        将CT融合到体模中
        
        Parameters:
        -----------
        registration : dict
            配准参数
        transition_width : int
            过渡区域宽度（体素数）
            
        Returns:
        --------
        np.ndarray
            融合后的体模数据
        """
        print(f"\n执行CT-体模融合...")
        print(f"  过渡区域宽度: {transition_width} 体素")
        
        # 创建融合结果数组（复制体模）
        fusion_result = self.phantom_data.copy()
        
        # 获取配准参数
        translation = np.array(registration['translation'])
        
        # 确定CT在体模中的边界框
        ct_shape = np.array(self.ct_data.shape)
        
        # CT的起始位置（在体模坐标系中）
        ct_start = (translation - ct_shape / 2).astype(int)
        ct_end = ct_start + ct_shape
        
        # 确保在体模范围内
        phantom_shape = np.array(self.phantom_data.shape)
        ct_start_clipped = np.maximum(ct_start, 0)
        ct_end_clipped = np.minimum(ct_end, phantom_shape)
        
        print(f"  CT在体模中的位置:")
        print(f"    起始: {ct_start_clipped}")
        print(f"    结束: {ct_end_clipped}")
        
        # 计算CT中对应的范围
        ct_offset = ct_start_clipped - ct_start
        ct_region_shape = ct_end_clipped - ct_start_clipped
        ct_region_end = ct_offset + ct_region_shape
        
        # 提取CT区域
        ct_region = self.ct_data[
            ct_offset[0]:ct_region_end[0],
            ct_offset[1]:ct_region_end[1],
            ct_offset[2]:ct_region_end[2]
        ]
        
        # 将CT的HU值转换为体模的器官ID
        ct_as_organ_ids = self._convert_hu_to_organ_ids(ct_region)

        # 如果有肿瘤掩膜，特殊处理肿瘤区域
        if self.tumor_mask is not None:
            tumor_region = self.tumor_mask[
                ct_offset[0]:ct_region_end[0],
                ct_offset[1]:ct_region_end[1],
                ct_offset[2]:ct_region_end[2]
            ]

            # 肿瘤用特殊的器官ID（例如999）
            ct_as_organ_ids[tumor_region] = 999

            print(f"  肿瘤体素数: {np.sum(tumor_region)}")

        # ★ 横截面轮廓自适应匹配 ★
        # 在Z边界处测量CT和体模的体宽，对CT做自适应XY缩放
        phantom_overlap = fusion_result[
            ct_start_clipped[0]:ct_end_clipped[0],
            ct_start_clipped[1]:ct_end_clipped[1],
            ct_start_clipped[2]:ct_end_clipped[2]
        ]
        ct_as_organ_ids = self._adaptive_xy_scale(
            ct_as_organ_ids, phantom_overlap)

        # 创建过渡区域掩膜
        transition_mask = self._create_transition_mask(
            ct_region.shape,
            transition_width
        )

        # 融合：
        # - 中心区域：完全使用CT
        # - 过渡区域：混合
        # - 外部区域：保持体模

        # 中心区域（非过渡区）
        core_mask = transition_mask == 0

        # 直接替换中心区域
        fusion_result[
            ct_start_clipped[0]:ct_end_clipped[0],
            ct_start_clipped[1]:ct_end_clipped[1],
            ct_start_clipped[2]:ct_end_clipped[2]
        ][core_mask] = ct_as_organ_ids[core_mask]

        # 过渡区域：平滑混合
        for i in range(1, transition_width + 1):
            layer_mask = transition_mask == i

            # 简化：在过渡区域优先使用CT
            fusion_result[
                ct_start_clipped[0]:ct_end_clipped[0],
                ct_start_clipped[1]:ct_end_clipped[1],
                ct_start_clipped[2]:ct_end_clipped[2]
            ][layer_mask] = ct_as_organ_ids[layer_mask]

        self.fusion_result = fusion_result

        replacement_volume = np.sum(core_mask) + np.sum(transition_mask > 0)
        print(f"  融合完成")
        print(f"  替换体素数: {replacement_volume:,}")
        print(f"  替换比例: {replacement_volume / fusion_result.size * 100:.2f}%")

        return fusion_result
    
    def _adaptive_xy_scale(self, ct_organ_ids: np.ndarray,
                           phantom_region: np.ndarray,
                           blend_slices: int = 3) -> np.ndarray:
        """
        在Z边界处测量CT与体模的XY体宽, 对CT做逐层自适应缩放
        使融合边界处的轮廓连续。

        中心区域保持CT原始精度，边界处逐渐缩放以匹配体模轮廓。
        """
        nz = ct_organ_ids.shape[2]
        if nz < 4:
            return ct_organ_ids

        nx, ny, _ = ct_organ_ids.shape

        # 逐层测量身体XY宽度
        ct_xw = np.zeros(nz)
        ct_yw = np.zeros(nz)
        ph_xw = np.zeros(nz)
        ph_yw = np.zeros(nz)

        for k in range(nz):
            ct_body = ct_organ_ids[:, :, k] > 0
            ph_body = phantom_region[:, :, k] > 0
            if np.any(ct_body):
                xs = np.where(ct_body)[0]
                ys = np.where(ct_body)[1]
                ct_xw[k] = xs.max() - xs.min() + 1
                ct_yw[k] = ys.max() - ys.min() + 1
            if np.any(ph_body):
                xs = np.where(ph_body)[0]
                ys = np.where(ph_body)[1]
                ph_xw[k] = xs.max() - xs.min() + 1
                ph_yw[k] = ys.max() - ys.min() + 1

        bs = min(blend_slices, nz // 4, 3)
        bs = max(bs, 1)

        def _avg_ratio(ct_w, ph_w, idx_list):
            ratios = []
            for i in idx_list:
                if ct_w[i] > 5 and ph_w[i] > 5:
                    ratios.append(ph_w[i] / ct_w[i])
            return np.mean(ratios) if ratios else 1.0

        sx_bot = _avg_ratio(ct_xw, ph_xw, list(range(0, bs)))
        sy_bot = _avg_ratio(ct_yw, ph_yw, list(range(0, bs)))
        sx_top = _avg_ratio(ct_xw, ph_xw, list(range(nz - bs, nz)))
        sy_top = _avg_ratio(ct_yw, ph_yw, list(range(nz - bs, nz)))

        if (abs(sx_bot - 1) < 0.05 and abs(sx_top - 1) < 0.05 and
                abs(sy_bot - 1) < 0.05 and abs(sy_top - 1) < 0.05):
            print(f"  [轮廓匹配] CT与体模宽度差异<5%, 无需缩放")
            return ct_organ_ids

        print(f"  [轮廓匹配] 底部缩放 X={sx_bot:.3f} Y={sy_bot:.3f}")
        print(f"  [轮廓匹配] 顶部缩放 X={sx_top:.3f} Y={sy_top:.3f}")

        result = ct_organ_ids.copy()
        for k in range(nz):
            t = k / max(nz - 1, 1)
            dist_to_edge = min(k, nz - 1 - k)
            fade_zone = max(nz * 0.3, 1)
            w = max(0.0, 1.0 - dist_to_edge / fade_zone)

            sx = 1.0 + w * ((sx_bot * (1 - t) + sx_top * t) - 1.0)
            sy = 1.0 + w * ((sy_bot * (1 - t) + sy_top * t) - 1.0)

            if abs(sx - 1) < 0.02 and abs(sy - 1) < 0.02:
                continue

            layer = ct_organ_ids[:, :, k].astype(np.float32)
            scaled = ndimage.zoom(layer, (sx, sy), order=0)
            snx, sny = scaled.shape
            out = np.zeros((nx, ny), dtype=np.int16)

            src_x0 = max(0, (snx - nx) // 2)
            src_y0 = max(0, (sny - ny) // 2)
            dst_x0 = max(0, (nx - snx) // 2)
            dst_y0 = max(0, (ny - sny) // 2)
            cw = min(snx - src_x0, nx - dst_x0)
            ch = min(sny - src_y0, ny - dst_y0)

            out[dst_x0:dst_x0 + cw,
                dst_y0:dst_y0 + ch] = scaled[
                src_x0:src_x0 + cw,
                src_y0:src_y0 + ch].astype(np.int16)
            result[:, :, k] = out

        print(f"  [轮廓匹配] 自适应缩放完成")
        return result

    def _convert_hu_to_organ_ids(self, ct_data: np.ndarray) -> np.ndarray:
        """
        将CT的HU值转换为器官ID
        
        基于HU值的组织分类
        """
        organ_ids = np.zeros_like(ct_data, dtype=np.int16)
        
        organ_ids[ct_data < -500] = 0
        organ_ids[(ct_data >= -500) & (ct_data < -100)] = 81
        organ_ids[(ct_data >= -100) & (ct_data < -50)] = 121
        organ_ids[(ct_data >= -50) & (ct_data < 100)] = 110
        organ_ids[ct_data >= 100] = 26
        
        return organ_ids
    
    def _create_transition_mask(self,
                               shape: Tuple[int, int, int],
                               width: int) -> np.ndarray:
        """创建过渡区域掩膜"""
        mask = np.ones(shape, dtype=bool)
        mask[width:-width, width:-width, width:-width] = False
        
        dist = ndimage.distance_transform_edt(~mask)
        
        transition_mask = np.zeros(shape, dtype=np.int16)
        for i in range(1, width + 1):
            transition_mask[(dist > 0) & (dist <= i)] = i
        
        return transition_mask
    
    def smooth_boundaries(self, fusion_data: np.ndarray) -> np.ndarray:
        """平滑器官边界"""
        print("\n平滑器官边界...")
        smoothed = ndimage.median_filter(fusion_data, size=3)
        print("✓ 边界平滑完成")
        return smoothed
    
    def export_fusion_result(self,
                            output_path: str,
                            voxel_size: Tuple[float, float, float],
                            metadata: Dict):
        """
        导出融合结果为numpy格式
        
        Parameters:
        -----------
        output_path : str
            输出文件路径 (.npy)
        voxel_size : tuple
            体素尺寸 (mm)
        metadata : dict
            元数据
        """
        if self.fusion_result is None:
            raise ValueError("请先执行融合操作")
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 保存为numpy格式
        np.save(output_path, self.fusion_result)
        
        # 保存元数据
        metadata_enhanced = {
            **metadata,
            'voxel_size': voxel_size,
            'shape': self.fusion_result.shape,
            'dtype': str(self.fusion_result.dtype)
        }
        
        metadata_path = output_path.with_suffix('.json')
        with open(metadata_path, 'w') as f:
            json.dump(metadata_enhanced, f, indent=2)
        
        print(f"\n✓ 融合结果已保存:")
        print(f"  数据: {output_path}")
        print(f"  元数据: {metadata_path}")


def example_fusion_workflow():
    """示例融合工作流程"""
    print("="*60)
    print("CT-体模融合示例工作流程（简化版）")
    print("="*60)
    
    # 1. 初始化融合器
    fusion = CTPhantomFusion()
    
    # 2. 创建示例数据
    print("\n创建示例数据...")
    ct_data = np.random.randn(100, 100, 100) * 100
    phantom_data = np.random.randint(0, 140, (254, 127, 222), dtype=np.int16)
    
    fusion.load_ct_array(ct_data, spacing=(1.0, 1.0, 1.0))
    
    # 3. 配准
    registration = fusion.register_ct_to_phantom(
        phantom_data,
        phantom_voxel_size=(2.137, 2.137, 8.0),
        tumor_location='brain'
    )
    
    # 4. 融合
    fusion_result = fusion.fuse_ct_into_phantom(
        registration,
        transition_width=5
    )
    
    print("\n" + "="*60)
    print("融合工作流程完成！")
    print("="*60)


if __name__ == "__main__":
    example_fusion_workflow()
