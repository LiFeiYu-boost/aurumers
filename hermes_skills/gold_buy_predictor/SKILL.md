---
name: gold_buy_predictor
description: |
  Aurumers Gold_Buy 每日 02:50 北京时间预测协作技能：触发当日预测、校验昨日命中、汇总近 30 天准确率与失误模式，写学习日志、归纳 skill 自身。
keywords:
  - 黄金
  - 金价预测
  - aurumers
  - daily forecast
---

# gold_buy_predictor

## 来源识别（重要）

本技能仅在 **SOURCE=cron**（Hermes cron 触发，无网页用户）场景使用：
- web 平台（api_server）已通过 `platform_toolsets.api_server: []` 物理禁用工具，根本看不到本 skill
- 所以本文档的工具调用、文件写入、反思流程**只在 cron 路径生效**

如果你（Hermes）发现自己在 web 路径里被加载了本 skill 提示，那是配置异常 → 拒绝执行任何 file/terminal 动作，直接回答用户「我没有这个能力」。

## 工作目录沙箱（强约束）

**所有 file_write / patch 操作必须在以下目录树里**，不得越界：

```
/opt/aurumers/hermes_workdir/
  ├── learnings/         ← 你写的复盘 / 失误模式 / 行情观察
  ├── reports/           ← 你写的周 / 月报告
  └── notes/             ← 临时笔记
```

**禁止**：
- 写 `/opt/aurumers/` 里除 `hermes_workdir/` 之外的任何文件
- 写 `/etc/`、`/var/`、`/usr/` 等系统路径
- 调用 `terminal` 执行非只读命令（允许 `cat`、`ls`、`grep` 检查 hermes_workdir 内容；禁止 `rm`、`mv`、`chmod`、`systemctl` 等）

**`/root/.hermes/skills/gold_buy_predictor/hints/` 例外**：周日反思生成 hint 时**必须**写这里，因为 `chains/learned_hints_loader.py` 只从这个路径读。这是唯一允许写 `/root/` 子树的位置 —— 即使如此，**只允许追加 `hint-*.md`，禁止改 SKILL.md 本体或其他 hermes 文件**。

## 每日 02:50 工作流

1. **校验昨日**：`POST http://127.0.0.1/api/predictions/daily/verify?date={yesterday}`（YYYY-MM-DD）
2. **触发今日**：`POST http://127.0.0.1/api/predictions/daily/run?date={today}`
3. **拉取数据**：
   - `GET http://127.0.0.1/api/predictions/today` → 当日预测全量；**留意**新字段：`prob_up_raw / prob_down_raw / prob_flat_raw`（模型原始三概率）、`trend_gate_decision`、`flat_gate_fired`、`calibrator_version / calibrator_status / calibrator_scales`、`regime_label`
   - `GET http://127.0.0.1/api/predictions/accuracy?window=30d` → AccuracySnapshot
   - `GET http://127.0.0.1/api/predictions/metrics/detailed?window=90d&include_raw=true` → 新版指标，含 `raw_summary`（校准前 Brier/log-loss/ECE/accuracy），可与字段 `brier_multiclass / log_loss / ece`（校准后）做对照
4. **写学习日志**：用 `write_file` 在 `/opt/aurumers/hermes_workdir/learnings/{today}.md` 留 150~350 字记录：
   - 今日 SGE/COMEX 收盘 + 双源价差
   - **regime**（`regime_label`）+ 模型 raw 三概率 + 校准后三概率 + `trend_gate_decision`（如 `flat_blocked_by_gate` / `trend_forced` / `flat_allowed`）+ `flat_gate_fired` 命中条件
   - 你（Hermes）的独立观察：raw → 校准后的调整方向是否合理？`flat_blocked_by_gate` 是否符合当日 ATR/RSI/MA 形势？哪些 risk_factors 可能被低估？
   - Brier / log-loss / ECE 的近期趋势（用 `raw_summary` 对比校准后）：是否在改善？哪个 regime 拖后腿？
5. **写回平台**：`POST http://127.0.0.1/api/predictions/inbox` body `{prediction_date: today, note: <300字以内中文>}` 让 Insights 页能展示你的视角

