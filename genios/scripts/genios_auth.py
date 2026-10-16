#!/usr/bin/env python3
"""用南开统一身份认证账号密码登录 NK-GeniOS，生成平台管理 API 用的会话文件（session.env）。

⚠️ 仅限开发阶段使用：只供本机开发脚本调用平台管理 API。不得部署到演示服务、后端或交付物中，
不得用于正式/生产环境；生产环境应使用平台发布渠道的 API Key 或管理员提供的正式鉴权方式。

登录链路（2026-09-22 按登录页前端代码与跳转实测整理）：
  coze.nankai.edu.cn → 飞连网关 /corplink/agw（OIDC）→ iam.nankai.edu.cn/login
  → POST iam /api/v1/login（密码 AES-CBC 加密）→ 两次授权回调
    （飞连 /corplink/agw/callback；HiAgent 经 ListTenantIDP + POST /api/auth/login 取授权地址，回调 /api/auth/callback）
  → 平台下发 tenant、_csrf、x-csrf-token

账号密码默认读取项目根目录的 genios-credentials.env（已在 .gitignore 中忽略，权限必须是 600），格式：
    ACCOUNT=学号或工号
    PASSWORD=密码
用法：
    python3 <skill>/scripts/genios_auth.py [--credentials genios-credentials.env] \\
        [--session-file <scratchpad>/session.env]
项目根目录、默认账号密码文件与会话文件规则见 genios_api.py。
登录需要短信、邮件等二次验证时会直接报错退出，不会绕过。
"""
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from urllib.parse import urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genios_api  # noqa: E402

ROOT = genios_api.project_root()
PLATFORM = "https://coze.nankai.edu.cn"
IAM = "https://iam.nankai.edu.cn"
DEFAULT_CREDENTIALS = genios_api.credentials_file()
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")
TIMEOUT = 30


class LoginError(RuntimeError):
    """登录失败，消息面向使用者，不含密码或 cookie。"""


def encrypt_password(password: str) -> str:
    """与登录页 aesEncrypt 一致：key = MD5(Number.MAX_SAFE_INTEGER) 十六进制串，iv = SHA1(key) 前 16 位。"""
    key = hashlib.md5(str(2 ** 53 - 1).encode()).hexdigest()
    iv = hashlib.sha1(key.encode()).hexdigest()[:16]
    cipher = AES.new(key.encode(), AES.MODE_CBC, iv.encode())
    return cipher.encrypt(pad(password.strip().encode("utf-8"), AES.block_size)).hex()


def git_ignored(path: str) -> bool:
    """项目内的凭据文件必须被 git 忽略，防止误提交。"""
    result = subprocess.run(["git", "-C", ROOT, "check-ignore", "-q", path], capture_output=True)
    return result.returncode == 0


def read_credentials(path: str) -> tuple:
    path = os.path.abspath(os.path.expanduser(path))
    if path.startswith(ROOT + os.sep) and not git_ignored(path):
        raise LoginError(f"{path} 在项目目录内但没有被 git 忽略，请先加入 .gitignore")
    if not os.path.exists(path):
        raise LoginError(f"找不到账号密码文件 {path}；格式见本文件开头说明")
    if stat.S_IMODE(os.stat(path).st_mode) & 0o077:
        raise LoginError(f"{path} 权限过宽，请先执行 chmod 600")
    values = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            key, sep, value = line.strip().partition("=")
            if sep:
                values[key.strip()] = value.strip()
    if not values.get("ACCOUNT") or not values.get("PASSWORD"):
        raise LoginError(f"{path} 缺少 ACCOUNT 或 PASSWORD")
    return values["ACCOUNT"], values["PASSWORD"]


def _iam_headers(session: requests.Session, fe_version: str) -> dict:
    return {"content-type": "application/json", "Accept-Language": "zh", "Page-Name": "portal",
            "X-Version-Check": "0", "X-Fe-Version": fe_version,
            "csrf-token": session.cookies.get("csrf-token", domain="iam.nankai.edu.cn") or "",
            "admin-csrf-token": ""}


def _open_login_page(session: requests.Session) -> str:
    """从平台入口一路跳转到统一身份认证登录页，返回前端版本号。"""
    page = session.get(PLATFORM + "/", timeout=TIMEOUT)
    if urlparse(page.url).hostname != "iam.nankai.edu.cn" or not urlparse(page.url).path.startswith("/login"):
        raise LoginError(f"没有跳转到统一身份认证登录页（停在 {urlparse(page.url).netloc}{urlparse(page.url).path}）")
    match = re.search(r"VERSION:\s*'portal-fe-([^']+)'", page.text)
    return match.group(1) if match else ""


def _submit_password(session: requests.Session, fe_version: str, account: str, password: str) -> dict:
    url = f"{IAM}/api/v1/login?os=web&t={int(time.time() * 1000)}"
    # account_type 取自 /api/login/setting 的 login_account（南开为 userid，即学号/工号）
    body = {"account": account.strip(), "password": encrypt_password(password), "login_scene": "feilian",
            "account_type": "userid"}
    resp = session.post(url, data=json.dumps(body), headers=_iam_headers(session, fe_version), timeout=TIMEOUT)
    try:
        result = resp.json()
    except ValueError as err:
        raise LoginError(f"登录接口返回非 JSON（HTTP {resp.status_code}）") from err
    if result.get("code") not in (0, None):
        raise LoginError(f"登录被拒绝：{result.get('code')} {result.get('message')}")
    return result.get("data") or {}


