#!/usr/bin/env python3
"""NK-GeniOS 智能体对话 API 客户端（文档：api-sdk/api/agent-api-call/agent-api-documentation.md）

用法：
    export GENIOS_KEY_FILE=~/Downloads/agent-apikey.txt   # 文件里一行，就是 API Key
    python3 genios_chat.py chat "你好"             # 一问一答（blocking）
    python3 genios_chat.py stream "你好"           # 流式（SSE）
"""
import json, os, sys, urllib.request, urllib.error

BASE = os.environ.get("GENIOS_BASE", "https://coze.nankai.edu.cn/api/proxy/api/v1")
USER_ID = os.environ.get("GENIOS_USER", "dev-test")


def api_key() -> str:
    key = os.environ.get("GENIOS_API_KEY")
    if key:
        return key.strip()
    path = os.path.expanduser(os.environ.get("GENIOS_KEY_FILE", ""))
    if not path or not os.path.exists(path):
        sys.exit("缺少 API Key：设置 GENIOS_API_KEY，或用 GENIOS_KEY_FILE 指向密钥文件")
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            return line.split(":")[-1].strip() if ":" in line else line
    sys.exit("密钥文件是空的")


def post(path: str, body: dict, stream: bool = False):
    req = urllib.request.Request(
        f"{BASE}/{path}", data=json.dumps(body).encode(), method="POST",
        headers={"Apikey": api_key(), "Content-Type": "application/json",
                 **({"Accept": "text/event-stream"} if stream else {})})
    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
    return resp if stream else json.loads(resp.read())


def create_conversation(user_id: str = USER_ID) -> str:
    return post("create_conversation", {"UserID": user_id})["Conversation"]["AppConversationID"]


def chat(query: str, conv_id: str = None, user_id: str = USER_ID) -> dict:
    conv_id = conv_id or create_conversation(user_id)
    return post("chat_query_v2", {"AppConversationID": conv_id, "Query": query,
                                  "UserID": user_id, "ResponseMode": "blocking"})


def chat_stream(query: str, conv_id: str = None, user_id: str = USER_ID):
    conv_id = conv_id or create_conversation(user_id)
    resp = post("chat_query_v2", {"AppConversationID": conv_id, "Query": query,
                                  "UserID": user_id, "ResponseMode": "streaming"}, stream=True)
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        try:
            evt = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        yield evt


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, text = sys.argv[1], " ".join(sys.argv[2:])
    if cmd == "chat":
        print(json.dumps(chat(text), ensure_ascii=False, indent=1)[:4000])
    elif cmd == "stream":
        for evt in chat_stream(text):
            piece = evt.get("answer") or evt.get("Answer") or ""
            if piece:
                print(piece, end="", flush=True)
        print()
    else:
        sys.exit(__doc__)
