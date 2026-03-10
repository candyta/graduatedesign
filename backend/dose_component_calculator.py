#!/usr/bin/env python3
"""
BNCT 剂量组分计算器
BNCT Dose Component Calculator

功能：
1. 配置中子源参数（位置、方向、能量/能谱）
2. 配置体模位置与朝向
3. 计算四个剂量组分：硼剂量、氮剂量、氢剂量、伽马剂量
4. 应用CBE/RBE权重因子得到生物加权总剂量

物理背景（BNCT剂量分量）：
  D_total = CBE_B × D_B + RBE_N × D_N + RBE_H × D_H + RBE_γ × D_γ

  D_B  ← ¹⁰B(n,α)⁷Li 反应（热中子俘获）
  D_N  ← ¹⁴N(n,p)¹⁴C 反应（快中子）
  D_H  ← ¹H(n,γ)²H 散射质子反冲
  D_γ  ← 光子沉积

Author: BNCT Team
Date: 2026-03-10
"""

import numpy as np
import json
from typing import Dict, List, Tuple, Optional


# ─────────────────────────────────────────────
# 默认 CBE / RBE 因子（IAEA TECDOC-1223）
# ─────────────────────────────────────────────
DEFAULT_CBE_RBE = {
    "tumor": {
        "boron_cbe":    3.8,   # 肿瘤硼 CBE（化合物生物效应）
        "nitrogen_rbe": 3.2,   # 氮俘获 RBE
        "hydrogen_rbe": 3.2,   # 氢反冲 RBE
        "gamma_rbe":    1.0    # 伽马 RBE（参考辐射）
    },
    "normal_tissue": {
        "boron_cbe":    1.35,
        "nitrogen_rbe": 3.2,
        "hydrogen_rbe": 3.2,
        "gamma_rbe":    1.0
    },
    "skin": {
        "boron_cbe":    2.5,
        "nitrogen_rbe": 3.2,
        "hydrogen_rbe": 3.2,
        "gamma_rbe":    1.0
    }
}

# 默认硼浓度 (ppm = μg/g)
DEFAULT_BORON_CONC = {
    "tumor":         60.0,
    "skin":          25.0,
    "blood":         25.0,
    "normal_tissue": 18.0
}

# ¹⁰B 宏观截面（热中子，0.0253 eV）
SIGMA_B10_THERMAL = 3840.0   # 靶核截面 (barn)
AVOGADRO = 6.022e23
B10_MASS  = 10.0             # g/mol
B10_ABUNDANCE = 0.196        # 天然丰度

# ¹⁴N 热中子俘获截面（ENDF/B-VIII.0）
SIGMA_N14_THERMAL = 1.83     # barn

# 每次反应沉积能量 (MeV→cGy·cm³ 转换用)
Q_B10 = 2.31    # MeV（¹⁰B(n,α) 反应 Q 值，扣去 γ）
Q_N14 = 0.626   # MeV（¹⁴N(n,p) Q 值）


