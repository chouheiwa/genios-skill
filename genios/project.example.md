# 项目固定参数（模板）

复制到使用方仓库根目录，命名为 `genios-project.md`，把尖括号里的值换成自己的。skill 本体不放任何项目参数。

| 参数 | 值 | 说明 |
|---|---|---|
| 平台地址 | `https://coze.nankai.edu.cn` | |
| 团队空间 WorkspaceID | `<团队空间ID>` | 所有资源都放这里，环境变量 `GENIOS_TEAM_WORKSPACE` 也设为它 |
| 内部 UserID | `<内部用户ID>` | `CreateAppWithConfig` 等接口要用它，不是学工号；用 iam `ListUser {"Query":"<学工号>"}` 查 |
| X-Account-Id | `1000000000` | 主账号，固定 |
| 主入口智能体 | `<AppID>`「<名称>」 | 提示词源文件位置 |
| 工作流 | `<WorkflowID>` | 工作流构建命令或配置位置 |
| 问答库 | `<DatasetID>` | 条目源文件位置 |
| 当前模型 | `<模型名> <ModelID>` | 智能体与工作流 LLM 节点共用；备选模型的限制写在这里 |
| 问答库召回 | MatchType `force`、Similarity `<阈值>`、TopK 1 | 阈值依据实测分数，见 references/qa-dataset.md |
| 工作流图标（CreateWorkflow 必填） | `upload/full/...` | 需要有效的 `upload/full/...` 路径 |

项目封装（构建、发布、上传命令）：

| 封装 | 作用 |
|---|---|
| `<path>` | `<作用>` |

常用环境变量：

```bash
export GENIOS_SESSION_FILE=<项目外>/session.env
# 团队空间是项目配置；setup 页面只管理登录凭据
export GENIOS_TEAM_WORKSPACE=<团队空间ID>
# 运行 genios setup 在本地网页中管理账号和密码
```
