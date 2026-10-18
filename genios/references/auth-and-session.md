# 认证、会话与调用格式

## 两套 API

| | 对话 API（Agent API） | 平台管理 API（Platform API） |
|---|---|---|
| 用途 | 和已发布智能体对话 | 建/改/删智能体、工作流、问答库、发布 |
| 网关 | `/api/proxy/api/v1/<接口>`（如 `create_conversation`、`chat_query_v2`、`get_conversation_messages`） | `/api/<service>?Action=<X>&Version=<V>` |
| 认证 | 请求头 `Apikey: <发布渠道的 API Key>` | 登录会话 cookie + `x-csrf-token` |
| 客户端 | `genios chat stream|block`（`GENIOS_KEY_FILE` 指向 Key 文件） | `genios api` |

账号中心的 AccessKey/SecretKey 只对未开放的 `:30040` 端口有效，校外用不了；管理 API 只能走登录会话。

## 管理 API 请求格式

```
POST https://coze.nankai.edu.cn/api/<service>?Action=<Action>&Version=<Version>&X-Account-Id=1000000000
Content-Type: application/json
x-csrf-token: <cookie 中 x-csrf-token 的值>
x-top-region: cn-north-1
WorkspaceID: <团队空间ID>
Cookie: <整串会话 cookie>
Body: JSON（写接口里也显式放 WorkspaceID）
```

| service | Version | 常用 Action |
|---|---|---|
| `app` | `2023-08-01` | 智能体、工作流、问答库、发布、API Key |
| `iam` | `2024-12-25` | `ListUser`、`ListTenantIDP`、`GetTenantSupportProducts` |
| `aigw` | `2023-08-01` | `ListModelByWorkspaceGrant`（团队空间可用模型及参数范围） |
| `observe` | `2025-05-01` | `ListTraceSpans`（调用链与上游原始报错） |

响应：`{"ResponseMetadata": {..., "Error": {...}?}, "Result": {...}}`。`Error` 存在即业务失败；
会话过期时不会返回 JSON，而是 302 到统一身份认证或直接给登录页 HTML。

## 自动登录链路（`genios auth`，仅限开发阶段）

1. `GET https://coze.nankai.edu.cn/` 一路跳转：飞连网关 `/corplink/agw` → `iam.nankai.edu.cn/api/oidc/authorize`
   → `iam.nankai.edu.cn/login`。登录页 HTML 的 `globalInfo.VERSION` 里有前端版本号 `portal-fe-x.y.z`。
2. `POST https://iam.nankai.edu.cn/api/v1/login?os=web&t=<毫秒时间戳>`
   - 请求头：`csrf-token`（取 iam 域 cookie `csrf-token`）、`X-Fe-Version`、`Page-Name: portal`、`Accept-Language: zh`。
   - 请求体：`{"account": 学工号, "password": 加密后, "login_scene": "feilian", "account_type": "userid"}`。
     `account_type` 来自公开接口 `GET /api/login/setting?login_scene=feilian` 的 `login_account`，少了它返回
     `40000 参数错误`。
   - 密码加密（与登录页 crypto-js 逐字节一致）：key = `MD5("9007199254740991")` 的 32 位十六进制串（UTF-8 当 AES-256
     密钥），iv = `SHA1(key)` 十六进制的前 16 位，AES-CBC + PKCS7，输出十六进制。
   - 成功：`{"code":0,"data":{"result":"success","next":{"action":"GoToLink","link":"/api/oidc/authorize?..."}}}`。
     `next.action == "2FA"` 表示需要二次验证，脚本会报错退出，不要绕过。
3. `GET next.link`：完成飞连网关回调，平台域拿到 `corplink_at`、`corplink_it`。
4. HiAgent 自己的 OAuth2（打开首页不会自动触发，要主动调）：
   - `POST /api/iam?Action=ListTenantIDP&Version=2024-12-25`，body `{"TenantName":"","Offset":0,"Limit":4,"Status":1}`
     → 南开 IdP：`Id "1"`、`IDPType "oauth"`、租户 `dev`。
   - `POST /api/auth/login`，body `{"SSO":"Oauth","IdpID":"1","RedirectUrl":"https://coze.nankai.edu.cn/"}`
     → 返回 `redirect_uri`；GET 它，统一身份认证已登录会直接回调 `/api/auth/callback`。
5. 平台下发 `tenant`、`_csrf`、`x-csrf-token`。把平台域全部 cookie 拼成 `COOKIE`，`x-csrf-token` 的值作 `CSRF`，
   用只读的 `ListWorkflows` 验证后写入 `session.env`（`COOKIE=...` / `CSRF=...`，权限 600，项目目录外）。

注意：跳转后的 URL 可能带显式端口（`iam.nankai.edu.cn:443`），判断域名用 `hostname` 而不是 `netloc`。

## 会话寿命与续期

- 实测会话有时半小时左右就失效。Go CLI 捕获 302/401/登录页后，会读取本地凭据重新登录，写回 session 文件并重试一次。
- 没有账号密码时运行 `genios setup`，在只监听本机的管理页面中输入；不要把密码放进对话、命令行或项目文件。
- 使用 `genios api <Action> <JSON> [--service <service>]`，
  不要另写 urllib 调用，否则拿不到自动续期。`call()` 按服务自动选 Version（见上表，可用 `version=` 覆盖），并自动在
  请求体里补上 WorkspaceID。
- `GENIOS_CREDENTIALS_FILE` 和 `GENIOS_SESSION_FILE` 可覆盖默认路径；默认值都在操作系统用户配置目录中。自定义凭据到项目内时必须被 git 忽略，session 则必须放在项目目录外。