class SourceConfig:
    """中子源配置"""

    def __init__(self,
                 position: Tuple[float, float, float] = (0.0, 0.0, 100.0),
                 direction: Tuple[float, float, float] = (0.0, 0.0, -1.0),
                 beam_radius: float = 5.0,
                 source_type: str = "epithermal",
                 energy_mono: Optional[float] = None,
                 energy_spectrum: Optional[Dict] = None,
                 intensity: float = 1.0e12):
        """
        Parameters
        ----------
        position      : (x, y, z) 源位置，cm
        direction     : (ux, uy, uz) 束流方向（单位向量）
        beam_radius   : 束流半径 (cm)
        source_type   : 'epithermal' | 'thermal' | 'mono' | 'custom_spectrum'
        energy_mono   : 单能能量 (MeV)，source_type='mono' 时使用
        energy_spectrum: {'energies': [...], 'weights': [...]} 多群能谱
        intensity     : 中子通量强度 (n/cm²/s)
        """
        self.position    = list(position)
        raw_dir = list(direction)
        norm = np.linalg.norm(raw_dir)
        self.direction   = [v / norm for v in raw_dir] if norm > 0 else [0, 0, -1]
        self.beam_radius = beam_radius
        self.source_type = source_type
        self.energy_mono = energy_mono
        self.energy_spectrum = energy_spectrum or self._default_spectrum(source_type)
        self.intensity   = intensity

    @staticmethod
    def _default_spectrum(source_type: str) -> Dict:
        """内置能谱（IAEA 参考谱近似）"""
        if source_type == "epithermal":
            # 超热中子谱（0.5 eV – 10 keV 主要成分）
            return {
                "energies": [0.5e-6, 1e-6, 10e-6, 100e-6, 1e-3, 0.01, 0.1, 1.0, 10.0],  # MeV
                "weights":  [0.00,  0.05,  0.15,   0.25,   0.25, 0.15, 0.10, 0.04, 0.01]
            }
        elif source_type == "thermal":
            return {
                "energies": [0.025e-6, 0.05e-6, 0.1e-6, 0.2e-6],  # MeV
                "weights":  [0.3, 0.4, 0.2, 0.1]
            }
        else:
            return {"energies": [1e-3], "weights": [1.0]}

    def to_dict(self) -> Dict:
        return {
            "position":    self.position,
            "direction":   self.direction,
            "beam_radius": self.beam_radius,
            "source_type": self.source_type,
            "energy_mono": self.energy_mono,
            "energy_spectrum": self.energy_spectrum,
            "intensity":   self.intensity
        }


class PhantomConfig:
    """体模（患者/标准人体模）配置"""

    def __init__(self,
                 center: Tuple[float, float, float] = (0.0, 0.0, 0.0),
                 rotation_deg: Tuple[float, float, float] = (0.0, 0.0, 0.0),
                 phantom_type: str = "AM",
                 height_cm: float = 170.0,
                 weight_kg: float = 70.0,
                 tumor_position: Tuple[float, float, float] = (0.0, 0.0, 10.0),
                 tumor_radius: float = 2.0):
        """
        Parameters
        ----------
        center        : 体模中心坐标 (cm)
        rotation_deg  : 绕 X/Y/Z 轴旋转角度 (度)
        phantom_type  : 'AM' 成年男性 | 'AF' 成年女性 | 'custom'
        height_cm     : 身高 (cm)
        weight_kg     : 体重 (kg)
        tumor_position: 肿瘤中心坐标 (cm)（相对体模中心）
        tumor_radius  : 肿瘤等效球半径 (cm)
        """
        self.center         = list(center)
        self.rotation_deg   = list(rotation_deg)
        self.phantom_type   = phantom_type
        self.height_cm      = height_cm
        self.weight_kg      = weight_kg
        self.tumor_position = list(tumor_position)
        self.tumor_radius   = tumor_radius

    def get_rotation_matrix(self) -> np.ndarray:
        rx, ry, rz = [np.deg2rad(a) for a in self.rotation_deg]
        Rx = np.array([[1,0,0],[0,np.cos(rx),-np.sin(rx)],[0,np.sin(rx),np.cos(rx)]])
        Ry = np.array([[np.cos(ry),0,np.sin(ry)],[0,1,0],[-np.sin(ry),0,np.cos(ry)]])
        Rz = np.array([[np.cos(rz),-np.sin(rz),0],[np.sin(rz),np.cos(rz),0],[0,0,1]])
        return Rz @ Ry @ Rx

    def to_dict(self) -> Dict:
        return {
            "center":         self.center,
            "rotation_deg":   self.rotation_deg,
            "phantom_type":   self.phantom_type,
            "height_cm":      self.height_cm,
            "weight_kg":      self.weight_kg,
            "tumor_position": self.tumor_position,
            "tumor_radius":   self.tumor_radius
        }


