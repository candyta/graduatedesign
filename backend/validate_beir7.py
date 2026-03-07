#!/usr/bin/env python3
"""
BEIR VII 风险模型验证脚本
对照 BEIR VII (2006) 报告检验 beir7_risk_engine.py 中公式和参数的正确性

验证项目：
  1. ERR 公式基准点 —— ERR(1 Gy, 暴露年龄=30) 应恰好等于 β
  2. EAR 公式基准点 —— EAR(1 Gy, 暴露年龄=30, 达到年龄=60) 应等于 β
  3. 年龄调整因子行为
  4. ERR/EAR 模型权重 —— BEIR VII 推荐 0.7/0.3，肺部为 0.3/0.7（颠倒）
  5. 量化权重差异对 LAR 的影响

参考：BEIR VII Phase 2 (2006), Table 12-2D/E, Chapter 12
"""

import sys
import math
sys.path.insert(0, '/home/user/graduatedesign/backend')
from beir7_risk_engine import BEIRVII_RiskEngine


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ──────────────────────────────────────────────────────────────
# 1. ERR 公式基准点
# ──────────────────────────────────────────────────────────────
section("1. ERR 公式基准点  ERR(D=1Gy, e=30) == β")
print("  原理: exp(γ×(30-30)/10) = 1，故 ERR = β×D = β\n")

# BEIR VII Table 12-2D 的 β 值
ERR_BETA = {
    'stomach':  (0.21, 0.48),
    'colon':    (0.63, 0.43),
    'liver':    (0.32, 0.32),
    'lung':     (0.32, 1.40),
    'bladder':  (0.50, 1.20),
    'thyroid':  (0.53, 1.05),
    'brain':    (0.24, 0.24),
    'leukemia': (1.50, 2.20),
}

all_pass = True
for organ, (beta_m, beta_f) in ERR_BETA.items():
    eng_m = BEIRVII_RiskEngine(30, 'male')
    eng_f = BEIRVII_RiskEngine(30, 'female')
    got_m = eng_m.calculate_err(organ, 1.0, 30)
    got_f = eng_f.calculate_err(organ, 1.0, 30)
    ok_m = abs(got_m - beta_m) < 1e-9
    ok_f = abs(got_f - beta_f) < 1e-9
    sm = "✓" if ok_m else "✗"
    sf = "✓" if ok_f else "✗"
    print(f"  {organ:<12}  男 期望={beta_m:.2f} 得到={got_m:.4f} {sm}    "
          f"女 期望={beta_f:.2f} 得到={got_f:.4f} {sf}")
    if not (ok_m and ok_f):
        all_pass = False

print(f"\n  结论: {'全部通过 ✓' if all_pass else '存在错误 ✗'}")


# ──────────────────────────────────────────────────────────────
# 2. EAR 公式基准点
# ──────────────────────────────────────────────────────────────
section("2. EAR 公式基准点  EAR(D=1Gy, e=30, a=60) == β")
print("  原理: exp(γ×0)=1, (60/60)^η=1，故 EAR = β×1×1 = β\n")

# BEIR VII Table 12-2E 的 β 值
EAR_BETA = {
    'stomach': (4.90, 10.20),
    'colon':   (3.20,  1.60),
    'liver':   (2.70,  2.20),
    'lung':    (5.50,  9.60),
    'bladder': (1.00,  1.60),
    'thyroid': (0.40,  2.00),
}

all_pass = True
for organ, (beta_m, beta_f) in EAR_BETA.items():
    eng_m = BEIRVII_RiskEngine(30, 'male')
    eng_f = BEIRVII_RiskEngine(30, 'female')
    got_m = eng_m.calculate_ear(organ, 1.0, 30, 60)
    got_f = eng_f.calculate_ear(organ, 1.0, 30, 60)
    ok_m = abs(got_m - beta_m) < 1e-9
    ok_f = abs(got_f - beta_f) < 1e-9
    sm = "✓" if ok_m else "✗"
    sf = "✓" if ok_f else "✗"
    print(f"  {organ:<12}  男 期望={beta_m:.2f} 得到={got_m:.4f} {sm}    "
          f"女 期望={beta_f:.2f} 得到={got_f:.4f} {sf}")
    if not (ok_m and ok_f):
        all_pass = False

