# 工作流：用节点级 API 搭建、调试、发布

不需要画布。编辑器保存画布调用的就是下面这些接口（从 `/resources/product/llm` 子应用前端代码核实），`scripts/genios_flow.py`
已经封装好：`Flow.reset / add / set / link / check / run`，以及 `start_inputs / llm / code / condition / merge / end / ref / literal`
这些生成 NodeConfig 的函数。用法见下文各节示例。

## 目录

1. 工作流级接口
2. 节点级接口
3. 各类节点的 NodeConfig 格式
4. 变量引用与字面值
5. 调试与导出
6. 推荐的搭建顺序

## 1. 工作流级接口（service `app`，Version `2023-08-01`）

| Action | 参数 | 说明 |
|---|---|---|
| `CreateWorkflow` | `WorkspaceID, Name, Description, Icon` | 返回 `ID`；只含默认 Start/End。`Icon` 必须是有效 `upload/full/...` 路径 |
| `ListWorkflows` | `WorkspaceID, PageNumber, PageSize` | `Items[].ID/Name/Status` |
| `GetWorkflow` | `ID`（**不是** `WorkflowID`） | `Nodes[]`（含 `Code`、`Type`、`NodeConfig`）与 `NodeLinks[]` |
| `CheckWorkflow` | `ID` | `{"Valid": true}` 或 `Messages[]`（带出错节点 ID 和原因） |
| `PublishWorkflow` | `ID, Version, VersionNote` | 智能体调用的是已发布版本，改完要重新发布 |
| `DeleteWorkflow` | `ID` | |
| `ExportWorkflow` | `ID` | `Result.Content` 为 base64 的 DSL YAML（`DLVersion: v2`） |
| `CheckImportWorkflowDepends` / `ImportWorkflowFromDSL` | `WorkflowYaml`（base64） | 网关可达；尚未实测导入 |

## 2. 节点级接口

| Action | 参数 | 说明 |
|---|---|---|
| `CreateFlowNode` | `FlowID, Type, Layout:{X,Y}, Name` | 返回 `Node.Code`，节点带平台默认配置 |
| `UpdateFlowNode` | `ID(=节点 Code), FlowID, Name, NodeConfig:{<Type>Node:{...}}, ErrorConfig?` | 整体覆盖该节点配置 |
| `DeleteFlowNode` | `FlowID, ID` | 偶发 500，重试即可 |
| `UpdateFlowNodeLinks` | `FlowID, Links:[{From:{NodeCode, PortID?}, To:{NodeCode}}]` | 字段名是 **`Links`**（写成 `NodeLinks` 报缺参）；整体覆盖所有连线 |

节点 Type：`Start End LLM Code Http Condition Intent VariableMerge Knowledge QA Message Loop Batch Tool Workflow
Database VariablesAssign TextProcessing InformationGathering LongTermMemory ...`。
NodeConfig 的键是 `<Type>Node`：`StartNode`、`LLMNode`、`CodeNode`、`HttpNode`、`ConditionNode`、`VariableMergeNode`、`EndNode` 等。

## 3. 各类节点的 NodeConfig

变量类型编号：String 0、Integer 1、Boolean 2、Number 3、Object 4、Array<String> 5、Array<Object> 9、Array<File> 11。

**Start**：输入参数必须带 `Desc`，否则 `CheckWorkflow` 报 `desc is null`。

```json
{"InputSchema": [{"Name": "turns", "Type": 0, "Required": true, "Desc": "学生原话，每行一句"}]}
```

**LLM**：提示词字段是 `SystemPrompt` 和 `Prompt`，用 `{{输入名}}` 引用本节点 `Input` 里的变量。
`OutputFormat` 为 `"text"`（或 markdown）时，**输出变量名固定为 `raw_output`**，自己起名会拿到空值。
需要 JSON 时也建议用 text 输出，让提示词要求“只输出 JSON”，再在下游 Code 节点里容错解析。

```json
{"ModelID": "<模型ID>", "Temperature": 0, "TopP": 0.5, "MaxTokens": 512,
 "Input": [{"Name": "numbered", "RefType": "node_field", "NodeCode": "<上游Code>", "Path": "numbered"}],
 "SystemPrompt": "...", "Prompt": "学生的话：\n{{numbered}}", "OutputFormat": "text",
 "OutputSchema": [{"Name": "raw_output", "Type": 0}],
 "TimeoutSeconds": 120, "Retries": 1, "ModelInteractiveMode": "direct"}
```

**Code**：`Language` 0 = JavaScript，**1 = Python**；入口 `def handler(params): return {...}`，`params` 的键是
`Input[].Name`，返回字典的键要和 `OutputSchema` 一致。只用标准库（json、hashlib、uuid 等已验证可用）。

```json
{"Input": [...], "Language": 1, "Code": "def handler(params):\n    return {'reply': '...'}\n",
 "OutputSchema": [{"Name": "reply", "Type": 0}], "TimeoutSeconds": 30, "Retries": 0}
```

建议把 Code 源码放成独立 `.py` 文件，本地写单元测试，上传时读文件内容传给 `genios_flow.code(source, ...)`。推荐做法：
用一个 `render()` 读取源码文件（需要常量表的在前面注入 `SCRIPT = ...` 之类），本地测试和上传用同一份渲染结果。

