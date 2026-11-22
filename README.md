# FlowMind

自托管的自动化工作流与 AI Agent 平台。可视化编排 DAG，内置 RAG 知识库、多 Agent 协作、工具审批与运行审计，适合在本地或私有云部署。

## 已实现能力

- 可视化工作流画布：节点/连线右键菜单、键盘删除、自动布局、版本化 JSON DSL
- 手动 / 定时 / Webhook 触发，SSE 实时日志，审批中断与恢复
- LLM、Agent、Agent 团队（Supervisor / 自由图）、HTTP、工具、MCP、条件、循环、子工作流、代码节点
- 模型配置支持 DeepSeek / OpenAI 兼容 / Ollama，API Key 加密保存
- 多租户、RBAC、邀请、邮箱验证、审计与用量统计
- Dify 风格工作空间角色：所有者 / 管理员 / 编辑者 / 运行者 / 查看者，后端权限矩阵强制校验
- 内置 RAG：PDF / DOCX / MD / TXT / XLSX / CSV，pgvector + 全文混合检索与引用
- Dify 风格知识库：上传/拖拽、解析状态、分块预览与编辑、重解析、检索测试与评分
- 知识库元数据过滤与重排序：eq / ne / contains / in / gte / lte，keyword 与 LLM rerank
- Dify 风格 Agent：角色、模型、工具、知识库、JSON Schema 配置，多轮调试
- 顶部导航工作台：概览 / 工作流 / 运行 / 审批 / 知识库 / Agent / 工具 / 插件 / 设置
- Dify 风格插件市场：搜索、安装、配置、测试、卸载，安装后自动生成可绑定 Agent 的工具
- 工作流模板中心：Webhook 接收、HTTP 抓取、LLM 总结、人工审批、定时简报等模板一键创建
- 独立创建工作台：从模板、空白画布、导入 JSON DSL 或复制已有流程开始，创建前可预览节点路径
- Webhook 可视化调试：创建地址、复制 URL、发送测试事件、查看运行结果
- 发布可见性：草稿/已发布状态栏、版本记录、发布后一键运行与触发器入口
- 内置演示 MCP 服务：支持工具发现、添加为 Agent 工具与直接测试
- Agent 会话持久化：会话列表、历史消息恢复、token 统计、删除会话
- HTTP 工具 OAuth2 Authorization Code：加密保存 client secret / access / refresh token，自动注入 Bearer token
- 代码节点独立 Runner 沙箱
- Docker Compose 部署，OTel / Langfuse 可选接入

## 快速上手（4 步）

1. 登录后先到「设置 → 模型」确认默认 Chat 模型可用，点击「测试连接」。
2. 到「知识库」新建空间并上传资料，解析完成后在「检索测试」输入真实问题，确认召回与引用。
3. 到「工作流」新建流程，拖入开始、LLM / Agent、结束节点并连线；校验通过后发布版本。
4. 运行工作流，在「运行记录」查看输出与执行轨迹；遇到中高风险工具调用时到「审批中心」处理。

每个模块页面顶部都有对应的「推荐操作路径」，不确定下一步时照着编号操作即可。

## 本地开发

前置：Python 3.11、Node 22。没有 Docker 时使用 SQLite + 本机 Ollama 运行单机演示；完整联调需要 Postgres / Redis / MinIO / Runner。

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e "backend[dev]"
.\.venv\Scripts\python -m uvicorn app.main:app --reload --reload-dir backend --port 8020
```

安装为可编辑包后**不需要**设置 `PYTHONPATH`。如果未执行 `pip install -e`，改用：

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload --reload-dir backend --app-dir backend --port 8020
```

另开终端启动前端：

```powershell
cd web
npm install
npm run dev
```

- 前端：`http://localhost:5180`
- 后端：`http://localhost:8020`
- Vite 将 `/api` 与 `/healthz` 代理到 `http://127.0.0.1:8020`
- 如端口被占用，设置 `$env:VITE_API_TARGET='http://localhost:8020'` 后重启前端

默认 `.env` 不存在时后端使用 SQLite（`flowmind.db`）和本机 Ollama：

```powershell
ollama pull qwen2.5:7b
ollama pull bge-m3
```

首次启动会创建演示账号：`demo@flowmind.dev / password123`。开发模式下注册响应会返回 `verification_token`，也可打开 `/verify?token=...` 完成邮箱验证。

构建前端：

```powershell
cd web
npm run build
```

后端会自动托管 `web/dist`（如果存在），此时可直接访问 `http://localhost:8020`。

## OAuth2 工具接入

1. 在「工具 / MCP」页新建 OAuth 连接，填写 Authorization URL、Token URL、Client ID、Client Secret 与 scopes；Token 端点认证方式支持 `client_secret_post` 与 `client_secret_basic`。
2. 在 OAuth 服务商处登记回调地址：
   `http://localhost:8020/api/v1/oauth/callback`
   （生产环境改为 `PUBLIC_BASE_URL` + `/api/v1/oauth/callback`）
   使用 Docker Compose 时回调地址为 `http://localhost:8000/api/v1/oauth/callback`。
