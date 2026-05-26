import json
import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

from chains.input_builder import news_to_text
from chains.mock_llm import build_mock_output
from chains.parser import parse_result
from config import settings
from prompts.gold_prompt import build_analysis_prompt
from schemas import AnalysisInput, AnalysisLLMOutput


logger = logging.getLogger(__name__)


def build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.model_name,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
        temperature=0,
    )


def _build_payload(analysis_input: AnalysisInput) -> dict:
    return {
        "generated_at": analysis_input.generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        "price_raw": analysis_input.price_raw,
        "price_value": analysis_input.price_value if analysis_input.price_value is not None else "N/A",
        "news_text": news_to_text(analysis_input.news),
    }


def run_analysis_chain(analysis_input: AnalysisInput) -> tuple[AnalysisLLMOutput, str, str | None]:
    if settings.mock_llm:
        mock_payload = build_mock_output(analysis_input)
        raw_output = json.dumps(mock_payload, ensure_ascii=False)
        parsed_output, parse_error = parse_result(raw_output)
        return parsed_output, raw_output, parse_error

    chain = build_analysis_prompt() | build_llm() | StrOutputParser()
    raw_output = chain.invoke(_build_payload(analysis_input))
    parsed_output, parse_error = parse_result(raw_output)
    if parse_error:
        logger.warning("Model JSON parse failed: %s", parse_error)
    return parsed_output, raw_output, parse_error
