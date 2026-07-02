from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class EvalResult:
    passed: bool
    score: float
    note: str


Evaluator = Callable[[str], EvalResult]


@dataclass
class TestCase:
    id: str
    category: str
    name: str
    messages: list[dict]
    evaluator: Evaluator


def _extract_code(text: str) -> str:
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1)
    return text.strip()


def _eval_exact(expected: str) -> Evaluator:
    def evaluate(text: str) -> EvalResult:
        clean = text.strip().strip("`").strip()
        if expected in clean:
            return EvalResult(True, 1.0, f"命中关键词: {expected}")
        return EvalResult(False, 0.0, f"未找到 '{expected}'，实际: {clean[:80]}")

    return evaluate


def _eval_code_prime(text: str) -> EvalResult:
    code = _extract_code(text)
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return EvalResult(False, 0.0, f"语法错误: {e}")
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    if "is_prime" not in names:
        return EvalResult(False, 0.2, "未定义 is_prime 函数")
    namespace: dict = {}
    try:
        exec(code, namespace)
    except Exception as e:
        return EvalResult(False, 0.3, f"执行错误: {e}")
    func = namespace.get("is_prime")
    if not callable(func):
        return EvalResult(False, 0.3, "is_prime 不可调用")
    checks = [(2, True), (3, True), (4, False), (5, True), (1, False), (9, False), (17, True)]
    passed = sum(1 for n, exp in checks if bool(func(n)) == exp)
    ratio = passed / len(checks)
    return EvalResult(ratio == 1.0, ratio, f"{passed}/{len(checks)} 用例通过")


def _eval_code_sort(text: str) -> EvalResult:
    code = _extract_code(text)
    try:
        ast.parse(code)
    except SyntaxError as e:
        return EvalResult(False, 0.0, f"语法错误: {e}")
    namespace: dict = {}
    try:
        exec(code, namespace)
    except Exception as e:
        return EvalResult(False, 0.3, f"执行错误: {e}")
    func = namespace.get("quicksort")
    if not callable(func):
        return EvalResult(False, 0.3, "未定义 quicksort 函数")
    test_input = [3, 1, 4, 1, 5, 9, 2, 6]
    try:
        result = func(test_input)
    except Exception as e:
        return EvalResult(False, 0.4, f"调用错误: {e}")
    expected = sorted(test_input)
    if result == expected:
        return EvalResult(True, 1.0, "排序正确")
    return EvalResult(False, 0.5, f"排序错误: {result} != {expected}")


def _eval_json_fruits(text: str) -> EvalResult:
    clean = text.strip().strip("`").strip()
    match = re.search(r"\[.*?\]", clean, re.DOTALL)
    if not match:
        return EvalResult(False, 0.0, "未找到 JSON 数组")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        return EvalResult(False, 0.3, f"JSON 解析失败: {e}")
    if not isinstance(data, list):
        return EvalResult(False, 0.4, "不是数组")
    if len(data) == 3 and all(isinstance(x, str) for x in data):
        return EvalResult(True, 1.0, f"3 个字符串元素: {data}")
    return EvalResult(False, 0.6, f"元素数量/类型不符: {data}")


def _eval_chinese_length(target: int, tolerance: int = 3) -> Evaluator:
    def evaluate(text: str) -> EvalResult:
        clean = text.strip().replace("。", "").replace("，", "").replace(" ", "")
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", clean)
        count = len(chinese_chars)
        diff = abs(count - target)
        if diff <= tolerance:
            return EvalResult(True, 1.0 - diff / max(target, 1), f"字数: {count}（目标 {target}）")
        return EvalResult(False, 0.3, f"字数偏差过大: {count}（目标 {target}，差 {diff}）")

    return evaluate


def _eval_long_context(answer_keyword: str) -> Evaluator:
    def evaluate(text: str) -> EvalResult:
        if answer_keyword in text:
            return EvalResult(True, 1.0, f"命中关键词: {answer_keyword}")
        return EvalResult(False, 0.0, f"未提及 '{answer_keyword}'")

    return evaluate


def _eval_reasoning_yes(text: str) -> EvalResult:
    clean = text.strip()
    if "是" in clean and "否" not in clean.split("是")[0][-5:]:
        return EvalResult(True, 1.0, "回答: 是")
    if clean.startswith("是"):
        return EvalResult(True, 1.0, "回答: 是")
    return EvalResult(False, 0.0, f"未明确回答'是': {clean[:60]}")


