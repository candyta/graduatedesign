#!/usr/bin/env python3
"""
生成 BNCT 四组分剂量随深度变化曲线（图2-X）
条件：肿瘤组织，硼浓度60 ppm，超热中子注量率1×10¹² n·cm⁻²·s⁻¹，照射时间30 min
"""

import sys
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib import font_manager

# 注册文泉驿正黑（系统内置 CJK 字体）
_CJK_FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
if os.path.exists(_CJK_FONT):
    font_manager.fontManager.addfont(_CJK_FONT)
    plt.rcParams["font.family"] = ["WenQuanYi Zen Hei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# 允许从任意目录调用
sys.path.insert(0, os.path.dirname(__file__))
from dose_component_calculator import (
    SourceConfig, PhantomConfig, DoseComponentCalculator, DEFAULT_CBE_RBE
)

# ─── 参数配置 ────────────────────────────────────────────────────────────────
INTENSITY     = 1e12          # n·cm⁻²·s⁻¹
BORON_CONC    = {"tumor": 60.0, "normal_tissue": 18.0, "skin": 25.0}
TUMOR_DEPTH   = 7.0           # cm
DEPTHS        = np.linspace(0.0, 20.0, 400)   # 0–20 cm，400点

# ─── 构建计算器 ──────────────────────────────────────────────────────────────
source = SourceConfig(
    position    = (0.0, 0.0, 100.0),
    direction   = (0.0, 0.0, -1.0),
    beam_radius = 5.0,
    source_type = "epithermal",
    intensity   = INTENSITY,
)
phantom = PhantomConfig(
    center         = (0.0, 0.0, 0.0),
    tumor_position = (0.0, 0.0, TUMOR_DEPTH),
    tumor_radius   = 2.0,
)
calc = DoseComponentCalculator(source, phantom,
                               cbe_rbe=DEFAULT_CBE_RBE,
                               boron_conc=BORON_CONC)

# ─── 逐点计算 ────────────────────────────────────────────────────────────────
d_B   = np.array([calc._calc_boron_dose(d, "tumor") for d in DEPTHS])
d_N   = np.array([calc._calc_nitrogen_dose(d)        for d in DEPTHS])
d_H   = np.array([calc._calc_hydrogen_dose(d)        for d in DEPTHS])
d_g   = np.array([calc._calc_gamma_dose(d)           for d in DEPTHS])

factors = DEFAULT_CBE_RBE["tumor"]
total = (factors["boron_cbe"]    * d_B +
         factors["nitrogen_rbe"] * d_N +
         factors["hydrogen_rbe"] * d_H +
         factors["gamma_rbe"]    * d_g)

# cGy → Gy
d_B_Gy   = d_B   / 100
d_N_Gy   = d_N   / 100
d_H_Gy   = d_H   / 100
d_g_Gy   = d_g   / 100
total_Gy = total  / 100

# ─── 绘图 ────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(8, 5.5))

# 论文要求配色与线型
ax.plot(DEPTHS, total_Gy, color="#1f77b4", lw=2.2, ls="-",
        label=r"生物等效总剂量 $D_\mathrm{total}$")
ax.plot(DEPTHS, d_B_Gy,   color="#d62728", lw=1.6, ls="--",
        label=r"$^{10}$B 俘获剂量 $D_B$")
ax.plot(DEPTHS, d_N_Gy,   color="#2ca02c", lw=1.6, ls="--",
        label=r"$^{14}$N 俘获剂量 $D_N$")
ax.plot(DEPTHS, d_H_Gy,   color="#ff7f0e", lw=1.6, ls="--",
        label=r"$^{1}$H 反冲剂量 $D_H$")
ax.plot(DEPTHS, d_g_Gy,   color="#9467bd", lw=1.6, ls="--",
        label=r"光子剂量 $D_\gamma$")

# 肿瘤靶区标注线
ax.axvline(x=TUMOR_DEPTH, color="#d62728", lw=1.2, ls=":",
           label=f"肿瘤靶区深度（{TUMOR_DEPTH} cm）")

ax.set_xlabel("组织深度 (cm)", fontsize=12)
ax.set_ylabel("剂量 (Gy)", fontsize=12)
ax.set_xlim(0, 20)
ax.set_ylim(bottom=0)
ax.xaxis.set_minor_locator(ticker.MultipleLocator(1))
ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(4))
ax.tick_params(axis="both", which="both", direction="in")
ax.grid(True, which="major", linestyle="--", alpha=0.4)
ax.legend(fontsize=9, loc="upper right", framealpha=0.85)

caption = (
    "图2-X  本系统基于解析模型计算的BNCT四组分剂量随组织深度分布曲线\n"
    "（肿瘤组织，硼浓度60 ppm，超热中子注量率1×10¹² n·cm⁻²·s⁻¹，照射时间30 min）"
)
fig.text(0.5, -0.04, caption, ha="center", va="top", fontsize=8.5,
         wrap=True, color="#333333")

plt.tight_layout()

out_path = os.path.join(os.path.dirname(__file__), "dose_curves_figure.png")
fig.savefig(out_path, dpi=200, bbox_inches="tight")
print(f"已保存：{out_path}")