def _follow_after_login(session: requests.Session, data: dict) -> None:
    """登录成功返回 {"result": "success", "next": {"action": "GoToLink", "link": 授权地址}}。"""
    step = data.get("next") or {}
    action = step.get("action")
    if action == "2FA":
        raise LoginError("账号需要二次验证（短信/邮件等），无法只凭账号密码自动登录")
    if data.get("result") != "success" or action != "GoToLink" or not step.get("link"):
        raise LoginError(f"登录后需要额外步骤：result={data.get('result')} action={action}"
                         "（例如修改初始密码、补充信息），请先在浏览器完成一次")
    link = step["link"]
    session.get(link if link.startswith("http") else IAM + link, timeout=TIMEOUT)  # 飞连网关回调


def _platform_sso(session: requests.Session) -> None:
    """HiAgent 平台自己的 OAuth2：取租户 IdP，POST /api/auth/login 拿授权地址，跟随回调 /api/auth/callback。"""
    idps = session.post(f"{PLATFORM}/api/iam?Action=ListTenantIDP&Version=2024-12-25",
                        json={"TenantName": "", "Offset": 0, "Limit": 4, "Status": 1},
                        headers={"x-top-region": "cn-north-1"}, timeout=TIMEOUT).json()
    oauth = [idp for idp in (idps.get("Result") or {}).get("List") or [] if idp.get("IDPType") == "oauth"]
    if not oauth:
        raise LoginError("平台没有返回 OAuth 身份提供方（ListTenantIDP 为空）")
    resp = session.post(f"{PLATFORM}/api/auth/login", timeout=TIMEOUT, headers={"x-top-region": "cn-north-1"},
                        json={"SSO": "Oauth", "IdpID": oauth[0]["Id"], "RedirectUrl": PLATFORM + "/"})
    try:
        redirect = (resp.json().get("Result") or resp.json()).get("redirect_uri")
    except ValueError as err:
        raise LoginError(f"/api/auth/login 返回非 JSON（HTTP {resp.status_code}）") from err
    if not redirect:
        raise LoginError(f"/api/auth/login 没有返回 redirect_uri（HTTP {resp.status_code}）")
    final = session.get(redirect, timeout=TIMEOUT)  # 统一身份认证已登录，直接回调平台
    if urlparse(final.url).hostname != "coze.nankai.edu.cn":
        raise LoginError(f"平台授权回调未完成（停在 {urlparse(final.url).hostname}{urlparse(final.url).path}）")


def platform_credentials(session: requests.Session) -> dict:
    cookies = {c.name: c.value for c in session.cookies if c.domain.lstrip(".").endswith("nankai.edu.cn")
               and (c.domain.lstrip(".") == "coze.nankai.edu.cn" or c.domain.startswith("."))}
    csrf = cookies.get("x-csrf-token")
    if not csrf or "tenant" not in cookies:
        raise LoginError("平台没有下发 tenant 或 x-csrf-token cookie")
    return {"COOKIE": "; ".join(f"{k}={v}" for k, v in cookies.items()), "CSRF": csrf}


def _verify_workspace() -> str:
    return os.environ.get("GENIOS_TEAM_WORKSPACE", "")


def verify(creds: dict) -> None:
    if not _verify_workspace():
        print("未设置 GENIOS_TEAM_WORKSPACE，跳过会话的平台校验", file=sys.stderr)
        return
    resp = requests.post(f"{PLATFORM}/api/app?Action=ListWorkflows&Version=2023-08-01&X-Account-Id=1000000000",
                         data=json.dumps({"WorkspaceID": _verify_workspace(), "PageNumber": 1, "PageSize": 1}),
                         headers={"Content-Type": "application/json", "x-csrf-token": creds["CSRF"],
                                  "x-top-region": "cn-north-1", "WorkspaceID": _verify_workspace(), "Cookie": creds["COOKIE"]},
                         allow_redirects=False, timeout=TIMEOUT)
    if resp.status_code != 200 or "json" not in resp.headers.get("content-type", ""):
        raise LoginError(f"会话校验失败（HTTP {resp.status_code}）")


def login(account: str, password: str) -> dict:
    """完成整条登录链路，返回 {"COOKIE": ..., "CSRF": ...}。"""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    fe_version = _open_login_page(session)
    data = _submit_password(session, fe_version, account, password)
    _follow_after_login(session, data)
    _platform_sso(session)
    creds = platform_credentials(session)
    verify(creds)
    return creds


def write_session(creds: dict, path: str) -> None:
    genios_api.write_session(creds, path)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--credentials", default=os.environ.get("GENIOS_CREDENTIALS_FILE", DEFAULT_CREDENTIALS))
    p.add_argument("--session-file", default=os.environ.get("GENIOS_SESSION_FILE"))
    args = p.parse_args()
    if not args.session_file:
        sys.exit("请用 --session-file 或环境变量 GENIOS_SESSION_FILE 指定输出位置（项目目录外）")
    try:
        account, password = read_credentials(args.credentials)
        write_session(login(account, password), args.session_file)
    except (LoginError, requests.RequestException) as err:
        sys.exit(f"登录失败：{err}")
    print(f"登录成功，会话已写入 {args.session_file}")


if __name__ == "__main__":
    main()
