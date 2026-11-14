"""점도 구간 설정 — 구간의 이름·예시 제형·숫자 범위는 이 파일에서만 고칩니다.

범위(cP)는 임시값입니다. 각 구간은 min_cp 이상 max_cp 미만이라 경계값은 위쪽 구간에 들어갑니다.
저장본에는 key 만 들어가므로 key 는 바꾸지 않습니다. 표시명·예시·범위는 바꿔도 됩니다.
시뮬레이션 탭과 함께 쓰게 되면 src/common 으로 옮깁니다.
"""

from __future__ import annotations

import math

VISCOSITY_BANDS = [
    {"key": "very_thin", "label": "매우 묽음", "example": "토너·미스트", "min_cp": 0, "max_cp": 100},
    {"key": "thin", "label": "묽음", "example": "에센스", "min_cp": 100, "max_cp": 1000},
    {"key": "medium", "label": "중간", "example": "세럼·앰플", "min_cp": 1000, "max_cp": 10000},
    {"key": "thick", "label": "되직함", "example": "로션·에멀전", "min_cp": 10000, "max_cp": 30000},
    {"key": "very_thick", "label": "매우 되직함", "example": "크림", "min_cp": 30000, "max_cp": None},
]
VISCOSITY_BAND_KEYS = [band["key"] for band in VISCOSITY_BANDS]


def band_for_cp(cp) -> str:
    """점도(cP) → 구간 key. 숫자가 아니거나 음수이면 ValueError."""
    if isinstance(cp, bool) or not isinstance(cp, (int, float)) or not math.isfinite(cp) or cp < 0:
        raise ValueError("점도는 0 이상의 숫자여야 합니다.")
    for band in VISCOSITY_BANDS:
        if band["max_cp"] is None or cp < band["max_cp"]:
            return band["key"]
    raise ValueError("점도 구간 설정이 올바르지 않습니다.")   # 마지막 구간의 max_cp 가 None 이면 오지 않음
