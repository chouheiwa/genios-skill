# GeniOS CLI

`bin/genios` 是 GeniOS skill 的本地命令行工具。它使用 Go 标准库，不依赖 Python、Node.js 或第三方运行时。Release 压缩包已经包含对应平台的二进制；源码安装时在本目录构建即可。

## 构建

```bash
go test ./...
go vet ./...
mkdir -p bin
go build -trimpath -ldflags='-s -w' -o bin/genios ./cmd/genios
```

交叉编译示例：

```bash
GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags='-s -w' -o dist/genios-darwin-arm64 ./cmd/genios
GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o dist/genios-linux-amd64 ./cmd/genios
GOOS=windows GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o dist/genios-windows-amd64.exe ./cmd/genios
```

## 认证与项目配置

```bash
./bin/genios setup
./bin/genios auth
```

`setup` 启动只监听 `127.0.0.1` 的本地页面，只负责账号密码和 session。WorkspaceID 属于项目配置：把它写入使用方项目根目录的 `genios-project.md`，CLI 会自动读取；也可以临时设置 `GENIOS_TEAM_WORKSPACE` 覆盖它。

凭据和 session 默认保存在操作系统用户配置目录并使用 `0600`。自定义凭据可用 `GENIOS_CREDENTIALS_FILE`，自定义 session 可用 `GENIOS_SESSION_FILE`；session 必须放在项目目录外。

## 命令

```text
genios setup
genios auth [--credentials FILE] [--session-file FILE]
genios api ACTION [JSON] [--service app]
genios chat stream|block TEXT
genios flow check|run|reset|add|set|link ...
genios debug APP_ID ...
genios qa upload ...
genios traces errors|messages ...
genios publish APP_ID [--apply]
```

写入类命令默认打印执行计划，使用 `--apply` 才执行平台写操作。完整参数和平台约束见上级目录的 [`SKILL.md`](SKILL.md) 及 `references/`。

## Release

`.github/workflows/build-genios.yml` 只在推送 `v*` 标签时运行 `go test`、`go vet`，为 macOS、Linux 和 Windows 构建二进制，并把 `SKILL.md`、`project.example.md`、`references/`、`evals/` 和 `bin/genios` 打包成完整 skill 压缩包后创建 GitHub Release。
