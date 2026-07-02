from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class RequestMetrics:
    endpoint: str
    test_id: str
    category: str
    test_name: str
    run_index: int
    success: bool
    error: str
    ttft_ms: float
    total_ms: float
    generation_ms: float
    input_tokens: int
    output_tokens: int
    tps: float
    response_text: str
    quality_passed: bool
    quality_score: float
    quality_note: str

    def to_dict(self) -> dict:
        return asdict(self)
