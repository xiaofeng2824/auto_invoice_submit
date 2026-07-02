# DeepSeek V4 Flash 对比基准测试方案

对比 **opencode Go 套餐端点** 与 **DeepSeek 官方 API** 在延迟速度和输出质量上的差异。

---

## 1. 对比对象

| 维度 | opencode Go | DeepSeek 官方 |
|------|-------------|---------------|
| 端点 | `https://opencode.ai/zen/go/v1` | `https://api.deepseek.com/v1` |
| 模型 | `deepseek-v4-flash` | `deepseek-chat`（可配置） |
| 协议 | OpenAI 兼容 | OpenAI 兼容 |
| 计费 | $10/月订阅（含额度） | 按 token 计费 |
| API Key | `OPENCODE_GO_API_KEY` | `DEEPSEEK_API_KEY` |

> 官方模型名请按实际可用模型调整，通过环境变量 `DEEPSEEK_MODEL` 覆盖。

---

## 2. 测试维度与指标

### 2.1 延迟与速度

| 指标 | 说明 | 测量方式 |
|------|------|----------|
| **TTFT（首字延迟）** | 从发出请求到收到第一个 token 的时间 | 流式响应，记录首个 chunk 到达时间 |
| **总耗时** | 请求发出到完整响应结束的端到端时间 | `perf_counter` 计时 |
| **生成耗时** | 从首 token 到末 token 的纯生成时间 | 总耗时 - TTFT |
| **TPS（吞吐量）** | 每秒输出 token 数 | output_tokens / 生成耗时 |

统计值：均值、中位数、P95。

### 2.2 输出质量

每个测试用例配备**自动评估器**，返回通过/不通过 + 0~1 分值 + 说明：

| 评估类型 | 判定方式 |
|----------|----------|
| 关键词命中 | 回答是否包含预期关键词 |
| 代码正确性 | `ast.parse` 语法检查 + `exec` 执行 + 用例验证 |
| JSON 格式 | 解析 JSON 并校验结构与元素数量 |
| 字数约束 | 统计中文字符数与目标值的偏差 |
| 长文本检索 | 回答是否包含埋入文本中的关键信息 |

质量通过率 = 自动评估通过的请求占比。

---

## 3. 测试用例设计

共 10 个用例，覆盖 5 个类别：

| 类别 | 用例 | 评估方式 |
|------|------|----------|
| simple_qa | 简单数学问答 / 简单事实问答 | 关键词命中 |
| code_gen | 素数判断 / 快速排序 / FizzBuzz | 编译 + 执行 + 用例验证 |
| reasoning | 传递性推理 / 三段论推理 | 关键词命中 |
| instruction | JSON 格式约束 / 字数约束 | JSON 解析 / 字数统计 |
| long_context | 长文本信息检索 | 埋入关键词命中 |

每个用例默认运行 5 次（`--runs` 可调），取统计值消除单次波动。

---

## 4. 技术实现

```
benchmark/
  config.py        # 双端点配置（从环境变量读取 API Key）
  test_cases.py    # 10 个测试用例 + 自动评估器
  metrics.py       # 指标数据结构
  runner.py        # 流式请求执行 + 延迟采集
  report.py        # 统计聚合 + 报告输出
  main.py          # CLI 入口
  requirements.txt # 依赖（openai SDK）
  results/         # 运行时生成，存放报告
```

**核心设计**：
- 使用 `openai` Python SDK，两个端点均为 OpenAI 兼容格式，统一接口
- **流式响应**（`stream=True`）精确测量 TTFT
- `stream_options={"include_usage": True}` 获取 token 用量
- `temperature=0.0` 保证结果可复现
- 缺少 API Key 的端点自动跳过，不阻断测试

---

## 5. 使用方法

### 5.1 安装依赖

```bash
pip install -r benchmark/requirements.txt
```

### 5.2 设置环境变量

```bash
export OPENCODE_GO_API_KEY="你的Go套餐API Key"
export DEEPSEEK_API_KEY="你的DeepSeek官方API Key"

# 可选：覆盖默认模型名
# export OPENCODE_GO_MODEL="deepseek-v4-flash"
# export DEEPSEEK_MODEL="deepseek-chat"
# export DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"
```

### 5.3 查看测试用例

```bash
python benchmark/main.py list
```

### 5.4 运行完整基准测试

```bash
python benchmark/main.py run
```

### 5.5 自定义参数

```bash
# 每个用例跑 10 次
python benchmark/main.py run --runs 10

# 只跑代码生成类用例
python benchmark/main.py run --cases code_prime,code_sort,code_fizzbuzz

# 增大输出上限
python benchmark/main.py run --max-tokens 2048

# 指定输出目录
python benchmark/main.py run --output my_results
```

---

## 6. 输出报告

### 6.1 终端汇总表

运行结束后打印两张表：

- **端点汇总**：TTFT 均值/中位/P95、总耗时、TPS、质量通过率、质量均分、成功率
- **按用例明细**：每个测试用例在两个端点上的逐项对比

### 6.2 文件报告

| 文件 | 内容 |
|------|------|
| `raw_results.jsonl` | 逐次请求的完整原始数据（JSON Lines） |
| `raw_results.csv` | 同上，CSV 格式，便于 Excel/数据分析 |
| `case_summary.csv` | 按测试用例 x 端点汇总的统计值 |

---

## 7. 结果分析指南

### 7.1 如何判断 Go 端点是否值得用

| 场景 | 判断依据 |
|------|----------|
| 速度可接受 | TTFT 和 TPS 与官方差距 < 30% |
| 质量一致 | 质量通过率差距 < 10%，质量均分差距 < 0.1 |
| 稳定可靠 | 成功率 >= 95%，P95 延迟无异常尖刺 |

### 7.2 常见现象解读

- **TTFT 差距大但 TPS 接近**：Go 端点有额外网络跳转，首字慢但生成速度不受影响
- **代码类用例通过率差异大**：可能存在 token 截断（调大 `--max-tokens`）或模型路由差异
- **长上下文用例失败**：检查是否触发了上下文窗口限制
- **质量一致但延迟波动大**：Go 端点可能有排队/限流，建议增大 `--runs` 观察方差

### 7.3 进阶建议

- 跑 3 轮取最佳/中位，排除偶发网络抖动
- 在不同时段跑（高峰 vs 低峰），观察稳定性
- 如需测并发吞吐，可修改 `runner.py` 改为 `asyncio` 并发请求
- 质量评估可扩展为 LLM-as-Judge：加一个评估模型对自由回答打分

---

## 8. 环境变量速查

| 变量 | 必需 | 说明 |
|------|------|------|
| `OPENCODE_GO_API_KEY` | Go 端点必需 | opencode Zen 控制台获取 |
| `DEEPSEEK_API_KEY` | 官方端点必需 | DeepSeek 平台获取 |
| `OPENCODE_GO_MODEL` | 可选 | 默认 `deepseek-v4-flash` |
| `DEEPSEEK_MODEL` | 可选 | 默认 `deepseek-chat` |
| `DEEPSEEK_BASE_URL` | 可选 | 默认 `https://api.deepseek.com/v1` |
