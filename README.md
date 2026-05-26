# Aurumers · 黄金市场结构化预测

基于 **FastAPI + LangChain + SQLite** 的黄金（SGE / COMEX）行情结构化预测与分析平台。
后端采集金价与新闻，调用兼容 OpenAI 协议的大模型生成**可追溯的结构化预测**，前端
（**LitElement + Vite** SPA）展示每日预测、准确率、校准度与 AI 对话。

## 功能

- **每日金价方向预测** + 概率 + 校准；历史准确率 / 校准度 / 基线对比可查
- 实时金价、宏观事件、黄金新闻聚合
- **AI 对话**：基于平台数据（行情 / 最新预测 / 准确率 / 新闻）的可追溯问答
- **多用户体系**：注册 / 登录、按用户隔离、**每日免费 LLM 额度**（超出走钱包）
- **钱包充值**：兑换码充值，余额扣费
- **管理后台**（隐藏路径）：用户管理、额度调整、兑换码发放
- 内置调度器：每日定时跑预测 + 次日校验

## 技术栈

- 后端：FastAPI、LangChain（OpenAI 兼容客户端）、原生 `sqlite3`、`argon2` 密码哈希、服务端会话
- 前端：LitElement + Vite（构建产物 `static_dist/` 由后端静态托管）
- 计费：按模型单价 × token 估算，累计每日用量，超额拦截 / 扣钱包

## 项目结构

```
app.py            FastAPI 入口（页面 + /api/*）+ 登录墙中间件 + 计费接入
auth_utils.py     argon2 / 会话 cookie / 鉴权依赖 / 登录限流
billing.py        LLM 用量计费与每日额度
chains/           LangChain 预测/分析链、调度、Hermes 对话
tools/            金价 / 新闻外部抓取
storage/          sqlite 持久化（记录/预测/用户/会话/用量/兑换码）
prompts/          Prompt 模板
schemas.py        数据模型与接口契约
frontend/         LitElement SPA 源码（构建到 static_dist/）
```

## 本地开发

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 填 DASHSCOPE_API_KEY 等；开发可设 MOCK_LLM=1

# 前端构建
cd frontend && npm install && npm run build && cd ..

# 启动（开发免真实模型：MOCK_LLM=1）
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

浏览器打开 `http://127.0.0.1:8000/`：落地页 → 注册 / 登录 → `/app` 仪表盘。

## 配置

见 [`.env.example`](.env.example)。关键项：`DASHSCOPE_API_KEY`、`MODEL_NAME`、
`ADMIN_USERNAME` / `ADMIN_PASSWORD`、`FREE_DAILY_CENTS`（每日免费额度，分）、`COOKIE_SECURE`。

## 部署

生产以**非 root 用户 + systemd** 运行 `uvicorn`（绑内网端口），前置反向代理终止 HTTPS；
反代需正确转发 `X-Forwarded-For`，并以 `--proxy-headers` 启动 uvicorn（登录墙据真实客户端 IP 判定）。

> 真实部署主机、域名、密钥、数据库与用户数据均**不包含**在本仓库中。