class DoseComponentCalculator:
    """
    BNCT 剂量组分解析计算器

    使用基于解析模型的简化剂量估算，适用于快速参数研究。
    精确计算需 MCNP/OpenMC 蒙特卡洛模拟。
    """

    # 人体软组织元素组成（质量分数）
    SOFT_TISSUE_COMPOSITION = {
        "H":  0.101,
        "C":  0.111,
        "N":  0.026,
        "O":  0.762
    }

    # 软组织密度 (g/cm³)
    TISSUE_DENSITY = 1.04

    def __init__(self,
                 source_config: SourceConfig,
                 phantom_config: PhantomConfig,
                 cbe_rbe: Optional[Dict] = None,
                 boron_conc: Optional[Dict] = None):
        self.source  = source_config
        self.phantom = phantom_config
        self.cbe_rbe = cbe_rbe or DEFAULT_CBE_RBE
        self.boron_conc = boron_conc or DEFAULT_BORON_CONC

    # ─────────────────────────────────────────────────
    # 几何辅助
    # ─────────────────────────────────────────────────

    def _source_to_phantom_distance(self) -> float:
        """源中心到体模中心的距离 (cm)"""
        s = np.array(self.source.position)
        p = np.array(self.phantom.center)
        return float(np.linalg.norm(s - p))

    def _beam_axis_offset(self) -> float:
        """
        束流轴到肿瘤中心的横向偏移（用于估算通量衰减）
        """
        s = np.array(self.source.position)
        d = np.array(self.source.direction)
        t = np.array(self.phantom.center) + np.array(self.phantom.tumor_position)
        # 点到直线距离
        v = t - s
        proj = np.dot(v, d)
        perp = v - proj * d
        return float(np.linalg.norm(perp))

    # ─────────────────────────────────────────────────
    # 中子通量估算（简化解析模型）
    # ─────────────────────────────────────────────────

    def _thermal_flux_at_depth(self, depth_cm: float) -> float:
        """
        超热中子束经组织慢化后在深度 d 处的热中子通量估算
        模型：Φ_th(d) = Φ₀ × (d/λ_s) × exp(-d/λ_th)
        λ_s  = 慢化长度 ≈ 6.0 cm（水/软组织中超热中子）
        λ_th = 热中子扩散长度 ≈ 3.0 cm（水）
        """
        phi0 = self.source.intensity
        R    = self.source.beam_radius
        dist = self._source_to_phantom_distance()

        # 几何因子（圆形准直束，近似为 1/r² 衰减）
        area_factor = np.pi * R**2 / max(1.0, dist**2)

        lambda_s  = 6.0   # cm，慢化长度（水）
        lambda_th = 3.0   # cm，热扩散长度

        build_up = (depth_cm / lambda_s)
        decay    = np.exp(-depth_cm / lambda_th)
        phi_th   = phi0 * area_factor * build_up * decay
        return max(phi_th, 0.0)

    def _epithermal_flux_at_depth(self, depth_cm: float) -> float:
        """超热中子通量（指数衰减模型）"""
        phi0 = self.source.intensity
        R    = self.source.beam_radius
        dist = self._source_to_phantom_distance()
        area_factor = np.pi * R**2 / max(1.0, dist**2)
        # 超热中子在软组织中自由程约 10 cm
        lambda_epi = 10.0
        return phi0 * area_factor * np.exp(-depth_cm / lambda_epi)

    def _fast_flux_at_depth(self, depth_cm: float) -> float:
        """快中子通量（衰减更快）"""
        phi0 = self.source.intensity
        R    = self.source.beam_radius
        dist = self._source_to_phantom_distance()
        area_factor = np.pi * R**2 / max(1.0, dist**2)
        lambda_fast = 7.0
        return phi0 * area_factor * np.exp(-depth_cm / lambda_fast)

    # ─────────────────────────────────────────────────
    # 四个剂量组分
    # ─────────────────────────────────────────────────

    def _calc_boron_dose(self, depth_cm: float, tissue_type: str) -> float:
        """
        硼中子俘获剂量 D_B (cGy)
        D_B = Φ_th × N_B10 × σ_B10 × Q_B10 × t × 1/ρ × 单位转换
        """
        conc_ppm = self.boron_conc.get(tissue_type,
                   self.boron_conc.get("normal_tissue", 18.0))

        # B-10 原子密度 (atoms/cm³)
        conc_g_per_g = conc_ppm * 1e-6
        n_b10 = (conc_g_per_g * self.TISSUE_DENSITY * AVOGADRO
                 * B10_ABUNDANCE / B10_MASS)

        phi_th = self._thermal_flux_at_depth(depth_cm)
        sigma  = SIGMA_B10_THERMAL * 1e-24   # barn → cm²

        # 反应率 × Q → MeV/cm³/s
        reaction_rate = phi_th * n_b10 * sigma
        dose_mev_per_g_s = reaction_rate * Q_B10 / self.TISSUE_DENSITY

        # 换算 MeV/g/s → Gy/s → cGy/s（1 Gy = 6.242×10⁹ MeV/g）
        dose_cgy_per_s = dose_mev_per_g_s / 6.242e9 * 100

        # 治疗时间 30 min
        irr_time_s = 30 * 60
        return dose_cgy_per_s * irr_time_s

    def _calc_nitrogen_dose(self, depth_cm: float) -> float:
        """
        氮俘获剂量 D_N (cGy)  ← ¹⁴N(n,p) 反应
        """
        n_frac = self.SOFT_TISSUE_COMPOSITION.get("N", 0.026)
        # 氮原子密度
        n_n14 = (n_frac * self.TISSUE_DENSITY * AVOGADRO
                 / 14.003)

        phi_th = self._thermal_flux_at_depth(depth_cm)
        sigma  = SIGMA_N14_THERMAL * 1e-24

        reaction_rate = phi_th * n_n14 * sigma
        dose_mev_per_g_s = reaction_rate * Q_N14 / self.TISSUE_DENSITY
        dose_cgy_per_s   = dose_mev_per_g_s / 6.242e9 * 100

        return dose_cgy_per_s * 30 * 60

    def _calc_hydrogen_dose(self, depth_cm: float) -> float:
        """
        氢反冲质子剂量 D_H (cGy)  ← ¹H(n,p) 弹性散射

        正确物理公式（与硼剂量一致）：
          D_H = Φ_epi × N_H × σ_H_elastic × ⟨E_recoil⟩ × t / ρ × 单位转换

        参数选取（超热中子 ~1 keV 平均）：
          σ_H_elastic ≈ 4.5 barn（超热范围积分平均，ENDF/B-VIII.0）
          ⟨E_recoil⟩  ≈ E_n/2 ≈ 0.5 keV = 5e-4 MeV（等质量全转移平均）
        """
        h_frac = self.SOFT_TISSUE_COMPOSITION.get("H", 0.101)
        n_h    = h_frac * self.TISSUE_DENSITY * AVOGADRO / 1.008   # atoms/cm³

        phi_epi = self._epithermal_flux_at_depth(depth_cm)

        sigma_H_elastic = 4.5e-24          # cm²，超热平均弹性截面
        E_recoil_avg_MeV = 5.0e-4          # MeV，0.5 keV 平均反冲

        reaction_rate    = phi_epi * n_h * sigma_H_elastic
        dose_mev_per_g_s = reaction_rate * E_recoil_avg_MeV / self.TISSUE_DENSITY
        dose_cgy_per_s   = dose_mev_per_g_s / 6.242e9 * 100   # 1 Gy = 6.242e9 MeV/g

        return dose_cgy_per_s * 30 * 60

    def _calc_gamma_dose(self, depth_cm: float) -> float:
        """
        伽马剂量 D_γ (cGy)
        来源：①束流伴生伽马；②¹H(n,γ) 俘获；③体模散射

        公式：
          D_γ(d) = Φ_epi × k_γ × exp(-μ_eff × d) × t
          k_γ  ≈ 3.5e-15 Gy·cm²（超热束流 γ/n 光子剂量转换因子，IAEA TD-1683）
          μ_eff ≈ 0.08 /cm（软组织有效衰减系数）
        """
        phi_epi = self._epithermal_flux_at_depth(depth_cm)

        # 超热 BNCT 束流中，伽马剂量换算因子（per n/cm²）
        k_gamma  = 3.5e-15   # Gy·cm²（fluence-to-dose，表面参考值）
        mu_eff   = 0.08      # /cm
        # 注：k_gamma 已含衰减修正，这里再做深度修正
        dose_gy_per_s = phi_epi * k_gamma * np.exp(-mu_eff * depth_cm)
        return dose_gy_per_s * 30 * 60 * 100   # → cGy

    # ─────────────────────────────────────────────────
    # 主计算接口
    # ─────────────────────────────────────────────────

    def calculate_at_depth(self, depth_cm: float,
                            tissue_type: str = "tumor") -> Dict:
        """
        计算单点剂量组分

        Parameters
        ----------
        depth_cm    : 从体表到目标点的深度 (cm)
        tissue_type : 'tumor' | 'normal_tissue' | 'skin'

        Returns
        -------
        dict with keys: boron_dose, nitrogen_dose, hydrogen_dose, gamma_dose,
                        weighted_boron, weighted_nitrogen, weighted_hydrogen,
                        weighted_gamma, total_weighted_dose, tissue_type,
                        depth_cm, cbe_rbe_used
        """
        factors = self.cbe_rbe.get(tissue_type, self.cbe_rbe["normal_tissue"])

        d_B = self._calc_boron_dose(depth_cm, tissue_type)
        d_N = self._calc_nitrogen_dose(depth_cm)
        d_H = self._calc_hydrogen_dose(depth_cm)
        d_g = self._calc_gamma_dose(depth_cm)

        wd_B = factors["boron_cbe"]    * d_B
        wd_N = factors["nitrogen_rbe"] * d_N
        wd_H = factors["hydrogen_rbe"] * d_H
        wd_g = factors["gamma_rbe"]    * d_g
        total = wd_B + wd_N + wd_H + wd_g

        return {
            "depth_cm":         round(depth_cm, 3),
            "tissue_type":      tissue_type,
            "boron_dose_cgy":   round(d_B, 4),
            "nitrogen_dose_cgy":round(d_N, 4),
            "hydrogen_dose_cgy":round(d_H, 4),
            "gamma_dose_cgy":   round(d_g, 4),
            "weighted_boron_cgy":   round(wd_B, 4),
            "weighted_nitrogen_cgy":round(wd_N, 4),
            "weighted_hydrogen_cgy":round(wd_H, 4),
            "weighted_gamma_cgy":   round(wd_g, 4),
            "total_weighted_cgy":   round(total, 4),
            "cbe_rbe_used": factors,
            "fractions": {
                "boron":    round(wd_B / total * 100, 1) if total > 0 else 0,
                "nitrogen": round(wd_N / total * 100, 1) if total > 0 else 0,
                "hydrogen": round(wd_H / total * 100, 1) if total > 0 else 0,
                "gamma":    round(wd_g / total * 100, 1) if total > 0 else 0
            }
        }

    def calculate_depth_profile(self,
                                 depths: Optional[List[float]] = None,
                                 tissue_type: str = "tumor") -> List[Dict]:
        """
        计算深度-剂量曲线（多个深度点）

        Returns
        -------
        list of dicts（每个深度一条记录）
        """
        if depths is None:
            depths = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20]
        return [self.calculate_at_depth(d, tissue_type) for d in depths]

    def calculate_all_tissues(self, depth_cm: float) -> Dict:
        """
        同时计算肿瘤、正常组织、皮肤的剂量
        """
        return {
            "depth_cm": depth_cm,
            "tumor":         self.calculate_at_depth(depth_cm, "tumor"),
            "normal_tissue": self.calculate_at_depth(depth_cm, "normal_tissue"),
            "skin":          self.calculate_at_depth(depth_cm, "skin")
        }

    def full_report(self, tumor_depth: float = 7.0) -> Dict:
        """
        生成完整剂量报告

        Parameters
        ----------
        tumor_depth : 肿瘤中心深度 (cm)

        Returns
        -------
        包含配置、剂量结果、深度曲线的完整报告
        """
        profile = self.calculate_depth_profile(tissue_type="tumor")
        tumor_point = self.calculate_all_tissues(tumor_depth)

        # 皮肤（表面，深度 0.5 cm）
        skin_point = self.calculate_at_depth(0.5, "skin")
        # 对侧正常组织（肿瘤对面，假设深 15 cm）
        normal_point = self.calculate_at_depth(15.0, "normal_tissue")

        return {
            "source_config":  self.source.to_dict(),
            "phantom_config": self.phantom.to_dict(),
            "cbe_rbe":        self.cbe_rbe,
            "boron_conc_ppm": self.boron_conc,
            "tumor_depth_cm": tumor_depth,
            "tumor_point":    tumor_point["tumor"],
            "skin_point":     skin_point,
            "normal_tissue_point": normal_point,
            "depth_profile":  profile,
            "summary": {
                "peak_total_dose_cgy": max(p["total_weighted_cgy"] for p in profile),
                "tumor_total_dose_cgy": tumor_point["tumor"]["total_weighted_cgy"],
                "skin_total_dose_cgy":  skin_point["total_weighted_cgy"],
                "therapeutic_ratio": (
                    tumor_point["tumor"]["total_weighted_cgy"]
                    / max(skin_point["total_weighted_cgy"], 1e-9)
                )
            }
        }


