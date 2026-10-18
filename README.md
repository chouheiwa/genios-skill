# genios-skill

南开 NK-GeniOS（coze.nankai.edu.cn，火山引擎 HiAgent 2.5.1）平台的 Agent skill：统一身份认证自动登录与会话续期、
平台管理 API 调用格式、用节点级 API 纯代码搭建/调试/发布工作流与对话流、智能体发布与 API 渠道审核、问答库写入与召回调参、
对话 API 端到端测试，以及实测踩过的平台坑。

skill 本体在 [`genios/`](genios/SKILL.md)，不含任何项目参数。

## 安装

在使用方仓库里用软链接引用（以 Claude Code 为例；Codex / OpenCode / Cursor 读 `.agents/skills/`）：

```bash
git clone <本仓库地址> ~/genios-skill
mkdir -p .claude/skills && ln -s ~/genios-skill/genios .claude/skills/genios
# 或全局：ln -s ~/genios-skill/genios ~/.claude/skills/genios
```

然后在使用方仓库根目录：

1. 按 `genios/project.example.md` 新建 `genios-project.md`，填团队空间 ID、内部 UserID、资源 ID 等。
2. 运行 `genios setup`，在本地网页中填写账号和密码；CLI 会把凭据和会话保存到用户配置目录并设置权限 600。也可以通过 `GENIOS_CREDENTIALS_FILE` 指定自定义凭据文件。
3. 用户可以直接把 WorkspaceID 告诉 Agent，由 Agent 写入项目的 `genios-project.md`；CLI 会自动读取。需要临时覆盖时才设置 `GENIOS_TEAM_WORKSPACE`。如需自定义会话文件，再设置 `GENIOS_SESSION_FILE` 指向项目外路径。

如果 CLI 提示缺少团队空间 ID，先让用户提供 WorkspaceID，并由 Agent 写入 `genios-project.md`。团队空间属于项目配置，不要写入账号密码文件。

也可以直接下载 GitHub Release 中与操作系统匹配的 `genios-skill-*.tar.gz`，解压到
`.agents/skills/genios/`（或其他 skill 目录）；压缩包内的 `bin/genios` 已经可以直接运行。

CLI 依赖：Go 标准库。构建后是单个 `genios` 二进制，不需要 Python、Node.js 或第三方包。构建说明见 [`genios/README.md`](genios/README.md)。仓库的 GitHub Actions 会在推送 `v*` 标签时构建完整多平台 skill 压缩包并自动创建 Release。

## 构建与测试

```bash
cd genios
go test ./...
go build -trimpath -ldflags='-s -w' -o genios ./cmd/genios
```


## 安全边界

- 自动登录只用于本机开发 CLI，不部署进后端或交付物；生产环境用发布渠道的 API Key。
- 账号密码、会话文件不进 git、不打印、不发给第三方。
- 账号若被要求二次验证，CLI 会报错退出，不要尝试绕过。