**Condition（选择器）**：`Conditions[]` 里每个条件的 `Name` 就是连线用的端口 ID（`if01`、`if02`…），兜底端口固定
`else`。`ConditionLogic` 0 = AND、1 = OR；`Operator` 0 = 等于（1 不等于、2 大于、3 大于等于…）。

```json
{"Conditions": [{"Name": "if01", "ConditionLogic": 0, "SubConditions": [
  {"Left": {"Name": "action", "RefType": "node_field", "NodeCode": "<Code节点>", "Path": "action"},
   "Operator": 0, "Right": {"Name": "Right", "RefType": "value", "JsonValue": "\"submit\""}}]}]}
```

**Http**：`URLTemplate`、`Method`、`ContentType`（`none`、`JSON`、`raw text`、`form-data`、`x-www-form-urlencoded`、`binary`）、
`BodyJsonTemplate`。模板里的变量写成 `{{<NodeCode>_node_field.<节点名>.<字段路径>}}`，并在 `TemplateVar` 里登记同名
条目。鉴权：`AuthType` 为 `None` / `Bearer`（配 `Token: {RefType:"value", JsonValue:...}`）/ `Custom`。
出站请求经平台出站代理：**内网地址（10.x、172.16—31.x、192.168.x）一律被拒**（报错 `Deny: Private Range`，节点仍显示 success，
错误在输出的 `error_body` 里），即使服务器也在校内；公网 HTTPS 可以访问。演示后端要部署在有公网地址的机器上。

```json
{"Method": "POST", "URLTemplate": "https://example/api/v1/reports", "ContentType": "JSON",
 "BodyJsonTemplate": "{{<Code>_node_field.校验与组装.body}}",
 "TemplateVar": [{"Name": "<Code>_node_field.校验与组装.body", "RefType": "node_field", "NodeCode": "<Code>", "Path": "body"}],
 "AuthType": "None", "TimeoutSeconds": 5, "Retries": 0,
 "OutputSchema": [{"Name": "status_code", "Required": true, "Type": 1}, {"Name": "headers", "Type": 0}, {"Name": "body", "Type": 0}]}
```

异常时给默认输出而不是中断流程（放在 `UpdateFlowNode` 顶层 `ErrorConfig`，不在 NodeConfig 里）：

```json
{"ErrorConfigType": "Default", "DefaultOutput": "{\"status_code\": 0, \"headers\": \"\", \"body\": \"\"}"}
```

`ErrorConfigType` 还有 `None`（出错即停）、`ErrBranch`（走异常分支，端口 `error`）。

**VariableMerge（变量聚合）**：分支汇合用，取组内第一个非空值；输出固定名 `Group1`、`Group2`…

```json
{"Groups": [{"name": "Group1", "Type": 0, "Variables": [<ref A>, <ref B>]}],
 "OutputSchema": [{"Name": "Group1", "Type": 0}]}
```

**End**：`{"OutputType": "Variable", "Input": [<ref>, ...]}`，`Input[].Name` 就是工作流输出字段名。
End 可以直接引用每条路径都会经过的上游节点；只在某个分支上的节点要先经过变量聚合。

## 4. 变量引用与字面值

- 引用上游节点：`{"Name": "<本节点里的变量名>", "RefType": "node_field", "NodeCode": "<上游节点 Code>", "Path": "<字段>"}`
- 字面值：`{"Name": "Right", "RefType": "value", "JsonValue": "<JSON 编码后的字符串>"}`，例如字符串 submit 写成
  `"\"submit\""`。写成 `Value`、`Val`、`Default` 都会被静默丢弃。
- 其他 RefType：`conversation_variable`、`user_variable`、`tmp_variable`、`loop_item`、`loop_index`。

## 5. 调试

- `SubmitWorkflowDebug {ID, InputData: "<JSON 字符串>"}` → `runId`
- `QueryDebugProcess {WorkflowId, RunId}`（注意大小写，写成 `RunID`/`WorkflowID` 报缺参）→
  `status`（processing/success/failed）、`output`（End 节点输出的 JSON 字符串）、`nodes{<Code>: {input, output, status, message, costMs}}`、`msg`。
- LLM 节点失败时看 `nodes[].message`：`LLMRateLimitError 429` 是模型配额被占满，`404 Your account ...` 是没有模型权限。
- `Flow.run(inputs)` 封装了提交与轮询；构建脚本可加 `--smoke`，用预置样例输入跑并打印结果。改完节点先试跑，再发布。

## 6. 推荐的搭建顺序

1. `reset()` 清掉 Start/End 以外的节点（重建是幂等的，失败了重跑即可）。
2. `add()` 建全部节点，拿到各自 Code。
3. `set()` 逐个写配置（上游先于下游，方便引用）。
4. `link()` 一次写全部连线（含选择器端口）。
5. `CheckWorkflow` → `--smoke` 试跑 → `PublishWorkflow`。
6. 如果改了输入参数，智能体侧要重新发布配置，否则它仍按旧参数调用。