def run_calculator(params: Dict) -> Dict:
    """
    JSON 接口入口（供 index.js 调用）

    params 字段：
      source_position   : [x, y, z] (cm)
      source_direction  : [ux, uy, uz]
      beam_radius       : float (cm)
      source_type       : str
      energy_mono       : float | null
      energy_spectrum   : {energies, weights} | null
      intensity         : float (n/cm²/s)
      phantom_center    : [x, y, z]
      phantom_rotation  : [rx, ry, rz] (deg)
      phantom_type      : 'AM' | 'AF'
      height_cm         : float
      weight_kg         : float
      tumor_position    : [x, y, z]
      tumor_radius      : float
      tumor_depth_cm    : float
      cbe_rbe           : dict | null（null 使用默认值）
      boron_conc        : dict | null（null 使用默认值）
    """
    src = SourceConfig(
        position        = params.get("source_position",  [0, 0, 100]),
        direction       = params.get("source_direction", [0, 0, -1]),
        beam_radius     = params.get("beam_radius",      5.0),
        source_type     = params.get("source_type",      "epithermal"),
        energy_mono     = params.get("energy_mono",      None),
        energy_spectrum = params.get("energy_spectrum",  None),
        intensity       = params.get("intensity",        1e12)
    )
    phantom = PhantomConfig(
        center          = params.get("phantom_center",   [0, 0, 0]),
        rotation_deg    = params.get("phantom_rotation", [0, 0, 0]),
        phantom_type    = params.get("phantom_type",     "AM"),
        height_cm       = params.get("height_cm",        170.0),
        weight_kg       = params.get("weight_kg",        70.0),
        tumor_position  = params.get("tumor_position",   [0, 0, 7]),
        tumor_radius    = params.get("tumor_radius",     2.0)
    )
    cbe_rbe    = params.get("cbe_rbe",    None)
    boron_conc = params.get("boron_conc", None)

    calc   = DoseComponentCalculator(src, phantom, cbe_rbe, boron_conc)
    report = calc.full_report(tumor_depth=params.get("tumor_depth_cm", 7.0))
    return {"success": True, "result": report}


if __name__ == "__main__":
    import sys, json as _json

    if len(sys.argv) > 1:
        params = _json.loads(sys.argv[1])
    else:
        params = {}

    out = run_calculator(params)
    print(_json.dumps(out, ensure_ascii=False, indent=2))
