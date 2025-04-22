# OpenManus 项目开发计划

## 项目概述

OpenManus 是一个功能强大的 AI 代理系统，旨在通过多种工具完成复杂任务。系统由多个组件构成，包括各种代理(Agent)类型、工具(Tool)集合以及执行流程(Flow)管理。
- 后端核心文件：`app/agent/manus.py` - Manus代理实现
- 后端运行文件：`main.py` - 项目入口点
- 每次完成一个开发必须进行readme.md更新到最新状态

## 系统架构

- **代理(Agent)系统**：`app/agent/` 目录
  - 基础代理：`app/agent/base.py`
  - Manus代理：`app/agent/manus.py`
  - 浏览器代理：`app/agent/browser.py`
  - MCP代理：`app/agent/mcp.py`
  - ReAct代理：`app/agent/react.py`
  - SWE代理：`app/agent/swe.py`
  - 工具调用代理：`app/agent/toolcall.py`

- **执行流程(Flow)管理**：`app/flow/` 目录
  - 基础流程：`app/flow/base.py`
  - 规划流程：`app/flow/planning.py`
  - 流程工厂：`app/flow/flow_factory.py`

- **工具(Tool)集合**：`app/tool/` 目录
  - 基础工具：`app/tool/base.py`
  - Bash工具：`app/tool/bash.py`
  - 浏览器工具：`app/tool/browser_use_tool.py`
  - 聊天完成工具：`app/tool/create_chat_completion.py`
  - 深度研究工具：`app/tool/deep_research.py`
  - 文件操作工具：`app/tool/file_operators.py`
  - MCP工具：`app/tool/mcp.py`
  - 规划工具：`app/tool/planning.py`
  - Python执行工具：`app/tool/python_execute.py`
  - 字符串替换编辑器：`app/tool/str_replace_editor.py`
  - 终止工具：`app/tool/terminate.py`
  - 工具集合：`app/tool/tool_collection.py`
  - 网络搜索工具：`app/tool/web_search.py`
  - 搜索引擎：`app/tool/search/` 目录

- **提示词(Prompt)模板**：`app/prompt/` 目录
  - 浏览器提示词：`app/prompt/browser.py`
  - 思维链提示词：`app/prompt/cot.py`
  - Manus提示词：`app/prompt/manus.py`
  - MCP提示词：`app/prompt/mcp.py`
  - 规划提示词：`app/prompt/planning.py`
  - SWE提示词：`app/prompt/swe.py`
  - 工具调用提示词：`app/prompt/toolcall.py`

- **沙箱(Sandbox)系统**：`app/sandbox/` 目录
  - 沙箱客户端：`app/sandbox/client.py`
  - 沙箱核心：`app/sandbox/core/` 目录
    - 沙箱实现：`app/sandbox/core/sandbox.py`
    - 终端实现：`app/sandbox/core/terminal.py`
    - 异常处理：`app/sandbox/core/exceptions.py`
    - 管理器：`app/sandbox/core/manager.py`

- **MCP系统**：`app/mcp/` 目录
  - 服务器：`app/mcp/server.py`

- **LLM处理**：`app/llm.py` - 大型语言模型交互处理
- **配置管理**：`app/config.py` - 系统配置
- **类型定义**：`app/schema.py` - 数据模型和类型定义
- **异常处理**：`app/exceptions.py` - 自定义异常
- **日志系统**：`app/logger.py` - 日志处理

## 后端开发计划

### 1. Manus 代理增强 (文件: `app/agent/manus.py`)

- [ ] 增加`act`方法优化，提升工具选择策略
- [ ] 添加任务规划能力，自动分解复杂任务，与`app/flow/planning.py`集成
- [ ] 添加记忆压缩和摘要功能，优化长对话处理
- [ ] 集成所有可用工具，包括`WebSearch`(`app/tool/web_search.py`)、`DeepResearch`(`app/tool/deep_research.py`)、文件操作等
- [ ] 增加自我评估功能，对完成任务质量进行自评
- [ ] 集成沙箱(Sandbox)功能，实现安全的代码执行环境（暂时不集成，后续再说），涉及`app/sandbox/`目录
- [ ] 整合MCP(Model Context Protocol)客户端，支持与外部MCP服务器交互，涉及`app/tool/mcp.py`和`app/mcp/server.py`

### 2. 系统集成增强

- [ ] 完善 MCP 客户端集成，实现与外部服务无缝连接，涉及`app/agent/mcp.py`和`app/tool/mcp.py`
- [ ] 增加多代理协作能力，使不同专长代理能协同工作，修改`app/flow/`下的相关文件
- [ ] 优化沙箱环境，提升代码执行安全性和效率，涉及`app/sandbox/core/`下的文件
- [ ] 增强浏览器自动化能力，支持更复杂的网页交互，修改`app/tool/browser_use_tool.py`和`app/agent/browser.py`

### 3. 性能优化

- [ ] 优化 LLM 调用策略，减少不必要的 API 请求，修改`app/llm.py`
- [ ] 实现中间结果缓存机制，避免重复计算，涉及多个工具文件
- [ ] 添加流式处理大型文档的能力，修改文件操作相关工具(`app/tool/file_operators.py`和`app/tool/str_replace_editor.py`)
- [ ] 优化工具执行并行能力，支持并发任务，修改`app/tool/tool_collection.py`

### 4. 用户交互改进

- [ ] 增加更多反馈机制，提高代理任务透明度，修改`app/agent/base.py`和`app/agent/manus.py`
- [ ] 改进错误处理和恢复机制，修改`app/exceptions.py`和各代理文件
- [ ] 添加用户确认步骤，允许用户干预关键决策，修改`app/agent/manus.py`
- [ ] 实现进度报告功能，提供任务执行状态，修改`app/agent/base.py`和`app/agent/manus.py`

