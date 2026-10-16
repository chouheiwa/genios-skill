# 对话流型智能体：状态、路由、嵌入对话型智能体

需要**跨轮保存状态**（按剧本推进的陪练、分步表单、计数）时用对话流型（AppType `ChatFlow`）。它每轮都执行一遍画布，
并提供用户变量 + 变量赋值节点。对话型智能体做不到这一点：工作流返回值不进下一轮上下文（pitfalls.md 第 1 条）。

推荐组合：**对话流做外层**（状态、路由、确定性推进），用智能体节点调用已有的对话型智能体处理开放问答（提示词、问答库、
工作流都留在它那里）。反过来（对话型的 `AgentIDs` 里挂对话流智能体）能转交，但每次调用都是新会话，状态保存不住。

脚本：`scripts/genios_flow.py`（`Flow(..., app_id=)`、`user_var`、`assign`、`agent`、`end_content`、`chatflow_config`）、
`scripts/genios_publish.py`（`publish_chatflow`）、`scripts/genios_debug.py`（调试草稿）。

## 1. 创建与配置

| Action | 参数 | 说明 |
|---|---|---|
| `CreateApp` | `WorkspaceID, Name, AppType:"ChatFlow", Description, Icon` | 返回 `AppID`；平台自动建好画布，`GetAppConfigDraft` 的 `ChatFlowConfigDraft.WorkflowID` 就是画布 ID |
| `SaveChatFlowConfigDraft` | `AppID, ChatFlowConfig:{WorkflowID, RoundsReserved, VariableConfigs, UserVariableConfigs}` | 定义用户变量 |
| `UpdateApp` | `AppID, Name, Description` | 改名称、简介（审核看这两项） |
| 开场白 | `SaveChatFlowConfigDraft` 的 `ChatFlowConfig.ChatAdvancedConfig.OpeningConfig: {OpeningText, OpeningQuestions, OpeningEnabled}` | 发布时 `publish_chatflow` 从草稿带上 |

> 发布审核是模型自动审的，看不到画布里的 HTTP / Code 节点。画布里没有智能体节点、只靠 HTTP 取数据的对话流，简介要写明
> “画布中的 HTTP 节点实时读取 XX”，否则会被判“未绑定知识库、工作流或工具，无法获取数据”而驳回（2026-09-27 值班助手 1.0.0 实测）。

用户变量：`{"Name": "train_state", "Description": "...", "Scope": "Conversation"}`。`Scope` 为 `Conversation`（单会话）或
`Agent`（该用户所有会话）。`DefaultValue` 字段会被丢弃，读到的初值是空字符串，代码里自己兜底。

画布节点用和工作流相同的 `CreateFlowNode / UpdateFlowNode / UpdateFlowNodeLinks`（FlowID = 画布 ID）。
开始节点固定输出 `query`、`files`、`chat_histories`（只读，不用配置）。

## 2. 对话流专有节点与引用

| 用途 | 写法 |
|---|---|
| 读用户变量 | 节点 `Input` 里写 `{"Name": "step", "RefType": "user_variable", "Path": "train_state"}` |
| 写用户变量 | `VariablesAssign` 节点：`{"Variables": [{"Name": "train_state", "RefType": "node_field", "NodeCode": <上游>, "Path": "state"}], "OutputSchemas": [{"Name": "is_successful", "Type": 2}]}` |
| 调用对话型智能体 | `Agent` 节点：`{"AppID": <已发布的智能体>, "Input": [{"Name": "sys_user_query", ...引用 query}], "EnableChatHistories": true}`，输出字段 `output` |
| 读系统变量 | `{"Name": "sys_username", "RefType": "conversation_variable", "Path": "SYS_USERNAME"}`，可用 `SYS_USERID`、`SYS_USERNAME`、`SYS_USER_CHANNEL`、`SYS_CONVERSATION_ID`（开始节点**没有** `user_id` 字段） |
| 直接输出文本 | End 节点 `{"OutputType": "Content", "Template": "{{reply}}", "StreamOutput": true, "Input": [...]}` |
| 看图 | LLM 节点加 `"VisionInputs": [{"Name": "photo", "RefType": "node_field", "NodeCode": <开始节点>, "Path": "files"}]`（`gf.llm(..., vision=[...])`），模型须支持看图；智能体节点的附件条目 `sys_user_file_list[i].name/.url` 在当前轮只以文字链接传入，看不到图（见 pitfalls） |

