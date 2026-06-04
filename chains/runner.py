import logging
import time
from datetime import datetime
from threading import Lock
from uuid import uuid4

from chains.analysis_chain import run_analysis_chain
from chains.input_builder import build_analysis_input
from chains.verifier import _direction_from_close
from config import settings
from schemas import AnalysisRecord, AnalysisStatus, Trend
from storage.record_manager import get_latest_records, init_storage, save_record
from tools.gold_price import get_gold_price
from tools.news import get_gold_news


logger = logging.getLogger(__name__)
RUN_LOCK = Lock()


def _trend_from_price(price_value: float | None) -> Trend:
    """趋势由价格涨跌幅确定性计算，锚点取上一条分析记录（约 30 分钟前）。

    与日预测验证口径一致：复用 verifier._direction_from_close 的阈值
    （0.15% 或 0.5/克取大值）。当前记录尚未保存，故 get_latest_records(1)
    取到的即上一个点。
    """
    if price_value is None:
        return Trend.UNKNOWN
    prev = get_latest_records(1)
    anchor = prev[0].price_value if prev else None
    if anchor is None:
        return Trend.UNKNOWN
    return _direction_from_close(anchor, price_value)


def _resolve_status(*, price_ok: bool, news_ok: bool, output_ok: bool) -> AnalysisStatus:
    if price_ok and news_ok and output_ok:
        return AnalysisStatus.SUCCESS
    if output_ok and (price_ok or news_ok):
        return AnalysisStatus.PARTIAL
    return AnalysisStatus.FAILED


def run_gold_analysis_once(source: str = "manual") -> AnalysisRecord:
    with RUN_LOCK:
        init_storage()
        started = time.perf_counter()
        errors: list[str] = []

        price_raw = get_gold_price()
        news = get_gold_news(limit=settings.news_limit)

        if price_raw == "N/A":
            errors.append("金价抓取失败")
        if not news:
            errors.append("新闻抓取为空")

        analysis_input = build_analysis_input(price_raw=price_raw, news=news, source=source)
        raw_output = ""
        llm_output = None

        parse_error: str | None = None
        if analysis_input.price_value is not None or analysis_input.news:
            llm_output, raw_output, parse_error = run_analysis_chain(analysis_input)
            if parse_error:
                errors.append(f"模型解析失败: {parse_error}")
        else:
            raw_output = "数据源全部失败，未调用模型"

        if llm_output and not llm_output.summary:
            errors.append("模型未返回有效摘要")

        output_ok = (
            parse_error is None
            and llm_output is not None
            and llm_output.summary not in ("", "暂无总结")
            and bool(llm_output.reasons)
        )

        latency_ms = int((time.perf_counter() - started) * 1000)
        status = _resolve_status(
            price_ok=analysis_input.price_value is not None,
            news_ok=bool(analysis_input.news),
            output_ok=output_ok,
        )

        now = datetime.now()
        record = AnalysisRecord(
            id=str(uuid4()),
            time=now.strftime("%Y-%m-%d %H:%M:%S"),
            source=analysis_input.source,
            status=status,
            price_raw=analysis_input.price_raw,
            price_value=analysis_input.price_value,
            news=analysis_input.news,
            summary=llm_output.summary if llm_output else "暂无总结",
            trend=_trend_from_price(analysis_input.price_value),
            reasons=llm_output.reasons if llm_output else [],
            advice=llm_output.advice if llm_output else "暂无建议",
            raw_output=raw_output,
            model_name=("mock" if settings.mock_llm else settings.model_name),
            prompt_version=settings.prompt_version,
            latency_ms=latency_ms,
            error="; ".join(errors) if errors else None,
            input_snapshot=analysis_input.model_dump(mode="json"),
            confidence=llm_output.confidence if llm_output else None,
            news_count=len(analysis_input.news),
        )
        save_record(record)
        logger.info("Analysis finished status=%s latency_ms=%s", record.status.value, record.latency_ms)
        return record
