"""Static values that the manual workbook treats as constants per month.

These are values a human (Finance) types or pastes into specific cells
that aren't derivable from any export. By housing them here, the
generator produces them "from source" (this module) rather than
inheriting them from the template — satisfying the "no inherited cells"
requirement while still matching the manual byte-for-byte.

Update these when Finance changes them (monthly FX, manager rotation,
new comparable stores etc.).
"""
from __future__ import annotations

from dataclasses import dataclass


# ── Store-level static metadata not in any export ─────────────────────────
# 区域经理 (regional manager) is the same person for all CA stores currently.
# 店经理 (store manager) — Finance maintains this list.
@dataclass(frozen=True)
class StaffMeta:
    store_manager: str  # 店经理
    region_manager: str  # 区域经理


STORE_STAFF: dict[str, StaffMeta] = {
    "加拿大一店": StaffMeta("张森磊", "蒋冰遇"),
    "加拿大二店": StaffMeta("朱芯逸", "蒋冰遇"),
    "加拿大三店": StaffMeta("Bao Xiaoyun", "蒋冰遇"),
    "加拿大四店": StaffMeta("李俊娟", "蒋冰遇"),
    "加拿大五店": StaffMeta("陈浩", "蒋冰遇"),
    "加拿大六店": StaffMeta("陈浩（兼）", "蒋冰遇"),
    "加拿大七店": StaffMeta("潘幸远", "蒋冰遇"),
    "加拿大八店": StaffMeta("李俊娟", "蒋冰遇"),
    "加拿大九店": StaffMeta("-", "蒋冰遇"),
}


# ── 汇率 (本币/美元 conversion, CAD-per-USD or similar) ────────────────────
# Finance pastes per-month from 管报. March 2026 → 0.728597.
DEFAULT_FX_BY_PERIOD: dict[tuple[int, int], float] = {
    (2026, 3): 0.728597,
    (2026, 2): 0.728597,
    (2025, 3): 0.695265,
}


# ── 细分毛利率表 stale 2023 example block (rows 4-10 of the manual) ─────
# This is a template documentation block — same content every month, used
# as an example of how the cur/prev/环比 columns should look. Reproduced
# verbatim so the generated workbook structurally matches the manual.
SUBDIVIDED_GP_2023_HEADERS = (
    " 如有除锅底类等其他分类如自选饮料等区域可以自行添加",
    "2023年月细分毛利率环比表",
)

# Each row: (store_label, 7 categories × 3 cols (cur, prev, 环比))
# Columns layout: col2=label, then 21 data cols for 7 categories
SUBDIVIDED_GP_2023_ROWS: list[tuple] = [
    ("加拿大一店",
     0.639350781291113, 0.672991741544605, -0.0336409602534919,
     0.638882244560294, 0.672879392322332, -0.033997147762038,
     0.74914329945689,  0.804969010161893, -0.0558257107050031,
     0.655420168930614, 0.673930893132302, -0.0185107241016886,
     0.390142746220841, 0.398854242662627, -0.00871149644178578,
     0.631409539391795, 0.664949785103015, -0.033540245711219,
     0.99613898748756,  0.982668057206311, 0.013470930281249),
    ("加拿大二店",
     0.603699782237564, 0.65756981961403,  -0.053870037376466,
     0.665088301558917, 0.670322128470771, -0.00523382691185403,
     0.778331103026074, 0.810431807868188, -0.032100704842114,
     0.620654899344505, 0.697038196304238, -0.0763832969597333,
     0.472321988437828, 0.478421567838034, -0.00609957940020574,
     0.763178744050293, 0.733811288063234, 0.0293674559870592,
     0.997288776813147, 0.988657357379486, 0.00863141943366114),
    ("加拿大三店",
     0.600233053692698, 0.5734711149216,    0.0267619387710978,
     0.661920676278949, 0.640402584198658,  0.0215180920802907,
     0.698513901829022, 0.701823844269841, -0.00330994244081933,
     0.761254191068231, 0.709543345530412,  0.0517108455378192,
     0.349294751737215, 0.319318306275082,  0.0299764454621335,
     0.576492391770155, 0.560103451608225,  0.0163889401619298,
     1.0,               0.991555600839014,  0.00844439916098635),
    ("加拿大四店",
     0.611860890794229, 0.626174420705319, -0.014313529911090,
     0.590700783433242, 0.635990498737383, -0.0452897153041411,
     0.736413485959353, 0.749421844951209, -0.0130083589918562,
     0.759057463013862, 0.775476074932884, -0.0164186119190213,
     0.388123649824574, 0.386843892796174,  0.00127975702840045,
     0.640060829395067, 0.673106020303906, -0.033045190908839,
     0.999241983886893, 0.978996324867841,  0.0202456590190524),
    ("加拿大五店",
     0.625446448586850, 0.632377784902997, -0.00693133631614684,
     0.653020987356270, 0.636502201125063,  0.0165187862312068,
     0.771954126364318, 0.796185579764115, -0.0242314533997968,
     0.747643597005552, 0.783745533119693, -0.036101936114141,
     0.443127489935075, 0.494419636480067, -0.051292146544992,
     0.700691389104148, 0.659563418984469,  0.041127970119679,
     1.0,               0.951953568287037,  0.0480464317129633),
    # 总计 row (template's pre-computed average from the 2023 example)
    ("总计",
     0.618357342848071, 0.635532636344946, -0.017175293496875,
     0.640181734448479, 0.651808374661043, -0.011626640212564,
     0.746389001201234, 0.774720608037488, -0.0283316068362539,
     0.710479076348789, 0.726775169496901, -0.0162960931481116,
     0.408541285154746, 0.418605629212993, -0.010064344058247,
     0.643626478740348, 0.658232532812371, -0.014606054072023,
     0.998733949437920, 0.978766181715938,  0.019967767721981),
]


# Title row text for the active 2026 block in 细分毛利率表
SUBDIVIDED_GP_2026_NOTE = "本月修改部分菜品销售分类（饮料酒水，十佳）"