3. 点击「授权」，完成后会跳回 `WEB_BASE_URL` 下的 `/tools?oauth=success`（Compose 下为 `http://localhost:8080/tools`）。
4. 新建 HTTP 工具时选择该连接，运行时自动注入 `Authorization: Bearer <access_token>`；过期会使用 refresh token 自动刷新。

相关环境变量：

```dotenv
PUBLIC_BASE_URL=http://localhost:8020
WEB_BASE_URL=http://localhost:5180
APP_ENCRYPTION_KEY=请填入 32 字节 base64 密钥
```

## 知识库元数据与重排序

- 文档列表点击「元数据」，保存 JSON，例如：`{"category": "faq", "department": "support", "priority": 2}`
- 检索面板添加过滤条件，多个条件按 AND 组合；key 支持点路径，例如 `source.team`
- `in` 操作符在界面中用逗号分隔多个值
- 重排序可选：不重排、关键词重排（本地、无需模型）、模型重排（使用 Chat 模型，失败时保留原顺序并返回 `rerank_error`）

检索请求示例：

```json
{
  "query": "退款多久到账",
  "top_k": 5,
  "metadata_filters": [{"key": "category", "operator": "eq", "value": "faq"}],
  "rerank_mode": "llm"
}
```

## 发布与版本

工作流编辑器顶部新增持久发布状态栏：

- 草稿状态：明确提示“尚未发布”，并提供「立即发布」
- 已发布状态：显示版本号、发布时间，并提供「运行此版本」
- 「版本记录」：查看每次发布的版本号、时间、节点数、DSL Hash 与完整 DSL
- 「触发器」：创建和测试 Webhook、查看外部调用方式

发布成功后会自动刷新版本列表；运行时会绑定当前已发布版本。

## Webhook 快速体验

1. 打开「工作流 → Webhook 接收示例」。
2. 点击右上角「触发方式」，复制页面中的 Webhook URL。
3. 外部系统直接 POST JSON 即可触发（演示地址默认不要求签名）：

```powershell
curl -X POST "<复制出来的 Webhook URL>" `
  -H "Content-Type: application/json" `
  -d '{"event":"demo.order.created","data":{"order_id":"A1001","amount":299}}'
```

4. 接口会返回 `run_id`，在「运行记录」中可以看到 `inputs.webhook` 与最终输出。

如果创建 Webhook 时勾选「要求 HMAC 签名」，外部请求需要额外发送：

```text
x-webhook-signature: sha256=<HMAC_SHA256(secret, raw_body)>
```

页面里的「测试」按钮会直接创建一次运行，不需要手工计算签名。

## 创建工作台

「工作流 → 新建工作流」会进入独立创建工作台，支持四种起点：

- 从模板创建：搜索和分类筛选，选中后右侧实时预览节点路径
- 空白画布：预置开始与结束节点
- 导入 DSL：粘贴完整 JSON DSL，解析成功后显示节点数量
- 复制已有：基于现有工作流创建独立副本

创建前可以修改名称和说明，右侧摘要会显示来源、节点路径、触发方式和模板亮点。创建后直接进入画布，草稿不会自动发布。

## 工作流模板

工作流页面内置 10 个模板，点击「使用模板」即可生成并进入画布：

基础与入门：

- Webhook 接收示例：无需模型，接收 JSON 并输出 payload
- HTTP 数据抓取：HTTP 节点 + 输出映射
- LLM 文本总结：自动选择默认模型
- 人工审批示例：LLM + 审批中断与恢复
- 定时数据简报：HTTP + LLM，可继续配置 Cron

复杂流程：

- 客服工单智能分诊：分类、人工确认、生成客服回复
- 内容创作与审核发布：双阶段 LLM、人工确认、HTTP 发布
- 运营数据双阶段分析：HTTP 抓取、指标提取、管理层简报
- 多智能体深度研究：主管 Agent + 多成员协作 + 报告生成
- Webhook 订单自动处理：事件提取、审批、通知接口与处理回执

## 内置演示 MCP

1. 打开「工具 / MCP → MCP 服务」。
2. 点击「使用内置演示」，再点击「添加服务」。
3. 点击「发现工具」，可以看到 `echo`、`add`、`server_time`。
4. 点击「添加为工具」，然后到「工具」标签页点击「测试」。

内置演示地址由当前访问域名自动生成：`/api/v1/mcp/demo`。

## 角色与权限

工作空间支持 5 种角色，权限同时在后端强制校验和前端按钮可见性中生效：