_LONG_CONTEXT_TEXT = (
    "在2024年的技术峰会上，首席架构师林婉清提出了一个关于微服务治理的新方案。"
    "该方案核心是通过服务网格来实现流量管控与熔断降级。"
    "峰会上还有多位工程师分享了他们在 Kubernetes 集群运维中的实践经验，"
    "包括如何处理节点漂移、如何优化 etcd 性能，以及在大规模集群中如何做日志收集。"
    "产品经理赵明远则从业务角度讨论了需求拆分与迭代节奏的平衡问题。"
    "整个峰会持续了两天，吸引了超过五百名开发者参与。"
    "会后，林婉清还组织了一场圆桌讨论，深入探讨了 service mesh 在中小团队的落地可行性。"
) * 3


def all_test_cases() -> list[TestCase]:
    return [
        TestCase(
            id="simple_math",
            category="simple_qa",
            name="简单数学问答",
            messages=[{"role": "user", "content": "2+2等于几？只回答数字，不要其他内容。"}],
            evaluator=_eval_exact("4"),
        ),
        TestCase(
            id="simple_factual",
            category="simple_qa",
            name="简单事实问答",
            messages=[{"role": "user", "content": "中国的首都是哪个城市？只回答城市名。"}],
            evaluator=_eval_exact("北京"),
        ),
        TestCase(
            id="code_prime",
            category="code_gen",
            name="素数判断函数",
            messages=[{"role": "user", "content": "用Python写一个函数 is_prime(n)，判断n是否为素数。只输出代码，不要解释。"}],
            evaluator=_eval_code_prime,
        ),
        TestCase(
            id="code_sort",
            category="code_gen",
            name="快速排序实现",
            messages=[{"role": "user", "content": "用Python实现快速排序函数 quicksort(arr)，返回排序后的列表。只输出代码。"}],
            evaluator=_eval_code_sort,
        ),
        TestCase(
            id="reasoning_transitive",
            category="reasoning",
            name="传递性推理",
            messages=[{"role": "user", "content": "A比B高，B比C高。谁最高？只回答字母。"}],
            evaluator=_eval_exact("A"),
        ),
        TestCase(
            id="reasoning_syllogism",
            category="reasoning",
            name="三段论推理",
            messages=[{"role": "user", "content": "所有的猫都是动物，汤姆是猫。汤姆是动物吗？只回答\"是\"或\"否\"。"}],
            evaluator=_eval_reasoning_yes,
        ),
        TestCase(
            id="instruction_json",
            category="instruction",
            name="JSON格式约束",
            messages=[{"role": "user", "content": "列出3种水果的名称，只输出JSON数组格式，例如 [\"苹果\",\"香蕉\",\"橘子\"]，不要其他内容。"}],
            evaluator=_eval_json_fruits,
        ),
        TestCase(
            id="instruction_length",
            category="instruction",
            name="字数约束",
            messages=[{"role": "user", "content": "用恰好20个汉字描述编程这件事。不要加标点符号，不要换行。"}],
            evaluator=_eval_chinese_length(20),
        ),
        TestCase(
            id="long_context",
            category="long_context",
            name="长文本信息检索",
            messages=[
                {"role": "user", "content": f"阅读以下文字并回答问题。\n\n{_LONG_CONTEXT_TEXT}\n\n提出微服务治理新方案的架构师叫什么名字？只回答姓名。"},
            ],
            evaluator=_eval_long_context("林婉清"),
        ),
        TestCase(
            id="code_fizzbuzz",
            category="code_gen",
            name="FizzBuzz实现",
            messages=[{"role": "user", "content": "用Python写一个 fizzbuzz(n) 函数，打印1到n的FizzBuzz结果。只输出代码。"}],
            evaluator=_eval_fizzbuzz,
        ),
    ]


def _eval_fizzbuzz(text: str) -> EvalResult:
    code = _extract_code(text)
    try:
        ast.parse(code)
    except SyntaxError as e:
        return EvalResult(False, 0.0, f"语法错误: {e}")
    namespace: dict = {}
    try:
        exec(code, namespace)
    except Exception as e:
        return EvalResult(False, 0.3, f"执行错误: {e}")
    func = namespace.get("fizzbuzz")
    if not callable(func):
        return EvalResult(False, 0.3, "未定义 fizzbuzz 函数")
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            func(15)
    except Exception as e:
        return EvalResult(False, 0.4, f"调用错误: {e}")
    lines = buf.getvalue().strip().split("\n")
    expected = []
    for i in range(1, 16):
        if i % 15 == 0:
            expected.append("FizzBuzz")
        elif i % 3 == 0:
            expected.append("Fizz")
        elif i % 5 == 0:
            expected.append("Buzz")
        else:
            expected.append(str(i))
    if lines == expected:
        return EvalResult(True, 1.0, "FizzBuzz 输出完全正确")
    correct = sum(1 for a, b in zip(lines, expected) if a == b)
    ratio = correct / len(expected)
    return EvalResult(ratio == 1.0, ratio, f"{correct}/{len(expected)} 行正确")