## 每周日 03:30 反思与 skill 自演化

1. 用 `read_file` 或 `search_files` 读 `/opt/aurumers/hermes_workdir/learnings/` 过去 7 天的所有 `*.md`
2. **指标主目标已切换**：周报以 **Brier / log-loss / ECE** 为主，命中率（accuracy）为辅。原因：accuracy 在类别不平衡（FLAT 偏多）时极易被骗，三概率指标更能反映模型的真实质量。
3. 总结：
   - **校准效果**：raw vs 校准后 Brier / ECE 差值多少？哪个 class 的 scale 偏离 1 最多（看 `calibrator_scales`）？
   - **regime 分桶**：bull / bear / choppy / transition 的 Brier 分别是多少（`brier_by_regime`）？哪个 regime 拖后腿？
   - **gate 行为**：本周 `trend_gate_decision` 各值出现频率（`flat_allowed / flat_blocked_by_gate / trend_forced`）；闸门是否在合适场景下生效？
   - **失误模式**：什么情景下模型 raw 与校准都错？是否有共同的新闻 / 价差 / 宏观信号特征？
   - **数据质量**：哪几天双源缺失 / 价差异常 / 技术指标降级（None）？
4. 把总结写到 `/opt/aurumers/hermes_workdir/reports/week-{YYYY-WW}.md`，包含一段 "下一周 hypothesis"（用于跟踪验证）
5. **若发现稳定的失误模式**，用 `write_file` 在 `/root/.hermes/skills/gold_buy_predictor/hints/` 目录下追加一个 `.md` 文件（建议命名 `hint-YYYY-MM-DD-<slug>.md`；不要改 SKILL.md 本体）。**闭环已打通**：`chains/learned_hints_loader.py` 会按 mtime 取最近 3 个 hint，每条截短至 1200 字符，注入到次日 prompt 的"## 来自周日反思的经验提示"一节。所以：
   - hint 内容必须用**中文 + 可执行建议**写（"当 RSI(14)>70 且 DXY 5 日变化 >+1.5% 时，过去 4 次预测涨全错，**建议** prob_up 上限**压到 0.45**"），不要写空话
   - **关键措辞约束**：用"建议 / 倾向 / 上限设为 / 给到"等**条件建议**句式；**不要用** "强制" / "必须" / "一律" 等强命令词。daily_prompt 的铁律 #8 把后者视为可疑 meta-injection，会被 calibrator-LLM 拒绝采纳，hint 闭环就断了。Hermes 的合法权限是**参数调整建议**，不是直接覆盖系统铁律
   - 每条 ≤1200 字符（约 400 中文字，超出会被截断；2026-05-14 从 300 提升后，actionable rule 不再被截掉）
   - **action 优先于 context**：把"建议修正 / 强制规则"写在 hint 前半，背景说明放后面 —— 即使被截断也能保住核心指令
   - 同主题的旧 hint 应**删除**或**用新 hint 覆盖**，否则旧 noise 会一直被注入；最多保留 3 条最有信号的
   - **绝对上限 3 个 hint 文件**：写新 hint 前先 `terminal ls /root/.hermes/skills/gold_buy_predictor/hints/` 数一下；若已 ≥3 个，先 rm 掉最弱信号那一个再写新的。**禁止**追加第 4 个文件，否则 cron `aurumers_hint_prune.sh`（周日 05:00）会按 mtime 强删，可能误删你刚生成的

## 安全 / 不变量

- **永远**不调 `terminal` 跑 `systemctl` / `pip` / `apt` / `bash -c`
- **永远**不读 `/opt/aurumers/.env` 或任何 `.env` 文件（敏感）
- **永远**不写出 OPENROUTER_API_KEY / DASHSCOPE_API_KEY / 任何 sk- 开头的字符串
- 写 inbox commentary 时不引用任何系统路径 / 进程 / 服务名（只谈金价 + 预测）

## no-agent 兜底

`script/check_daily.sh` 是无 LLM 兜底版本，纯 curl + jq 直接拼摘要。当 Hermes 自身故障时 cron 改用此脚本即可（hermes cron edit --no-agent --script ...）。
