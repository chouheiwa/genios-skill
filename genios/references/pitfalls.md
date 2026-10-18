# 已确认的平台行为与踩坑清单

每条都注明现象、原因和做法。判断“是平台还是模型”的问题时，先做对照实验再下结论（见第 1 条的做法）。

## 1. 工作流返回值不进下一轮模型上下文（平台行为）

- 现象：让智能体每轮把工作流返回的 `state` 传回去，第 2 轮传入的总是空字符串，陪练每轮回到开头。
- 原因：单智能体模式下，平台把工具调用记录存进会话历史（`get_conversation_messages` 查得到），但拼下一轮模型上下文时
  只带用户消息和智能体最终回复，不带 `agent_thought_end.observation`。
- 证据：平台行为探测流程 暗号对照实验——工作流返回随机暗号（不出现在回复里），第 2 轮问暗号，
  doubao-seed-2-0-mini 与 doubao-seed-2-1-pro 各 3 次全部答不出，均如实回答“看不到之前的工具返回结果”。
- 做法：多轮状态放在对话本身（预览、台词都在智能体回复里）；工作流只在最后调用一次，把需要的全部信息作为参数传入
  （例如陪练结束时传入学生全部原话，登记确认时传入最终字段）。
- 更好的做法：需要每轮推进的流程改用对话流型智能体，用单会话用户变量保存状态（chatflow.md）。

## 2. 历史轮数默认 3 轮（配置）

- 现象：陪练结束时智能体只能传出最后 3 句原话。
- 做法：`ModelConfig.RoundsReserved` 调大，上限 100；平台没有历史压缩，超出按滑动窗口丢弃。

## 3. 问答库截走流程短句（配置）

- 现象：用户说“确认保存”，智能体回答了一条刷单问答，没调工作流。
- 做法：`MatchType:"auto"` + 按实测分数定阈值（实测项目取 0.92），见 qa-dataset.md。

## 4. 改了配置线上没变（发布流程）

- 原因：API 渠道绑定具体 `PublishID`，且新版本要自动审核 1.5—3 分钟。
- 做法：`PublishAppConfig` 之后必须 `PublishAppChannel`，轮询审核到 `Success` 再测。

## 5. “大模型接口调用出错”

这是平台统一的兜底提示。先 `genios traces errors` 看调用链 span 的 `Status.Message`（上游原始报错），
再结合 `genios traces messages <AppID>` 与 `ListAppPublishHistory` 对上时间段和当时的线上配置：

| 具体错误 | 含义 | 做法 |
|---|---|---|
| `400 InvalidParameter: Unsupported thinking type for the current model: auto` | 智能体思考模式不被该模型支持 | `--reasoning disabled` 重新发布；`genios publish` 会拦截草稿里的非 disabled 值 |
| `400 ... tool name ... must match ^[a-zA-Z0-9_-]+$`（DeepSeek 系列） | DeepSeek 要求工具名只能是英文字母、数字、下划线、连字符，中文工作流名会直接失败 | 用 DeepSeek 前把工作流改成英文名；否则别选它当智能体模型 |
| `429 ModelAccountTpmRateLimitExceeded` | 模型账号每分钟 token 配额被占满（GLM 5.3 flash 疑为全校共享，早上 8 点持续数分钟） | 换模型；演示前先实测 |
| `404 Your account ... ` | 没有该模型权限（如 GLM-4.7） | 换模型 |
| 调试正常、智能体报错 | 智能体级参数不兼容（如 doubao-seed-2-1-pro 思考模式 auto） | 回退参数，逐项排查 |

## 6. 模型能力问题（与平台无关）

- doubao-seed-2-0-mini 在多轮角色扮演中反复重复同一段台词；换 GLM 5.3 flash / doubao-seed-2-1-pro 后正常。
- 第 3 幕“拒绝也继续”这类与其他步骤规律相反的规则，模型容易按惯性提前结束：提示词里逐条写明结束条件。

## 7. 接口参数名与文档不一致

| 接口 | 实际参数 | 常见错误写法 |
|---|---|---|
| `GetWorkflow` / `ExportWorkflow` / `CheckWorkflow` | `ID` | `WorkflowID` |
| `UpdateFlowNodeLinks` | `Links` | `NodeLinks` |
| `QueryDebugProcess` | `WorkflowId`、`RunId` | `WorkflowID`、`RunID` |
| `DeleteAppAPIKey` | `APIKeyID` | `AppKeyID` |
| `CreateAppAPIKey` | 必填 `Expired` | 省略 |
| LLM 文本输出变量 | `raw_output` | 自定义名 |
| 字面值 | `JsonValue`（JSON 编码字符串） | `Value` |
| Start 输入参数 | 必须带 `Desc` | 省略 |

## 8. 画布与审核

- `CreateFlowNode` 传不存在的节点类型（如 `Bot`、`App`）会返回 500，但**节点仍被写进画布**，之后 `GetWorkflow`/`GetChatflow`
  都报 `unknown node Type`，读不出节点 ID 也就删不掉。不要拿节点类型做试探；智能体节点的类型名是 `Agent`。
