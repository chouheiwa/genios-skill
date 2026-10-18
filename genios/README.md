# genios CLI

这是 GeniOS skill 的 Go CLI 实现，使用 Go 标准库，不依赖 Python、Node.js 或第三方包。

## 构建

```bash
cd genios
go build -trimpath -ldflags='-s -w' -o genios ./cmd/genios
```

交叉编译示例：

```bash
GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o dist/genios-linux-amd64 ./cmd/genios
GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags='-s -w' -o dist/genios-darwin-arm64 ./cmd/genios
GOOS=windows GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o dist/genios-windows-amd64.exe ./cmd/genios
```

## 使用

```bash
# 团队空间是项目配置，不属于登录凭据
export GENIOS_TEAM_WORKSPACE=<团队空间 ID>
./genios setup

# 或使用环境变量指定 session 路径
export GENIOS_SESSION_FILE=<项目外>/session.env
./genios api ListWorkflows '{"PageNumber":1,"PageSize":20}'
./genios api ListTraceSpans '{"PageSize":20}' --service observe
export GENIOS_KEY_FILE=<项目外>/agent-apikey.txt
./genios chat stream "你好"
./genios chat block "你好"
```

凭据和 session 默认保存在用户配置目录并使用 `0600`；自定义 session 路径必须放在项目目录外。
发布压缩包中的二进制位于 `bin/genios`，可直接运行 `./bin/genios setup`。

## 子命令

```bash
genios flow check <WorkflowID>
genios flow run <WorkflowID> '<输入 JSON>'
genios debug <AppID> "第一句" "第二句"
genios qa upload --dataset-id <DatasetID> --kb-file entries.json [--apply]
genios publish <AppID> [--apply]
genios traces errors [数量]
```

不带 `--apply` 的问答库上传和智能体发布只读取并打印计划。

## GitHub Actions

`.github/workflows/build-genios.yml` 只在推送新的 `v*` 标签时运行测试、`go vet`，构建多平台完整 skill 压缩包，并自动创建 GitHub Release。

## Release 安装

每个 `v*` 标签会生成按平台区分的完整 skill 压缩包。解压到目标仓库的 `.agents/skills/genios` 后，skill 文件、参考资料和对应平台的 `bin/genios` 会一起就位；首次使用前执行：

```bash
chmod +x .agents/skills/genios/bin/genios
```


## 认证引导

CLI 不会在终端或对话中回显、收集密码。没有 session 时，它会查找用户配置目录中的凭据文件；文件不存在时运行 `genios setup` 打开本地管理页面。不要把密码作为命令行参数或聊天消息发送。
