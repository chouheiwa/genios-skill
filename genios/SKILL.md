---
name: genios
description: >-
  操作南开 NK-GeniOS（coze.nankai.edu.cn，火山引擎 HiAgent 2.5.1）平台的实测手册：统一身份认证自动登录与会话续期、
  平台管理 API 调用格式、用节点级 API 纯代码搭建/调试/发布工作流（LLM、Code、Http、选择器、变量聚合节点格式）、
  智能体提示词与模型参数发布、API 渠道审核、问答库写入与召回调参、对话 API 端到端测试，以及已踩过的平台坑。
  只要任务涉及 GeniOS / HiAgent / coze.nankai.edu.cn / 平台上的智能体、对话流或工作流 / 问答库 / 平台管理 API /
  “在平台上建、改、发布、测试”某个资源，或者遇到会话过期、302 跳登录页、429 限流、“大模型接口调用出错”、
  工作流 state 传不回来、对话流/用户变量/多轮状态、调试草稿之类的问题，就先读这个 skill，即使用户没有点名 skill。不要去浏览器画布手工搭节点，也不要
  凭 Coze 公开文档猜格式——这里的格式都是在这个平台上实测过的。
---

# NK-GeniOS 平台操作

这个平台的公开文档只写了界面操作，管理 API 的参数名、节点配置格式、发布流程几乎都查不到。下面的内容都是在实际项目里
用 API 实测、逆向前端代码得来的，按它做可以避免重新摸索。

**项目固定参数**（团队空间 ID、内部 UserID、资源 ID、当前模型）不在本 skill 里，放在使用方仓库根目录的
`genios-project.md`；先读它。没有就按 [project.example.md](project.example.md) 新建一份。

## 先确认三件事

1. **资源只能建在团队空间**。每个写接口都显式传 `WorkspaceID`（见 `genios-project.md`）。有些接口不传就默认落到个人空间，
   而且不会报错；建完用 `ListAppBriefs` / `ListWorkflows` 带同一个 `WorkspaceID` 回读确认。
2. **有可用会话**。管理 API 靠登录会话（cookie + x-csrf-token），不认 AccessKey。设好
   `GENIOS_SESSION_FILE`（项目外）与 `GENIOS_TEAM_WORKSPACE` 后，`scripts/genios_api.py` 的 `call()` 在会话缺失、
   302/401/登录页时会用项目根目录的 `genios-credentials.env` 自动登录并重试。细节见
   [references/auth-and-session.md](references/auth-and-session.md)。
3. **先 dry-run**。仓库里的构建/发布脚本默认只打印计划，加 `--apply` 才写平台；写之前先看计划。

## 按任务找参考

脚本都在本 skill 的 `scripts/` 下，通用、不含项目参数（团队空间、ID 从环境变量和命令行传入）；项目自己的封装和默认值放在
使用方仓库里（见 `genios-project.md`）。

| 要做的事 | 读 | 用的脚本（`scripts/`） |
|---|---|---|
| 登录、会话过期、两套 API 的区别、调用格式、一次性只读查询 | [auth-and-session.md](references/auth-and-session.md) | `genios_auth.py`、`genios_api.py`（可直接 `genios_api.py <Action> '<json>' [service]`） |
| 用 API 建/改工作流节点、连线、调试、发布 | [workflow-node-api.md](references/workflow-node-api.md) | `genios_flow.py`（`Flow` 与节点配置辅助函数） |
| 需要跨轮保存状态（剧本陪练、分步表单）、对话流型智能体、嵌入对话型智能体 | [chatflow.md](references/chatflow.md) | `genios_flow.py`（`user_var`/`assign`/`agent`/`end_content`）、`genios_publish.py`（`publish_chatflow`） |
| 不发布、不等审核直接试跑草稿 | [chatflow.md](references/chatflow.md) 第 3 节 | `genios_debug.py <AppID> "第一句" "第二句"` |
| 改智能体提示词、模型参数，发布配置和 API 渠道 | [agent-publish.md](references/agent-publish.md) | `genios_publish.py` |
| 往问答库写条目、调召回阈值 | [qa-dataset.md](references/qa-dataset.md) | `genios_qa.py` |
| 对话 API 端到端测试 | [agent-publish.md](references/agent-publish.md) | `genios_chat.py` |
| “大模型接口调用出错”等报错 | [pitfalls.md](references/pitfalls.md) 第 5 条 | `genios_traces.py errors` / `messages` |
| 设计多轮流程前、怀疑平台行为时 | [pitfalls.md](references/pitfalls.md) | `genios_probe_history.py`（暗号对照实验） |

## 排查报错的顺序

1. `genios_traces.py errors` 看最近出错 span 的 `Status.Message`：这是上游模型的原始报错（429 限流、400 参数不支持、
   工具名不合法等）。平台界面和对话 API 只会显示“大模型接口调用出错，请联系管理员”。
2. `genios_traces.py messages --app-id <AppID>` 对时间段，再用 `ListAppPublishHistory` 看那段时间线上是哪次发布、什么模型参数。
3. 需要复现时，用工作流调试接口跑同一模型的 LLM 节点（不改配置）。

## 设计原则（为什么现在的架构长这样）

- **需要跨轮状态就用对话流型做外层。** 对话型（单智能体）模式下，工作流的返回结果不会进入下一轮的模型上下文
  （对照实验确认是平台行为，换强模型也一样），不要设计“智能体每轮把工作流返回的 state 传回去”。对话流型每轮执行
  画布，用单会话用户变量存状态、Code 节点按规则推进；开放问答用智能体节点转交已有的对话型智能体（chatflow.md）。
  只用对话型时，就让它靠对话历史完成追问、预览，最后调用一次工作流做保存、计分之类确定性的事。
- **确定性逻辑放 Code 节点，LLM 只做理解和生成。** 分支、计分、编号都用 Python 按规则算，便于写本地单元测试
  ，同样输入得到同样结果。
- **如实回报。** 调外部服务的 Http 节点配置异常默认值，Code 节点只有在服务端明确成功时才说“已保存”。

## 改动后的验证顺序

1. 本地：Code 节点逻辑写单元测试；skill 脚本自带
   `scripts/test_genios_auth.py`、`scripts/test_genios_publish.py`（直接 `python3 <文件>` 运行）。
2. 工作流：用 `Flow.run()` 调试接口试跑；智能体（对话型、对话流型）草稿用 `genios_debug.py` 试跑，不用发布，看每个节点的输入输出。
3. 智能体：发布后等 API 渠道审核通过，再用对话 API（流式，`genios_chat.py`）跑多轮端到端。只看工作流试跑不够：智能体是否调用、
   传什么参数，只有端到端才看得到（事件里的 `agent_thought` / `agent_thought_end`）。
4. 临时资源（测试用 API Key、探测智能体/工作流）用完即删，删完回读确认。

## 安全边界

- 账号密码文件 `genios-credentials.env` 放在**项目根目录**（已被 `.gitignore` 忽略，权限 600）；登录脚本要求它在项目内时
  必须被 git 忽略，否则拒绝读取。
- 会话文件 `session.env` 由 `GENIOS_SESSION_FILE` 指定，写到项目目录外（如 scratchpad）。
- 两者都不进 git、不打印、不发给第三方。
- 自动登录只用于本机开发脚本，不部署进后端或交付物；生产环境用发布渠道的 API Key。
- `ListUser`（iam）会返回全校个人信息，只按学工号查任务必需的那一个人。
- 账号若被要求二次验证，登录脚本会报错退出，不要尝试绕过。
