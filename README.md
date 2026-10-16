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
2. 新建 `genios-credentials.env`（`ACCOUNT=` / `PASSWORD=`），`chmod 600`，并加入 `.gitignore`；登录脚本发现它没被忽略会拒绝读取。
3. `export GENIOS_SESSION_FILE=<项目外>/session.env GENIOS_TEAM_WORKSPACE=<团队空间ID>`。

脚本依赖：Python 3、`requests`、`pycryptodome`（登录时 AES 加密密码）。

## 测试

```bash
python3 genios/scripts/test_genios_auth.py
python3 genios/scripts/test_genios_publish.py
```

## 安全边界

- 自动登录只用于本机开发脚本，不部署进后端或交付物；生产环境用发布渠道的 API Key。
- 账号密码、会话文件不进 git、不打印、不发给第三方。
- 账号若被要求二次验证，登录脚本会报错退出，不要尝试绕过。
