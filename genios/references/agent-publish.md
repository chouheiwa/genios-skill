# 智能体：配置、模型参数、发布与渠道审核

`scripts/genios_publish.py` 封装了整条链路。它以**平台草稿为准**读取模型（模型在界面或草稿里切换），只覆盖命令行传入的
提示词文件、`--max-tokens`、`--reasoning`、`--history-rounds`、问答库召回。

**发布保护**：草稿里思考模式不是 `disabled`、又没有显式传 `--reasoning` 时，脚本拒绝发布——界面上切换模型或思考开关
会改草稿，曾因此把不兼容的 `auto` 带上线。确认模型在 API 渠道支持后再用 `--reasoning` 明确指定。

## 配置读写

| Action | 参数 | 说明 |
|---|---|---|
| `CreateAppWithConfig` | `WorkspaceID, UserID(内部ID), Name, Description, Prompt, WorkflowIDs?, KnowledgeIDs?, OpenMessage?, OpenQuery?, OnlyDraft` | 不传 WorkspaceID 会落到个人空间 |
| `GetAppConfigDraft` | `AppID` | `Result.AppConfigDraft`：`ModelID`、`ModelConfig`、`PrePrompt`（提示词）、`WorkflowIDs`、`QADatasetIDs`、`QADatasetConfig` 等 |
| `SaveAppConfigDraft` | `AppID, AgentMode:"Single", AppConfigDraft` | 写草稿（界面看到的是草稿） |
| `PublishAppConfig` | `AppID, AgentMode:"Single", AppConfig` | 返回 `PublishID`；`ModelConfig.ReasoningMode` 必须是布尔值 |
| `ListAppPublishHistory` | `AppID, PageNumber, PageSize` | 每次发布的完整 `AppConfig`，用来确认线上到底是哪个模型/参数 |
| `DeleteApp` | `AppID` | |

写回时去掉只读字段：`UpdateTime ModelName SummaryModelName Version VersionDescription`。

## 发布到 API 渠道并等审核

**改完配置必须重新发布渠道**：API 渠道绑定的是某一次 `PublishID`，只 `PublishAppConfig` 不会影响线上对话。

1. `SaveAppBuiltinChannelPublishConfigDraft {AppID, ChannelCode:"api", BuiltinChannelConfigData:{APIPublishConfigData:{Enabled:true}}}`
2. `PublishAppChannel {AppID, BuiltinChannels:["api"], BuiltinChannelPublishConfigData:{APIPublishConfigData:{Enabled:true}}, Description}`
3. 轮询 `ListPublishAppChannelHistory {AppID, PageNumber, PageSize}`，找到对应 `PublishID`，
   `ChannelPublishStatusList[0].Status` 从 `InReview` 变为 `Success`（平台自动审核，实测 1.5—3 分钟，审核意见在 `StatusMessage`）。
4. `GetAppPublishedChannels {AppID}` 的 `PublishVersionInfoMap.api.PublishID` 是当前线上生效的版本。

审核通过前，对话 API 仍在跑旧版本——这期间测到的现象不代表新配置。

## API Key（端到端测试用）

- `CreateAppAPIKey {AppID, Expired, Description}`，`Expired` 必填：`0.5h 1h 6h 1d 7d 15d 1m 6m 1y forever`。返回 `APIKey`、`AppKeyID`。
- `ListAppAPIKey {AppID}` → `Result.AppAPIKeyInfos[]`（`APIKeyID`、`Description`、`ExpiredTime`，Key 本身已打码）。
- `DeleteAppAPIKey {AppID, APIKeyID}`（参数名 `APIKeyID`，不是 `AppKeyID`）。
- 测试 Key 写进项目外的文件（权限 600），描述里注明“临时”，用完按描述批量删除。

## 模型参数

- 可用模型及其参数范围：`POST /api/aigw?Action=ListModelByWorkspaceGrant&Version=2023-08-01`，看每个模型的
  `TokenConfig.MaxTokens`（上下限）、`TokenConfig.ContextTokens`、`FeaturesConfig`（`tool-call`、`reasoning`、`reasoning-switch`）、
  `ReasoningConfig.Switch.Types`、`StrategiesConfig`、`Parameter.Rules`（温度等范围）。
- `ModelConfig` 常用字段：`Temperature`、`TopP`、`MaxTokens`、`RoundsReserved`（带入上下文的历史轮数，默认 3，
  **上限 100，平台不做历史压缩**）、`Strategy`（`function_call` / `react`）、`ReasoningSwitchType`（`auto`/`enabled`/`disabled`）、
  `ReasoningMode`（界面上叫“长思考过程展示”，与开关一致：非 disabled 时为 true）。
- 切换模型后平台可能自动改 `Strategy`、`ReasoningSwitchType`，发布前用 `GetAppConfigDraft` 看一眼。
- 模型参数是否“能用”要以 API 渠道端到端为准：例如 doubao-seed-2-1-pro 的思考模式 `auto` 立即报
  “大模型接口调用出错”、`enabled` 60 秒无回复，只有 `disabled` 正常。

## 对话 API 端到端测试

```python
import os; os.environ["GENIOS_KEY_FILE"] = "<项目外的 key 文件>"
import genios_chat as ga   # scripts/genios_chat.py
conv = ga.create_conversation()
for evt in ga.chat_stream("我想登记一个安全隐患", conv):
    ...  # event: message / agent_thought（tool、tool_input）/ agent_thought_end（observation）/ qa_retrieve_end
```

- 用流式 `chat_stream`；阻塞模式在“模型 → 工作流 → 模型”链路上容易 504。
- `agent_thought` 的 `tool_input` 是智能体传给工作流的参数，`agent_thought_end.observation` 是工作流返回值；
  `qa_retrieve_end.docs.outputList[0].metadata.score` 是问答库命中分数。
- 回复为“大模型接口调用出错”时，先用 `genios_traces.py errors` 看上游原始报错，再按 pitfalls.md 第 5 条处理。
