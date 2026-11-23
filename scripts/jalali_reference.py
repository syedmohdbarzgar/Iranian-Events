"""مرجعِ مستقلِ تقویم جلالی برای ممیزی — الگوریتمِ بیراشکوفسکی (jalaali-js).

این فایل **جایگزینِ موتور نیست** و هیچ‌جا در تولیدِ تقویم استفاده نمی‌شود؛ فقط مرجعِ
مقایسهٔ مستقل است تا صحتِ `calendar_engine` با الگوریتمی دیگر (نه همان فرمولِ ۳۳ساله)
سنجیده شود. مبنای الگوریتم: A. Borkowski, "The Persian calendar for 3000 years",
Earth, Moon and Planets 74 (1996) — همان پیاده‌سازیِ مرجعِ jalaali-js.

تفاوتِ مهم با موتور: مرزِ سال با `march` (روزِ مارسِ ۱ فروردین) تعیین می‌شود، نه با
شمارشِ روزِ ۳۳ساله؛ پس اگر موتور در یک سالِ مرزی بلغزد، این مرجع آن را نشان می‌دهد.
"""
from __future__ import annotations

from datetime import date

BREAKS = (-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
          1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178)


def _mod(a: int, b: int) -> int:
    return a - b * (a // b)


def jal_cal(jy: int) -> tuple[int, int]:
    """(روزِ مارسِ ۱ فروردین، شاخصِ کبیسه) — شاخصِ ۰ یعنی سالِ کبیسه."""
    if jy < BREAKS[0] or jy >= BREAKS[-1]:
        raise ValueError(f"سال {jy} بیرون از بازهٔ الگوریتم مرجع")
    leap_j = -14
    jp = BREAKS[0]
    jump = 0
    for jm in BREAKS[1:]:
        jump = jm - jp
        if jy < jm:
            break
        leap_j += (jump // 33) * 8 + _mod(jump, 33) // 4
        jp = jm
    n = jy - jp
    leap_j += (n // 33) * 8 + (_mod(n, 33) + 3) // 4
    if _mod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1
    gy = jy + 621
    leap_g = gy // 4 - ((gy // 100 + 1) * 3) // 4 - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + ((jump + 4) // 33) * 33
    leap = _mod(_mod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return march, leap


def is_leap(jy: int) -> bool:
    return jal_cal(jy)[1] == 0


def first_day(jy: int) -> date:
    """۱ فروردینِ سالِ jy به میلادی."""
    return date(jy + 621, 3, jal_cal(jy)[0])


def month_length(jy: int, jm: int) -> int:
    if not 1 <= jm <= 12:
        raise ValueError("ماه نامعتبر")
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_leap(jy) else 29


def from_gregorian(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    d = date(gy, gm, gd)
    jy = gy - 621
    while first_day(jy) > d:
        jy -= 1
    while first_day(jy + 1) <= d:
        jy += 1
    offset = (d - first_day(jy)).days
    if offset < 186:
        return jy, offset // 31 + 1, offset % 31 + 1
    offset -= 186
    return jy, offset // 30 + 7, offset % 30 + 1


def to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    if not 1 <= jm <= 12:
        raise ValueError("ماه نامعتبر")
    if not 1 <= jd <= month_length(jy, jm):
        raise ValueError("روز نامعتبر")
    offset = (jm - 1) * 31 if jm <= 7 else 186 + (jm - 7) * 30
    d = first_day(jy).toordinal() + offset + jd - 1
    g = date.fromordinal(d)
    return g.year, g.month, g.day


def persian_weekday(gy: int, gm: int, gd: int) -> int:
    """روزِ هفته با قراردادِ ایرانی: شنبه=۰ … جمعه=۶."""
    return (date(gy, gm, gd).weekday() + 2) % 7


def year_days(jy: int) -> int:
    return (first_day(jy + 1) - first_day(jy)).days
