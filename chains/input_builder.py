from schemas import AnalysisInput, NewsItem


def normalize_price(price_raw: str) -> float | None:
    try:
        return float(price_raw)
    except (TypeError, ValueError):
        return None


def build_analysis_input(*, price_raw: str, news: list[NewsItem], source: str) -> AnalysisInput:
    return AnalysisInput(
        price_raw=price_raw or "N/A",
        price_value=normalize_price(price_raw),
        news=news,
        source=source,
    )


def news_to_text(news: list[NewsItem]) -> str:
    if not news:
        return "暂无相关新闻"

    lines: list[str] = []
    for index, item in enumerate(news, start=1):
        lines.append(
            f"{index}. {item.title} | 来源: {item.source or 'unknown'} | 链接: {item.link or 'N/A'}"
        )
    return "\n".join(lines)