### 5. 工具扩展 (目录: `app/tool/`)

- [ ] 增加数据库操作工具 (新建`app/tool/database.py`)
- [ ] 开发图像处理工具 (新建`app/tool/image_processing.py`)
- [ ] 增强文件处理工具，支持更多格式，修改`app/tool/file_operators.py`
- [ ] 添加音频处理工具 (新建`app/tool/audio_processing.py`)
- [ ] 开发 API 调用封装工具 (新建`app/tool/api_caller.py`)

### 6. 测试和文档

- [ ] 编写全面的单元测试和集成测试 (新建`tests/`目录下相关文件)
- [ ] 创建详细 API 文档 (新建`docs/api/`目录)
- [ ] 编写用户使用指南和示例 (新建`docs/user_guide/`和`examples/`目录下文件)
- [ ] 实现自动化测试流程 (新建`tests/automation/`目录)

## 前端开发计划

### 1. 用户界面开发

- [ ] 设计并实现主界面布局，包括聊天区、工具面板和状态展示
- [ ] 开发响应式设计，支持桌面和移动设备
- [ ] 实现深色/浅色主题切换功能
- [ ] 设计良好的加载状态和过渡动画
- [ ] 创建代理执行流程可视化面板，显示当前任务状态
- [ ] 设计沙箱和MCP连接状态指示器

### 2. 聊天界面功能

- [ ] 实现富文本消息显示，支持代码高亮和 Markdown
- [ ] 添加消息历史浏览和搜索功能
- [ ] 实现文件上传和预览能力
- [ ] 开发消息引用和回复功能
- [ ] 设计代理推理过程展示面板，可视化思考步骤
- [ ] 实现记忆摘要展示，帮助用户了解代理记住的关键信息
- [ ] 添加长文档支持，包括分段加载和阅读进度指示

### 3. 工具可视化

- [ ] 为每种工具创建可视化调用界面
- [ ] 显示工具执行进度和结果
- [ ] 开发工具执行历史记录
- [ ] 实现工具参数配置界面
- [ ] 创建WebSearch和DeepResearch结果的结构化展示
- [ ] 设计浏览器自动化操作可视化界面，显示网页交互过程
- [ ] 开发沙箱代码执行环境的监控界面，展示代码运行状态
- [ ] 实现MCP工具集的动态加载和展示

### 4. 任务和计划管理

- [ ] 创建会话保存和恢复功能
- [ ] 实现会话分享和导出能力
- [ ] 开发会话模板功能
- [ ] 添加会话统计和分析视图
- [ ] 设计任务规划可视化界面，以树状或流程图形式展示任务分解
- [ ] 实现计划执行跟踪，显示当前进度和下一步操作
- [ ] 开发多代理协作面板，展示不同代理间的交互

### 5. 用户设置和个性化

- [ ] 设计用户配置界面
- [ ] 实现 API 密钥管理
- [ ] 添加自定义代理配置功能
- [ ] 开发快捷键和界面个性化设置
- [ ] 创建代理行为偏好设置，允许用户调整代理的决策风格
- [ ] 实现工具使用权限控制，允许限制特定工具的使用
- [ ] 开发自定义提示词模板管理

### 6. 高级功能和集成

- [ ] 实现与后端 API 的无缝集成
- [ ] 开发用户认证和权限管理
- [ ] 添加敏感信息保护措施
- [ ] 实现安全日志和审计功能
- [ ] 开发性能指标监控面板，跟踪API调用和资源使用
- [ ] 创建错误诊断和恢复界面
- [ ] 实现用户确认流程UI，允许代理在关键步骤请求用户确认
- [ ] 设计并行任务监控界面，显示多个并行执行的工具状态

## 优先级任务

### 后端

1. 完善 Manus 代理核心功能，特别是任务规划和推理能力 (`app/agent/manus.py`)
2. 扩展工具集合，特别是搜索和深度研究工具 (`app/tool/web_search.py`和`app/tool/deep_research.py`)
3. 优化用户交互和错误处理机制 (`app/agent/base.py`和`app/exceptions.py`)
4. 实现多代理协作系统 (`app/flow/`目录)

### 前端

1. 开发基础聊天界面和消息展示
2. 实现工具调用可视化和结果展示
3. 设计任务规划和执行流程可视化
4. 创建沙箱和MCP连接状态监控界面（沙箱暂时不创建，后续再说）
5. 开发用户认证和设置界面

## 技术债务

- 重构工具调用机制，使其更加模块化 (`app/tool/tool_collection.py`和`app/agent/toolcall.py`)
- 优化内存管理，减少长时间运行时的内存占用 (`app/llm.py`和`app/agent/base.py`)
- 标准化错误处理流程 (`app/exceptions.py`)
- 重构配置管理系统 (`app/config.py`)
- 统一前后端数据交换格式 (`app/schema.py`)
- 提升组件复用率

## 下一步行动计划

1. 对 Manus 类进行功能扩展实现，添加上述缺失功能 (`app/agent/manus.py`)
2. 开发前端基础界面框架和核心聊天功能
3. 创建测试套件验证新功能 (`tests/`目录)
4. 编写详细文档说明使用方法和最佳实践 (`docs/`目录)
5. 逐步集成更多高级工具到 Manus 代理 (`app/tool/`目录)
6. 实现前后端基础集成，展示工具执行能力

## 开发规则
1. 不准使用模拟数据进行开发，必须使用真实的LLM交互数据
2. 不准创建测试脚本，一切以main.py实际后端结果来解决问题
3. 不准使用任何硬编码方式
