#!/usr/bin/env python3
"""用平台“调试”接口跑智能体草稿，不需要发布、不需要等渠道审核。

    python3 genios_debug.py <AppID> "第一句" "第二句" ...     # 同一个会话里依次发送，打印每轮回复
    python3 genios_debug.py <AppID> --events "你好"           # 同时打印原始事件

对话型智能体传草稿 AppConfig，对话流型传草稿 ChatFlowConfig（脚本从 GetAppConfigDraft 自动判断）。

已知限制：调试模式下对话流的用户变量能写入（GetAppUserVariables 查得到），但下一轮读不回来。
涉及跨轮状态的验证要发布后用对话 API（genios_chat.py）做。
"""
import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from genios_api import BASE, call, load_session, workspace  # noqa: E402

# 流式调试走 bypass 网关；写成 /api/app?Action=ChatQueryDebug 会返回 200 但内容为空
DEBUG_URL = BASE + "/bypass/app?Version=2023-08-01&Action=ChatQueryDebug"
READONLY = ("UpdateTime", "ModelName", "SummaryModelName", "Version", "VersionDescription")


def draft_body(session, ws, app_id) -> dict:
    """按智能体类型组装调试请求需要的草稿配置。"""
    result = call(session, ws, "GetAppConfigDraft", {"AppID": app_id})
    chatflow = result.get("ChatFlowConfigDraft") or {}
    if chatflow.get("WorkflowID"):
        return {"ChatFlowConfig": {k: v for k, v in chatflow.items() if k != "UpdateTime"}}
    config = {k: v for k, v in result["AppConfigDraft"].items() if k not in READONLY}
    return {"AgentMode": "Single", "AppConfig": config}


def parse_event(line: str):
    """调试流每行形如 `data:data: {...}`，要剥两层前缀。"""
    line = line.strip()
    if not line.startswith("data:"):
        return None
    while line.startswith("data:"):
        line = line[5:].strip()
    try:
        return json.loads(line)
    except ValueError:
        return None


def debug(session, ws, app_id, query, conversation_id=None, body=None, on_event=None):
    """发送一轮调试对话，返回 (回复文本, 会话 ID, 事件列表)。"""
    payload = {"WorkspaceID": ws, "AppID": app_id, "Query": query, **(body or draft_body(session, ws, app_id))}
    if conversation_id:
        payload["ConversationID"] = conversation_id
    req = urllib.request.Request(DEBUG_URL, data=json.dumps(payload).encode(), method="POST", headers={
        "Content-Type": "application/json", "accept": "text/event-stream", "x-csrf-token": session["CSRF"],
        "x-top-region": "cn-north-1", "WorkspaceID": ws, "Cookie": session["COOKIE"]})
    answer, events = "", []
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw in resp:
            event = parse_event(raw.decode("utf-8", "replace"))
            if event is None:
                continue
            events.append(event)
            if on_event:
                on_event(event)
            conversation_id = conversation_id or event.get("conversation_id")
            if event.get("event") == "message":
                answer += event.get("answer", "")
    return answer, conversation_id, events


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("app_id")
    p.add_argument("queries", nargs="+", help="同一会话里依次发送的用户消息")
    p.add_argument("--events", action="store_true", help="打印原始事件")
    args = p.parse_args()
    session, ws = load_session(), workspace()
    body = draft_body(session, ws, args.app_id)
    show = (lambda e: print("  ·", json.dumps(e, ensure_ascii=False)[:300])) if args.events else None
    conversation = None
    for query in args.queries:
        answer, conversation, _ = debug(session, ws, args.app_id, query, conversation, body, show)
        print(f"> {query}\n{answer}\n")


if __name__ == "__main__":
    main()
