import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests


_BJ = timezone(timedelta(hours=8))


def get_gold_price() -> str:
    """Return the latest COMEX gold quote as a bare string (legacy contract)."""
    try:
        timestamp = int(time.time() * 1000)
        url = f"https://www.huilvbiao.com/api/gold_indexApi?t={timestamp}"
        headers = {"User-Agent": "Mozilla/5.0"}

        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        match = re.search(r'hq_str_hf_GC="([^"]+)"', response.text)
        if not match:
            return "N/A"

        data_list = match.group(1).split(",")
        return data_list[0].strip() if data_list else "N/A"
    except Exception:
        return "N/A"


def _comex_open_at(now: datetime) -> bool:
    """COMEX gold trades roughly Sunday 18:00 ET → Friday 17:00 ET (Beijing: Mon 06:00 → Sat 06:00)."""
    bj = now.astimezone(_BJ)
    weekday = bj.weekday()  # 0=Mon
    hour = bj.hour
    if weekday == 5:  # Saturday
        return hour < 6
    if weekday == 6:  # Sunday
        return hour >= 7  # ~19:00 ET = 07:00 BJ next day
    if weekday == 0:
        return hour >= 6
    return True


def _sge_open_at(now: datetime) -> bool:
    """SGE day session 09:00-15:30 + night 19:50-02:30(next day), Beijing time, Mon-Fri."""
    bj = now.astimezone(_BJ)
    weekday = bj.weekday()
    minutes = bj.hour * 60 + bj.minute
    if weekday in (5, 6):  # Sat / Sun closed
        # Saturday early hours (00:00-02:30) is technically Friday's night session
        if weekday == 5 and minutes <= 2 * 60 + 30:
            return True
        return False
    if 9 * 60 <= minutes <= 15 * 60 + 30:
        return True
    if 19 * 60 + 50 <= minutes:
        return True
    if minutes <= 2 * 60 + 30:
        return True
    return False


def get_market_snapshot() -> dict:
    """Returns price + market timing meta. Never raises.

    Market open/closed flags are computed from system time only, so they remain
    accurate even if the upstream price feed is unreachable.
    """
    now = datetime.now(_BJ)
    comex_open = _comex_open_at(now)
    sge_open = _sge_open_at(now)
    out: dict = {
        "price_raw": "N/A",
        "price_value": None,
        "data_timestamp": None,
        "data_label": "实时报价" if comex_open else "上次收盘",
        "comex_open": comex_open,
        "sge_open": sge_open,
        "fetched_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        timestamp = int(time.time() * 1000)
        url = f"https://www.huilvbiao.com/api/gold_indexApi?t={timestamp}"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        match = re.search(r'hq_str_hf_GC="([^"]+)"', response.text)
        if match:
            fields = match.group(1).split(",")
            if fields:
                out["price_raw"] = fields[0].strip() or "N/A"
                try:
                    out["price_value"] = float(fields[0])
                except ValueError:
                    pass
            if len(fields) > 6 and fields[6].strip():
                out["data_timestamp"] = fields[6].strip()
    except Exception:
        # Network failure leaves price_raw=N/A but market flags remain accurate.
        pass
    return out