- 平台的 API 渠道审核由模型完成：名称或简介写“临时测试、验证后删除”会被驳回（理由是无实际应用价值）。测试件也起一个
  说得通的业务名称。审核一般 1.5—3 分钟，偶尔卡在 InReview 超过 20 分钟；不影响用 `genios debug` 调试草稿。
- 对话流调试模式下用户变量写得进、读不回；跨轮状态只能在发布版本上验证（chatflow.md 第 3 节）。

## 9. 网络与会话

- 阻塞对话模式易 504，用流式。
- 管理 API 偶发 5xx、TLS 握手超时：`genios_flow.Flow.api` 会重试 3 次；重建是幂等的。
- 会话可能半小时就失效：走 `genios api` 自动续期，不要自己拼请求。
- Http 节点出站走平台 `ssrf-proxy`，平台在校园内网，访问不到开发机的 localhost。


## 每个发布渠道绑定自己的版本（2026-09-24）

`PublishAppConfig` 只产生新版本；API / Web / 飞书各渠道仍停在各自上次 `PublishAppChannel` 时的 PublishID。
只重发 API 渠道时，曾出现 API 0.8.0、飞书 0.7.0、Web 0.6.0 并存（Web 版本里的 Http 节点还指向已删除的旧密钥，线上坏了却不报错）。
`genios_publish._publish_api_channel` 现在会读 `ListAppBriefs.PublishedChannels`，把新版本推到全部已开通渠道
（各渠道的配置数据从 `GetAppBuiltinChannelPublishConfig` 的 `DraftConfigDetail.ConfigData` 取，键名见 `CHANNEL_KEYS`）。
发布后用 `GetAppBuiltinChannelPublishConfig` 逐个渠道核对 `PublishedVersionInfo.Version`。

## 飞书渠道的身份

飞书渠道下对话流只拿到 `SYS_USERID`=飞书 open_id（`ou_…`）、`SYS_USER_CHANNEL`=`Lark`，`SYS_USERNAME` 为空——
即使应用开通了通讯录权限，学号（`LarkUserID`）和姓名（`LarkUserName`）也只出现在消息日志 `ListAppMessageWithConLog` 里。
要在业务里用学号，得由自己的后端拿飞书应用凭证调 `contact/v3/users/{open_id}?user_id_type=open_id` 换 `user_id` 与 `name`。

## 图片：智能体节点看不到当前这一轮的图片（2026-09-28）

- 对话流里学生发图，开始节点 `files` 是 `[{name, url}]`，`url` 为 https 预签名链接；原话为空。
- 智能体节点的附件条目要写成 `sys_user_file_list[i].name` / `sys_user_file_list[i].url` 两条输入（各引用一个字符串变量）；
  直接引用 `files` 列表会被 `CheckChatflow` 判 “invalid file list variable format”。
- 但即使接上，**当前这一轮**的附件只以“文件列表: 文件名…, 文件链接…”的文字传给模型，模型看不到图，会编造内容；
  下一轮起图片才以 `image_url` 出现在历史里。要看图就在对话流里加 LLM 节点，`VisionInputs` 引用 `files`（模型须带 `vision` 能力），
  把描述当文字交给智能体。
- 空原话、无附件交给智能体节点会报 `query or files is required`，整轮失败并回“agent 执行出错”；路由里要单独处理空原话。


## 对话流开始节点不要改（2026-10-02）

- 对话流的开始节点由平台固定输出 `query`、`files`、`chat_histories`。用 `UpdateFlowNode` 把它设成 `{"InputSchema": []}` 后，
  平台存成 `null`，`CheckChatflow` 报 `InputSchema is NULL` 和 `invalid field path query`；之后重建（`Flow.reset()` 只删其他节点）也恢复不了。
- 构建脚本里不要 `flow.set(start, ...)`。已经改坏时，从正常的对话流取开始节点的 `InputSchema` 原样 `UpdateFlowNode` 写回即可。
- 新发布的对话流首轮请求偶有“没找到依据”或 60 秒无回复，复跑即正常；回归要么在发布后稍等再跑，要么对失败项复跑确认。

## 流程编排型应用（AppType Workflow）：外部系统直接跑工作流（2026-10-02 实测）

不需要智能体或对话流。步骤：
1. 建工作流、搭节点、`PublishWorkflow`；用 `ListPublishedWorkflowVersion {ID}` 查到该版本的 `PublishID`。
2. `CreateApp {AppType:"Workflow", WorkflowIDs:[工作流ID], ...}`。参数名是 **`WorkflowIDs`（数组）**；写成 `WorkflowID`、
   `WorkflowConfig` 都会报 `workflow app type need select workflow`。
3. `PublishAppConfig {AppID, AppConfig:{...草稿, Version, SkillConfig:{WorkflowPublishIDMap:{工作流ID: PublishID}}}}`，
   不传 `AgentMode`；缺 `SkillConfig` 或 `WorkflowPublishIDMap` 都会报缺参。再照常发布 API 渠道、等审核。
4. `CreateAppAPIKey` 后调 `POST /api/proxy/api/v1/sync_run_app_workflow`，头 `Apikey`，体 `{"InputData": "<开始节点输入的 JSON 字符串>", "UserID": "..."}`；
   返回 `status`（success/failed…）、`output`（结束节点输出的 JSON 字符串）、`nodes`（逐节点输入输出，体积大）。
