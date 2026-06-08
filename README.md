# auto_invoice_submit

发票自动化提交工具：扫描 PDF 发票，提取备注栏订单号，将 PDF 复制为 `订单号_原文件名.pdf`，再通过 Playwright 打开抖音后台按订单号筛选并上传发票。

## 功能

- 扫描 `data/input_pdfs/` 下的 PDF。
- 使用 PyMuPDF 读取 PDF 文本。
- 从备注/订单号关键字附近提取订单号。
- 复制 PDF 到 `data/renamed_pdfs/`，命名为：

```text
订单号_原文件名.pdf
```

- 生成处理台账 `data/invoice_records.csv`。
- 使用 Playwright 可视化浏览器打开抖音后台。
- 支持保存登录态，后续复用登录。
- 支持 `dry_run`，先筛选订单但不实际上传。

## 安装

```bash
cd /home/charles/code/auto_invoice_submit
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## 配置

主要配置在 [config.yaml](config.yaml)。

初始建议保持：

```yaml
upload:
  dry_run: true
```

这样浏览器只会打开后台并按订单号筛选，不会真正上传，方便先调试页面选择器。

如果你知道抖音后台“发票管理”的直达 URL，可以填到：

```yaml
douyin:
  invoice_management_url: ""
```

后台页面选择器在：

```yaml
douyin:
  selectors:
```

抖音后台页面如果改版，可能需要调整这些选择器。

## 使用

### 1. 放入 PDF

把待处理发票放到：

```text
data/input_pdfs/
```

### 2. 解析并复制 PDF

```bash
python main.py parse
```

成功后会复制到：

```text
data/renamed_pdfs/
```

并生成：

```text
data/invoice_records.csv
```

### 3. 保存抖音登录态

```bash
python main.py login
```

程序会打开可视化 Chromium 浏览器。你手动登录抖音后台，登录完成后回到终端按 Enter，程序会保存登录态到：

```text
browser_state/douyin_storage_state.json
```

### 4. 上传或 dry-run 上传

```bash
python main.py upload
```

如果 `dry_run: true`，只会筛选订单，不会真正上传。

确认流程正确后，把 [config.yaml](config.yaml) 改成：

```yaml
upload:
  dry_run: false
```

再执行：

```bash
python main.py upload
```

### 5. 全流程

```bash
python main.py run
```

等价于先 `parse` 再 `upload`。

## 注意事项

- 不会绕过验证码或安全验证；遇到验证时需要人工处理。
- `browser_state/` 保存登录态，不要提交或分享。
- `data/` 目录下可能包含发票和订单信息，已加入 `.gitignore`。
- 第一版没有 OCR，适合电子发票 PDF；如果 PDF 是扫描图片，可能识别不到订单号。
