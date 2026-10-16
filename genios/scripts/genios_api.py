#!/usr/bin/env python3
"""NK-GeniOS 平台管理 API 客户端：会话读写、统一调用、会话过期自动续期。

    import genios_api as ga
    session = ga.load_session()                         # 读 GENIOS_SESSION_FILE
    items = ga.call(session, ga.workspace(), "ListWorkflows", {"PageNumber": 1, "PageSize": 20})

- `call()` 自动带上 WorkspaceID（请求头与请求体），按服务选 Version（app/aigw 2023-08-01、iam 2024-12-25、
  observe 2025-05-01，可用 version= 覆盖）；遇到 302/401/登录页时用账号密码文件自动重新登录一次再重试。
- 项目根目录：环境变量 GENIOS_PROJECT_ROOT → 当前目录所在 git 仓库 → 本脚本所在 git 仓库。
- 账号密码文件默认 <项目根>/genios-credentials.env（可用 GENIOS_CREDENTIALS_FILE 覆盖），会话文件由
  GENIOS_SESSION_FILE 指定且必须在项目目录外。
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("GENIOS_BASE_URL_MANAGE", "https://coze.nankai.edu.cn/api")
ACCOUNT_ID = "1000000000"
VERSIONS = {"app": "2023-08-01", "aigw": "2023-08-01", "iam": "2024-12-25", "observe": "2025-05-01"}
TIMEOUT = 30


def _git_root(start: str):
    result = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def project_root() -> str:
    return (os.environ.get("GENIOS_PROJECT_ROOT") or _git_root(os.getcwd())
            or _git_root(os.path.dirname(os.path.abspath(__file__))) or os.getcwd())


def workspace() -> str:
    """团队空间 ID，只从环境变量读取，避免脚本默认写进个人空间。"""
    value = os.environ.get("GENIOS_TEAM_WORKSPACE")
    if not value:
        sys.exit("请设置 GENIOS_TEAM_WORKSPACE 为团队空间 ID（资源禁止落到个人空间）")
    return value


def require_team_workspace(given: str) -> None:
    if given != workspace():
        sys.exit("--workspace 必须等于 GENIOS_TEAM_WORKSPACE（团队空间），禁止写入个人空间")


def credentials_file() -> str:
    return os.path.expanduser(os.environ.get("GENIOS_CREDENTIALS_FILE")
                              or os.path.join(project_root(), "genios-credentials.env"))


def _outside_project(path: str) -> str:
    path = os.path.abspath(os.path.expanduser(path))
    if path.startswith(project_root() + os.sep):
        sys.exit("会话文件不能放在项目目录内（它含完整登录态），请把 GENIOS_SESSION_FILE 指到项目外")
    return path


def load_session() -> dict:
    path = os.environ.get("GENIOS_SESSION_FILE", "")
    if not path:
        sys.exit("缺少会话：设置 GENIOS_SESSION_FILE 指向项目外的 session.env")
    path = _outside_project(path)
    if not os.path.exists(path):
        if relogin_into({}, path):
            return load_session()
        sys.exit(f"会话文件 {path} 不存在，且没有账号密码文件可以自动登录")
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            key, sep, value = line.strip().partition("=")
            if sep:
                env[key] = value.strip().strip("'\"")
    if not env.get("COOKIE") or not env.get("CSRF"):
        sys.exit("会话文件缺少 COOKIE 或 CSRF")
    return env


def write_session(creds: dict, path: str) -> None:
    path = _outside_project(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"COOKIE={creds['COOKIE']}\nCSRF={creds['CSRF']}\n")


class SessionExpired(Exception):
    """管理 API 返回登录页或 401/302：会话过期。"""


def relogin_into(session: dict, target: str) -> bool:
    """用账号密码文件登录，写入 target 并原地更新 session；没有账号密码文件时返回 False。"""
    import genios_auth
    if not os.path.exists(credentials_file()):
        return False
    try:
        creds = genios_auth.login(*genios_auth.read_credentials(credentials_file()))
    except genios_auth.LoginError as err:
        sys.exit(f"会话已过期，自动重新登录失败：{err}")
    write_session(creds, target)
    session.update(creds)  # 调用方持有的同一个 dict，后续请求直接用新会话
    print("会话已过期，已用账号密码自动重新登录", file=sys.stderr)
    return True


def relogin(session: dict) -> bool:
    target = os.environ.get("GENIOS_SESSION_FILE")
    return bool(target) and relogin_into(session, target)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _call_once(session: dict, ws: str, action: str, body: dict, svc: str, version: str) -> dict:
    url = f"{BASE}/{svc}?Action={action}&Version={version}&X-Account-Id={ACCOUNT_ID}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "accept": "application/json",
        "x-csrf-token": session["CSRF"], "x-top-region": "cn-north-1",
        "WorkspaceID": ws, "Cookie": session["COOKIE"]})
    try:
        resp = urllib.request.build_opener(_NoRedirect).open(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 401):
            raise SessionExpired(f"HTTP {e.code}") from e
        sys.exit(f"{action}: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:1000]}")
    text = resp.read().decode("utf-8", "replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        if text.lstrip().startswith("<"):
            raise SessionExpired("返回登录页 HTML") from e
        sys.exit(f"{action}: 返回非 JSON，前 200 字：{text[:200]}")
    err = (data.get("ResponseMetadata") or {}).get("Error")
    if err:
        sys.exit(f"{action}: 业务错误 {json.dumps(err, ensure_ascii=False)}")
    return data.get("Result") or {}


def call(session: dict, ws: str, action: str, body: dict, svc: str = "app", version: str = None) -> dict:
    """调用管理 API；body 里没有 WorkspaceID 时自动补上。业务错误直接退出并打印平台返回的错误。"""
    body = {"WorkspaceID": ws, **body}
    version = version or VERSIONS.get(svc, "2023-08-01")
    try:
        return _call_once(session, ws, action, body, svc, version)
    except SessionExpired as expired:
        if not relogin(session):
            sys.exit(f"{action}: 登录态失效（{expired}），请运行 genios_auth.py 或重新获取 cookie 与 csrf")
    try:
        return _call_once(session, ws, action, body, svc, version)
    except SessionExpired as expired:
        sys.exit(f"{action}: 自动重新登录后仍然失效（{expired}）")


if __name__ == "__main__":
    # 用法：python3 genios_api.py <Action> '<json body>' [service] —— 一次性只读查询很方便
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    result = call(load_session(), workspace(), sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {},
                  sys.argv[3] if len(sys.argv) > 3 else "app")
    print(json.dumps(result, ensure_ascii=False, indent=1))
