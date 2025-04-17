![image](https://github.com/user-attachments/assets/b97c789e-0d41-47c3-99cb-542abee96632)

![image](https://github.com/user-attachments/assets/b6797232-4f71-4180-9b1d-d58eb7c16d08)

![image](https://github.com/user-attachments/assets/f859d0dc-e39e-478d-abad-4c6ab361f893)

# 👋 Nephesh

Nephesh 是一个基于大语言模型的智能代理平台，集成了多种工具能力，支持复杂任务执行和自动化流程。

## 项目演示

<video src="https://private-user-images.githubusercontent.com/57515812/434656488-e1a5ad0b-6ed2-498b-9dba-982963e4cea8.mp4?jwt=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3NDQ4NzA0MjIsIm5iZiI6MTc0NDg3MDEyMiwicGF0aCI6Ii81NzUxNTgxMi80MzQ2NTY0ODgtZTFhNWFkMGItNmVkMi00OThiLTlkYmEtOTgyOTYzZTRjZWE4Lm1wND9YLUFtei1BbGdvcml0aG09QVdTNC1ITUFDLVNIQTI1NiZYLUFtei1DcmVkZW50aWFsPUFLSUFWQ09EWUxTQTUzUFFLNFpBJTJGMjAyNTA0MTclMkZ1cy1lYXN0LTElMkZzMyUyRmF3czRfcmVxdWVzdCZYLUFtei1EYXRlPTIwMjUwNDE3VDA2MDg0MlomWC1BbXotRXhwaXJlcz0zMDAmWC1BbXotU2lnbmF0dXJlPWJkZjg1MTUwMzg3Y2M0NGE3NzVkNGIyNWE0ZjY3YWE5NzA3NWE3OGVjMWU2YmMxNjU3YzczOWZlYTgzYTIzYzcmWC1BbXotU2lnbmVkSGVhZGVycz1ob3N0In0.5tEs-p7NUQrqj4a5AkHO1Q8tR2OndeYK9Us9EA5uGdg" data-canonical-src="https://private-user-images.githubusercontent.com/57515812/434656488-e1a5ad0b-6ed2-498b-9dba-982963e4cea8.mp4?jwt=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3NDQ4NzA0MjIsIm5iZiI6MTc0NDg3MDEyMiwicGF0aCI6Ii81NzUxNTgxMi80MzQ2NTY0ODgtZTFhNWFkMGItNmVkMi00OThiLTlkYmEtOTgyOTYzZTRjZWE4Lm1wND9YLUFtei1BbGdvcml0aG09QVdTNC1ITUFDLVNIQTI1NiZYLUFtei1DcmVkZW50aWFsPUFLSUFWQ09EWUxTQTUzUFFLNFpBJTJGMjAyNTA0MTclMkZ1cy1lYXN0LTElMkZzMyUyRmF3czRfcmVxdWVzdCZYLUFtei1EYXRlPTIwMjUwNDE3VDA2MDg0MlomWC1BbXotRXhwaXJlcz0zMDAmWC1BbXotU2lnbmF0dXJlPWJkZjg1MTUwMzg3Y2M0NGE3NzVkNGIyNWE0ZjY3YWE5NzA3NWE3OGVjMWU2YmMxNjU3YzczOWZlYTgzYTIzYzcmWC1BbXotU2lnbmVkSGVhZGVycz1ob3N0In0.5tEs-p7NUQrqj4a5AkHO1Q8tR2OndeYK9Us9EA5uGdg" controls="controls" muted="muted" class="d-block rounded-bottom-2 border-top width-fit" style="max-height:640px; min-height: 200px"></video>

## 安装

我们提供两种安装方法。方法2（使用uv）推荐用于更快的安装和更好的依赖管理。

### 方法1：使用conda

1. 创建一个新的conda环境：

```bash
conda create -n open_manus python=3.12
conda activate open_manus
```

2. 克隆仓库：

```bash
git clone https://github.com/raydoomed/OpenManus.git
cd OpenManus
```

3. 安装依赖：

```bash
pip install -r requirements.txt
```

### 方法2：使用uv（推荐）

1. 安装uv（一个快速的Python包安装和解析器）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. 克隆仓库：

```bash
git clone https://github.com/raydoomed/OpenManus.git
cd OpenManus
```

3. 创建一个新的虚拟环境并激活它：

```bash
uv venv --python 3.12
source .venv/bin/activate  # 在Unix/macOS上
# 或在Windows上：
# .venv\Scripts\activate
```

4. 安装依赖：

```bash
uv pip install -r requirements.txt
```

### 浏览器自动化工具（可选）
```bash
playwright install
```

## 配置

Nephesh需要配置它使用的LLM API。按照以下步骤设置您的配置：

1. 在`config`目录中创建一个`config.toml`文件（您可以从示例复制）：

```bash
cp config/config.example.toml config/config.toml
```

2. 编辑`config/config.toml`以添加您的API密钥并自定义设置：

```toml
# 全局LLM配置
[llm]
model = "gpt-4o"
base_url = "https://api.openai.com/v1"
api_key = "sk-..."  # 替换为您的实际API密钥
max_tokens = 4096
temperature = 0.0

# 特定LLM模型的可选配置
[llm.vision]
model = "gpt-4o"
base_url = "https://api.openai.com/v1"
api_key = "sk-..."  # 替换为您的实际API密钥
```

## 快速开始

一行代码运行Nephesh：

```bash
python main.py
```

然后通过终端输入您的需求！

对于MCP工具版本，您可以运行：
```bash
python run_mcp.py
```

对于Web界面版本，您可以运行：
```bash
python run_web.py
```

对于不稳定的多代理版本，您也可以运行：

```bash
python run_flow.py
```

## 如何贡献

## 社区

## 赞助商