| 角色 | 核心能力 |
| --- | --- |
| 所有者 | 全部权限，管理成员、管理员、模型凭据与工作空间设置 |
| 管理员 | 管理资源、成员、模型/密钥和审计，不能修改所有者 |
| 编辑者 | 创建/编辑/发布工作流、知识库、Agent、工具与插件 |
| 运行者 | 运行已发布工作流、查看运行记录、处理审批 |
| 查看者 | 只读浏览工作流、运行、知识库、Agent 与插件市场 |

设置页「成员」支持邀请、修改角色、移除成员；「权限」标签展示每个角色的权限矩阵。当前角色会显示在顶部用户信息和设置页中。

## 插件市场

- 内置 9 个插件：计算器、当前时间、文本统计、JSON 提取、正则提取、Base64 编解码、维基百科搜索、HTTP 连接器、Webhook 通知。
- 安装插件会自动创建一个同名 `plugin` 类型工具，并出现在 Agent 的「可用工具」列表中。
- 需要外部地址的插件会在安装/配置时生成表单，例如 HTTP 连接器与 Webhook 通知。
- 每个已安装插件都可以在页面内直接测试，返回结果会以结构化 JSON 展示。
- 卸载插件会同时删除对应工具，避免 Agent 继续调用失效能力。
- 插件定义位于 `backend/app/services/plugins.py`，新增内置插件只需追加定义与执行分支。

## Agent 会话

- 调试面板顶部可切换历史会话、新建对话、删除会话
- 每次消息都会持久化完整消息轨迹与 token 用量
- 切换到历史会话即可恢复上下文，刷新页面或换浏览器仍可继续对话
- 会话按 Agent 隔离，并按更新时间倒序返回最近 100 条

## Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up --build
```

- 控制台：`http://localhost:8080`
- API：`http://localhost:8000`
- MailHog：`http://localhost:8025`
- MinIO 控制台：`http://localhost:9001`
- Runner：`http://localhost:9100`

Compose 中 API/Worker 使用 Postgres、Redis、MinIO；代码节点 Runner 独立运行，只读文件系统且无网络。

## 种子数据

```powershell
.\.venv\Scripts\python backend/scripts/seed.py
```

Docker 中执行：

```powershell
docker compose exec api python scripts/seed.py
```

## 测试

```powershell
.\.venv\Scripts\python -m pytest backend/tests -q
.\.venv\Scripts\ruff check backend/app backend/tests backend/scripts
cd web
npm install
npm run test:e2e:install   # 首次安装 Chromium
npm run build
npm run test:e2e           # Playwright 全量 E2E
```

一条命令跑完整检查：

```powershell
.\scripts\test-all.ps1
```

Playwright 测试覆盖：

- 登录与仪表盘
- 知识库创建、从非文档 Tab 触发上传、解析完成、分块预览、删除
- 工作流创建、发布、版本记录、Webhook 测试
- 插件市场与已安装插件测试
- MCP 发现工具、添加为工具、执行测试
- 工作空间角色矩阵与成员管理页面

旧的轻量冒烟脚本仍保留：

```powershell
cd web
npm run test:smoke
```

## 页面截图

Playwright 可以自动登录并截取整个项目的主要页面、Tab 和移动端视图：

```powershell
cd web
npm run screenshots
```

默认输出到项目根目录的 `screenshots/`，包含：

- 登录、仪表盘、工作流列表、创建工作台、画布
- 运行记录、运行详情、审批中心
- 知识库文档 / 检索测试
- Agent 配置 / 调试
- 工具 / MCP / OAuth
- 插件市场
- 设置 / 成员 / 权限矩阵
- 移动端主要页面

自定义输出目录：

```powershell
$env:SCREENSHOT_DIR="D:\FlowMind-Screenshots"
npm run screenshots
```

## 架构

```text
web/        React + Vite + React Flow 控制台
backend/    FastAPI + SQLAlchemy + Celery + 工作流/Agent/RAG 服务
runner/     代码节点独立沙箱服务
infra/      Caddy 反向代理
```

工作流层使用轻量异步 DAG 执行器；Agent 运行时位于 `backend/app/services/agent_runtime.py`。JSON DSL 是唯一事实源，发布后生成不可变版本，运行绑定版本 ID。

## 安全默认值

- 所有业务数据按 `tenant_id` 隔离；生产建议启用 PostgreSQL RLS
- HTTP 工具默认阻止私网、回环、链路本地与云元数据地址，支持租户域名白名单
- OAuth client secret / token 使用应用密钥加密存储，不通过 API 返回
- MCP 首版只支持 Streamable HTTP / SSE，不支持 stdio
- 代码节点仅支持标准库、无网络、非 root、只读文件系统、30 秒超时
- 中高风险写操作进入审批；审批超时默认拒绝
- 首版不做 OCR、SSO、计费、插件市场、移动端与跨运行 Agent 长期记忆

## 工作流编辑器快捷键

- 右键空白画布：添加节点
- 右键节点：编辑、复制、删除
- 右键连线：编辑源端口、删除连接
- Delete / Backspace：删除选中节点或连线
- Ctrl/Cmd+S：保存草稿