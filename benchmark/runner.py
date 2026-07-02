from __future__ import annotations

import time
from typing import Iterator

from openai import OpenAI

from config import EndpointConfig, TestConfig
from metrics import RequestMetrics
from test_cases import TestCase


def _stream_completion(
    client: OpenAI,
    endpoint: EndpointConfig,
    test_case: TestCase,
    test_config: TestConfig,
) -> tuple[str, int, int, float, float, float]:
    start = time.perf_counter()
    first_token_time: float | None = None
    chunks: list[str] = []

    stream = client.chat.completions.create(
        model=endpoint.model,
        messages=test_case.messages,
        temperature=test_config.temperature,
        max_tokens=test_config.max_tokens,
        stream=True,
        stream_options={"include_usage": True},
        timeout=test_config.timeout,
    )

    usage_input = 0
    usage_output = 0

    for chunk in stream:
        if first_token_time is None and chunk.choices:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                first_token_time = time.perf_counter()
        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                chunks.append(delta.content)
        if chunk.usage:
            usage_input = chunk.usage.prompt_tokens or 0
            usage_output = chunk.usage.completion_tokens or 0

    end = time.perf_counter()
    total_ms = (end - start) * 1000
    ttft_ms = (first_token_time - start) * 1000 if first_token_time else 0.0
    generation_ms = (end - first_token_time) * 1000 if first_token_time else total_ms

    return "".join(chunks), usage_input, usage_output, ttft_ms, total_ms, generation_ms


def _run_single(
    endpoint: EndpointConfig,
    test_case: TestCase,
    test_config: TestConfig,
    run_index: int,
) -> RequestMetrics:
    client = OpenAI(api_key=endpoint.api_key, base_url=endpoint.base_url)
    error_msg = ""
    response_text = ""
    input_tokens = 0
    output_tokens = 0
    ttft_ms = 0.0
    total_ms = 0.0
    generation_ms = 0.0
    success = False

    try:
        result = _stream_completion(client, endpoint, test_case, test_config)
        response_text, input_tokens, output_tokens, ttft_ms, total_ms, generation_ms = result
        success = True
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        total_ms = 0.0

    tps = (output_tokens / generation_ms * 1000) if generation_ms > 0 and output_tokens > 0 else 0.0

    quality_passed = False
    quality_score = 0.0
    quality_note = "未评估（请求失败）"
    if success and response_text:
        eval_result = test_case.evaluator(response_text)
        quality_passed = eval_result.passed
        quality_score = eval_result.score
        quality_note = eval_result.note

    return RequestMetrics(
        endpoint=endpoint.name,
        test_id=test_case.id,
        category=test_case.category,
        test_name=test_case.name,
        run_index=run_index,
        success=success,
        error=error_msg,
        ttft_ms=round(ttft_ms, 2),
        total_ms=round(total_ms, 2),
        generation_ms=round(generation_ms, 2),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tps=round(tps, 2),
        response_text=response_text[:500],
        quality_passed=quality_passed,
        quality_score=round(quality_score, 4),
        quality_note=quality_note,
    )


def run_benchmark(
    endpoints: list[EndpointConfig],
    test_cases: list[TestCase],
    test_config: TestConfig,
) -> Iterator[RequestMetrics]:
    total = len(endpoints) * len(test_cases) * test_config.runs_per_case
    done = 0
    for test_case in test_cases:
        for endpoint in endpoints:
            if not endpoint.enabled:
                done += test_config.runs_per_case
                continue
            for run_index in range(test_config.runs_per_case):
                done += 1
                print(f"  [{done}/{total}] {endpoint.name} | {test_case.id} #{run_index + 1}", end="\r", flush=True)
                yield _run_single(endpoint, test_case, test_config, run_index)
    print()
