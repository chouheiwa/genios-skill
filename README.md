# GeniOS Skill

<p align="center"><img src="assets/genios-icon.png" alt="GeniOS Skill icon" width="220"></p>


用于南开 NK-GeniOS（`coze.nankai.edu.cn` / HiAgent）的 Agent skill。它把平台管理 API、统一身份认证、工作流和智能体操作封装成一个不依赖 Python 或 Node.js 的 Go CLI，并把平台实测的参数格式和常见问题整理成可供 Agent 使用的参考资料。

## 能做什么

- 通过本机登录页面完成统一身份认证，自动保存和续期管理 API 会话。
- 调用 GeniOS 平台管理 API，读取智能体、工作流、问答库、发布记录和观测信息。
- 用节点级 API 创建、修改、连线、校验、试跑和发布工作流。
- 调试未发布的智能体或对话流草稿。
- 修改智能体提示词、模型参数、问答库召回配置，并发布 API 渠道。
- 上传问答库条目，查询调用链和上游模型错误。
- 通过流式或阻塞模式调用已发布的对话 API。

skill 的平台规则和操作说明位于 [`genios/SKILL.md`](genios/SKILL.md)，参考资料位于 [`genios/references/`](genios/references/)。

## 安装

### 方式一：安装 GitHub Release（推荐）

1. 打开 [Releases](https://github.com/chouheiwa/genios-skill/releases)，下载与你的系统和架构匹配的 `genios-skill-*.tar.gz`。
2. 在使用方项目根目录解压到 skill 目录：

   ```bash
   mkdir -p .agents/skills/genios
   tar -xzf ~/Downloads/genios-skill-v*-darwin-arm64.tar.gz -C .agents/skills/genios
   chmod +x .agents/skills/genios/bin/genios
   ```

   Claude Code 用户可以把目标目录换成 `.claude/skills/genios`。解压后，目录中应包含 `SKILL.md`、`references/` 和 `bin/genios`。

### 方式二：从源码安装

源码安装需要 Go 1.22 或更新版本，运行时不需要 Python、Node.js 或第三方包：

```bash
git clone https://github.com/chouheiwa/genios-skill.git ~/genios-skill
cd ~/genios-skill/genios
go build -trimpath -ldflags='-s -w' -o bin/genios ./cmd/genios

# 在使用方项目中安装 skill
mkdir -p /path/to/project/.agents/skills
ln -s ~/genios-skill/genios /path/to/project/.agents/skills/genios
```

## 首次配置

以下命令都应在使用方项目根目录执行。

1. 复制 [`genios/project.example.md`](genios/project.example.md) 为 `genios-project.md`。用户可以直接把 WorkspaceID 告诉 Agent，由 Agent 写入该文件；CLI 会自动读取 `团队空间 WorkspaceID` 这一行。
2. 运行 skill 包中的 CLI：

   ```bash
   .agents/skills/genios/bin/genios setup
   ```

   在浏览器打开 CLI 打印的本机地址，输入统一身份认证账号和密码。密码不会通过聊天或命令行传递。
3. 验证登录：

   ```bash
   GENIOS_CREDENTIALS_FILE="$HOME/Library/Application Support/genios/credentials.env" \
     .agents/skills/genios/bin/genios auth
   ```

   `setup` 成功后通常不需要重复执行 `auth`。凭据和 session 默认保存在操作系统用户配置目录，权限为 `0600`；也可以用 `GENIOS_CREDENTIALS_FILE` 和 `GENIOS_SESSION_FILE` 覆盖路径。
4. 先做一个只读查询：

   ```bash
   .agents/skills/genios/bin/genios api ListWorkflows '{"PageNumber":1,"PageSize":20}'
   ```

如果 CLI 提示缺少团队空间 ID，让用户提供 WorkspaceID，并由 Agent 写入当前项目的 `genios-project.md`。团队空间属于项目配置，不要写进账号密码文件。

## 常用命令

```bash
GENIOS=.agents/skills/genios/bin/genios

# 读取平台管理 API
$GENIOS api ListWorkflows '{"PageNumber":1,"PageSize":20}'

# 工作流检查和试跑
$GENIOS flow check <WorkflowID>
$GENIOS flow run <WorkflowID> '<输入 JSON>'

# 调试未发布智能体草稿
$GENIOS debug <AppID> "第一句" "第二句"

# 问答库上传（默认只打印计划，加 --apply 才写入）
$GENIOS qa upload --dataset-id <DatasetID> --kb-file entries.json [--apply]

# 发布智能体配置和 API 渠道（默认只打印计划）
$GENIOS publish <AppID> [--apply]

# 查看平台错误和消息调用
$GENIOS traces errors [数量]
$GENIOS traces messages <AppID> [小时数] [数量]

# 调用已发布的对话 API
$GENIOS chat stream "你好"
$GENIOS chat block "你好"
```

如果没有把 `bin` 加入 `PATH`，请始终使用 skill 目录下的完整路径，例如 `.agents/skills/genios/bin/genios`。

## 从源码验证

```bash
cd genios
go test ./...
go vet ./...
```

GitHub Actions 只在推送 `v*` 标签时运行测试、静态检查和多平台构建，并自动创建包含完整 skill 文件、参考资料和对应平台二进制的 Release 压缩包：

```bash
git tag v0.1.0
git push origin v0.1.0
```

## 安全边界

- 账号密码只在本机 `setup` 页面输入，不要发送到聊天或写入命令行参数。
- 自动登录只用于本机开发 CLI；生产环境使用已发布渠道的 API Key。
- 凭据和 session 不进 Git、不打印、不发给第三方。
- 账号触发二次验证时 CLI 会报错退出，不尝试绕过。
