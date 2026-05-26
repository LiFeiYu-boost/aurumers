import re

import requests

from schemas import NewsItem


def get_gold_news(limit: int = 3) -> list[NewsItem]:
    try:
        url = "https://finance.sina.com.cn/roll/c/57084.shtml"
        headers = {"User-Agent": "Mozilla/5.0"}

        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        html = response.text

        pattern = re.compile(r'<a[^>]*href="(.*?)"[^>]*>(.*?)</a>', re.S)
        news_list = re.findall(pattern, html)
        keywords = ["黄金", "金价", "贵金属"]

        result: list[NewsItem] = []
        seen: set[str] = set()
        for link, title in news_list:
            title = re.sub(r"<.*?>", "", title).strip()
            if len(title) <= 10:
                continue
            if title.startswith("分析："):
                continue
            if not any(keyword in title for keyword in keywords):
                continue
            if title in seen:
                continue

            seen.add(title)
            if link.startswith("//"):
                link = f"https:{link}"
            result.append(NewsItem(title=title, link=link, source="sina_finance"))
            if len(result) >= max(limit, 1):
                break

        return result
    except Exception:
        return []
