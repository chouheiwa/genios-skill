# 问答库：写入条目与召回调参

## 接口（service `app`）

| Action | 参数 | 说明 |
|---|---|---|
| `CreateQADataset` | `WorkspaceID, Name, Description, Icon, EmbeddingModelID, DirectoryID:"default"` | 返回 `DatasetID` |
| `CreateQADocument` | `WorkspaceID, DatasetID, Description, Questions:{MainQuestion, SimilarQuestions[]}, Answer` | 写入即生效，无需发布 |
| `ListQADocuments` | `WorkspaceID, DatasetID, PageNumber, PageSize` | `Result.Items[]`（`Description`、`Questions`）、`Total` |
| `GetQADatasetOverview` / `DeleteQADocument` | | |

上传脚本建议按条目编号去重：`Description` 以 `document_id` 开头（如 `OFFICIAL-REG-01 official`），
重复执行只补写缺的条目（先 `ListQADocuments` 取已有编号）。

## 条目写法

- 答案末尾带来源标注，如 `【OFFICIAL-REG-01｜依据：《…》（南发字〔2025〕173号）第二十条】`。
  智能体提示词据此区分正式依据和演示内容。
- `SimilarQuestions` 写用户真实会问的说法（口语、缩写），能明显提高命中。

## 召回配置（智能体的 `QADatasetConfig`）

问答库命中后**直接输出答案，不再走意图识别和工作流**（平台文档 agent-development“问答库”一节），所以召回配置直接
决定流程能不能走到工作流。

| 字段 | 取值 | 说明 |
|---|---|---|
| `MatchType` | `force` / `auto` | `force` 每轮都检索且命中即截走；`auto` 由模型判断是否检索。界面默认会写成 `force` |
| `Similarity` | 0—1 | 命中阈值 |
| `TopK` | 1 | |
| `RetrievalSearchMethod` | 0 | |

实测的分数分布（doubao-embedding）：真实问题 0.956—1.0；“确认保存”“修改一下地点”“开始练习”“验证码不能给你”
这类流程短句误命中 0.82—0.87（例如“确认保存”0.817 命中“做任务先交保证金”）。阈值定 **0.92**，配合 `auto`。
新增一批条目后，重新测一遍流程短句的分数再决定阈值：在对话 API 流式事件里读 `qa_retrieve_end` 的 score。

## 外部数据源：让平台定时来拉（内容放自己的后端）

内容维护在自己的系统里、平台定时同步，比用管理 API 往平台写更合规——后端不需要持有平台登录态。
2026-09-23 实测全通。

1. 建 API 数据源（`CreateDataSource`）。文档没有这个接口，字段是实测出来的：

```json
{"Name": "...", "Description": "...", "Icon": "upload/full/...", "Type": 0,
 "Config": {"APIConfig": {"Method": 0, "URL": "https://<你的域名>/...", "Timeout": 30,
   "Headers": {"X-API-Key": "<只读 Key>"}, "Queries": {}, "Body": "", "AuthType": 0,
   "PageSizeField": "PageSize", "PageNumberField": "PageNumber", "TotalField": "Total"}}}
```

- `Type`：0 = API 接口，1 = 数据库；`Method`：0 = GET。两者都是数字，传字符串报 `Mismatch type int64`。
- `Headers` 是对象（`map[string]string`），不是数组；`Queries`、`Body`、`AuthType` 都必填，可为空。
- 删除用 `DeleteDataSource {Id, Type}`（参数名是 `Id`，且必须带 `Type`）；列表用 `ListDataSources {Filter:{Type:0}, PageNumber, PageSize}`。
- **不要把 Key 放在 URL 的 Query 里**：会进 nginx 访问日志、代理和浏览器历史。用请求头，平台支持。

2. 绑定到问答库并开定时：`CreateQAAPISourceImportTask {DatasetID, APISourceID, FieldMapping, CronRule?, Immediate}`，
   改配置用 `UpdateQAAPISourceImportTask`（同样支持 `Immediate` 立即拉一次）。

- **字段映射要写成数组内的路径**：`{"QuestionField": "Items.question", "AnswerField": "Items.answer"}`。
  写成 `"question"` 不报错，但同步 0 条，任务状态停在 3。
- 响应体必须是 JSON 对象（不能是顶层数组），分页字段名要和数据源配置一致。
- `CreateQADataset` 必须传 `DirectoryID`（填 `"default"`）。

3. 同步语义（实测）：按主问题匹配，**已存在则只更新答案，其他不动；不存在则新建；永远不会删除**。

- 外部数据源本身不能导入相似问法，但同步进来的就是普通问答条目：用 `UpdateQADocument`
  （`Questions: {MainQuestion, SimilarQuestions}`）补一次相似问法后，**后续同步只改答案，相似问法保留**（已实测）。
- 下线内容：让导出接口把答案改成【已停用】开头，平台不会自动删条目。

## MatchType：auto 会漏召回，force + 阈值更稳（2026-09-23 实测）

- `MatchType: "auto"` 不是“自动判断相似度”，而是**平台先判断这句话要不要查问答库**。实测 43 条里有 5 条
  （国家安全理论类问题，如“什么是国家秘密？”）连主问题原文都召回不到——不是分数低，是压根没检索；
  改成 `force` 后同样的问题分数 1.0。
- 当初用 auto 是为了防止“确认保存”这类流程短句被问答库截走。实测 `force` + `Similarity 0.92` 同样安全：
  16 条正向（主问题与相似问法）全部召回，24 条流程短句（确认保存/取消/B/我想做反诈陪练）与
  无依据问题（校园卡丢了怎么办等）**0 误采纳**。
- 结论：用 `force` + 阈值控制，不要用 auto 兜底；阈值靠实测分数定（实测项目取 0.92）。
- 量相似度的办法：临时把 `Similarity` 调到 0.5 发布，读对话事件 `qa_retrieve_end` 里的
  `docs.outputList[0].metadata.score`，量完改回。
- 相似问法能显著提分：同一条“电动车能不能推进宿舍楼充电”补进相似问法前 0.9127（未命中），补后 0.9988。