- **`EnableChatHistories` 要打开**：否则被调用的智能体每轮都从头开始，多轮登记会断。
- **End 不要用默认的 `Variable` 模式**：回复会被包成 `{"output": "..."}`，这段 JSON 还会进入对话历史，被调用的智能体会跟着学，
  回复被包两层。
- 多个互斥分支汇到同一个节点（如两个分支都连到“推进剧本”）可以正常执行，未执行分支的引用为空。

### 登录用户身份（2026-09-23 实测）

| 入口 | `SYS_USERID` | `SYS_USERNAME` | `SYS_USER_CHANNEL` |
|---|---|---|---|
| 调试（`ChatQueryDebug`） | 空 | 空 | `IAM` |
| API 渠道（传 `UserID`） | 调用方传的值，**不校验** | 空 | `App` |
| Web 服务，访问控制「平台认证用户」 | 平台内部 ID（形如 `dan...` 的 20 位 ID） | **统一身份认证账号（学工号）** | `IAM` |

可信身份只能来自 Web 服务 + 平台认证（或飞书等平台登录渠道）；API 渠道的 UserID 不能当身份凭据。
开 Web 服务：`SaveAppBuiltinChannelPublishConfigDraft {ChannelCode:"web", BuiltinChannelConfigData:{WebPublishConfigData:{Enabled:true,
WebAccessConfig:{AccessType:"LoginAuth"}}}}`，再 `PublishAppChannel {BuiltinChannels:["web"], ...}`，需审核。
`AccessType` 取值 `Public`（匿名，随机 userID）/ `LoginAuth` / `SpecifyUser`；读配置用 `GetAppBuiltinChannelPublishConfig {ChannelCode}`。
访问地址 `https://<平台>/product/llm/chat/<AppKey>`，AppKey 用 `GetWebsdkAppKey {AppID}` 取（**不是 AppID**，用 AppID 打开报 `AppKey is invalid`）。

## 3. 校验、调试、发布

- 校验用 `CheckChatflow {ID, AppID}`。`CheckWorkflow` 会报 `not support conversation_variable or user_variable when agentID is null`。
- 调试（不用发布、不用审核）：`POST /api/bypass/app?Version=2023-08-01&Action=ChatQueryDebug`，请求体带草稿的
  `ChatFlowConfig`（对话型带 `AgentMode:"Single"` + `AppConfig`）、`Query`，接着聊传 `ConversationID`。
  走 `/api/app?Action=ChatQueryDebug` 会返回 200 但内容为空；事件行形如 `data:data: {...}`。封装在 `genios_debug.py`。
- **调试模式读不回用户变量**：变量能写入（`GetAppUserVariables {AppID, ConversationID}` 查得到），下一轮读到的仍是空。
  涉及跨轮状态的验证只能发布后用对话 API 做。
- 发布：`PublishAppConfig {AppID, ChatFlowConfig: {...草稿, Version, VersionDescription}}`，不传 `AgentMode`；
  缺 `Version` 报 `BadParameters: ChatFlowConfig.ver...`。之后照常发布 API 渠道、等审核（agent-publish.md）。
- 智能体节点调用的是被调用智能体的**已发布版本**；它的提示词、问答库改动照常发布即可，对话流不用重发。

## 4. 设计要点

- 状态存成一个 JSON 字符串变量（如 `{"node": "N2", "turn": 1, "observed": [...]}`），用 `IDLE` 表示不在流程中，便于路由判断。
- 路由、推进、计分放 Code 节点（可本地单测）；LLM 只做“这句话属于哪一类”的识别和台词生成。
- 紧急情况在识别阶段就分出来，给固定回复并清空状态，不交给台词模型。
- 实例建议：画布构建脚本、路由 Code、推进 Code 各放一个 `.py`，路由与推进逻辑在本地写单元测试。
