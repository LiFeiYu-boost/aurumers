from langchain_core.prompts import ChatPromptTemplate


JSON_RULES = """请严格只返回一个合法 JSON 对象，不要返回 Markdown，不要返回代码块，不要返回额外解释。
JSON 字段固定为：
- summary: 1 到 2 句话总结
- trend: 只能是 上涨 / 下跌 / 震荡 / 未知
- reasons: 字符串数组，最多 3 条
- advice: 一句简短建议
- confidence: 0 到 1 之间的小数，表示判断的可信度，信息不足时给 0.3 以下
如果信息不足，请保守输出，禁止编造数字。"""


def build_analysis_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是黄金市场分析助手。"
                "请基于输入的价格和新闻，输出保守、可追溯的黄金市场判断。"
                f"{JSON_RULES}",
            ),
            (
                "human",
                "分析时间：{generated_at}\n"
                "黄金价格原始值：{price_raw}\n"
                "黄金价格数值：{price_value}\n"
                "相关新闻：\n{news_text}\n\n"
                "请返回 JSON。",
            ),
        ]
    )