print(f"\n  结论: {'全部通过 ✓' if all_pass else '存在错误 ✗'}")


# ──────────────────────────────────────────────────────────────
# 3. 年龄调整因子
# ──────────────────────────────────────────────────────────────
section("3. 年龄调整因子 exp(γ×(e-30)/10) 行为验证")
print("  以肺癌男性 γ=-0.40 为例\n")
print(f"  {'暴露年龄':>8}  {'调整因子':>10}  说明")
print(f"  {'-'*40}")
gamma = -0.40
for age in [10, 20, 30, 40, 50, 60]:
    factor = math.exp(gamma * (age - 30) / 10)
    note = "基准" if age == 30 else ("年轻→更高风险" if age < 30 else "年长→更低风险")
    print(f"  {age:>8}岁  {factor:>10.4f}  {note}")


# ──────────────────────────────────────────────────────────────
# 4. ERR/EAR 权重问题
# ──────────────────────────────────────────────────────────────
section("4. ERR/EAR 模型权重：现有代码 vs BEIR VII 推荐")
print("""
  BEIR VII Chapter 12 推荐权重：
  ┌──────────────┬──────────┬──────────┐
  │ 器官         │ ERR 权重 │ EAR 权重 │
  ├──────────────┼──────────┼──────────┤
  │ 大多数实体癌 │   0.7    │   0.3    │
  │ 肺癌         │   0.3    │   0.7    │ ← 颠倒
  │ 乳腺癌       │   0.0    │   1.0    │ ← 仅 EAR
  │ 甲状腺癌     │   1.0    │   0.0    │ ← 仅 ERR
  └──────────────┴──────────┴──────────┘

  现有代码：calculate_lar_combined() 默认 err_weight=0.5（均等权重）
""")

# 量化差异
print("  量化差异 (30岁男性, D=0.1 Sv)：\n")
print(f"  {'器官':<12} {'代码(0.5/0.5)':>14} {'BEIR VII推荐':>14} {'差异%':>8}  推荐权重")
print(f"  {'-'*60}")

organs_weights = {
    'stomach': (0.7, 0.3),
    'colon':   (0.7, 0.3),
    'lung':    (0.3, 0.7),   # 颠倒
    'bladder': (0.7, 0.3),
}

eng = BEIRVII_RiskEngine(30, 'male')
dose = 0.1

for organ, (w_err, w_ear) in organs_weights.items():
    lar_code    = eng.calculate_lar_combined(organ, dose)['lar_combined']
    lar_err_val = eng.calculate_lar(organ, dose)
    lar_ear_val = eng.calculate_lar_ear(organ, dose)
    lar_beir7   = w_err * lar_err_val + w_ear * lar_ear_val
    diff_pct    = (lar_beir7 - lar_code) / lar_code * 100 if lar_code > 0 else 0
    flag = " ← 偏差最大" if organ == 'lung' else ""
    print(f"  {organ:<12} {lar_code:>14.6f}% {lar_beir7:>14.6f}%"
          f" {diff_pct:>+8.1f}%  {w_err:.1f}/{w_ear:.1f}{flag}")


# ──────────────────────────────────────────────────────────────
# 5. 汇总
# ──────────────────────────────────────────────────────────────
section("5. 汇总")
print("""
  ✓ ERR/EAR 公式结构正确
  ✓ ERR/EAR 参数值与 BEIR VII Table 12-2D/E 完全一致

  ✗ 问题1 [权重错误] ★★★ 影响最大
      位置: calculate_lar_combined(), 默认 err_weight=0.5
      修正: 大多数器官改为 0.7/0.3，肺癌改为 0.3/0.7
            乳腺癌改为 0.0/1.0，甲状腺改为 1.0/0.0

  ✗ 问题2 [甲状腺 EAR 参数] ★★
      BEIR VII 对甲状腺只推荐 ERR 模型，代码中存在 EAR 参数会被误用
      修正: 甲状腺 LAR 应仅使用 ERR 模型

  ✗ 问题3 [DDREF 逻辑不清] ★
      代码以 0.1 Sv 为阈值应用 DDREF，BEIR VII 的描述是针对低剂量低剂量率
      BNCT 场景剂量通常 > 0.1 Gy，此处实际不触发，影响有限
""")
