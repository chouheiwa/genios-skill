#!/usr/bin/env python3
"""排查“大模型接口调用出错，请联系管理员”：从平台观测数据里拿上游模型的原始报错（只读）。

这句提示是平台对外统一的兜底文案；真实原因在调用链 span 的 Status.Message 里，例如
`400 InvalidParameter: Unsupported thinking type for the current model: auto`、`429 ... TPM limit`。

    export GENIOS_SESSION_FILE=<项目外>/session.env GENIOS_TEAM_WORKSPACE=<团队空间ID>
    python3 genios_traces.py errors [--limit 500] [--message-id <消息ID>] [--trace-id <TraceID>]
    python3 genios_traces.py messages --app-id <AppID> [--hours 12] [--limit 30]

errors   ：ListTraceSpans（service observe，Version 2025-05-01），按开始时间倒序翻页，只打印有报错信息的 span。
messages ：ListAppMessageWithConLog（app），列出智能体最近的消息及状态，定位是哪个时间段、哪条消息出错。
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from genios_api import call, load_session, workspace  # noqa: E402

PAGE = 200


def spans(session, ws, limit, message_id=None, trace_id=None):
    body = {"PageSize": min(PAGE, limit), "Sort": [{"SortBy": "StartTime", "SortOrder": "Desc"}]}
    if trace_id:
        body["SimpleFilters"] = [{"TraceID": {"Operator": "Equal", "Value": trace_id}}]
    elif message_id:
        body["SimpleFilters"] = [{"MessageID": {"Operator": "Equal", "Value": message_id}}]
    out = []
    while len(out) < limit:
        result = call(session, ws, "ListTraceSpans", body, svc="observe")
        out += result.get("Items") or []
        if not result.get("HasMore") or not result.get("LastID"):
            break
        body["LastID"] = result["LastID"]
    return out[:limit]


def errors(args):
    session, ws = load_session(), workspace()
    found = 0
    for span in spans(session, ws, args.limit, args.message_id, args.trace_id):
        status = span.get("Status") or {}
        if status.get("Code") not in ("ERROR",) and not status.get("Message"):
            continue
        found += 1
        attrs = span.get("Attributes") or {}
        model = attrs.get("gen_ai.request.model") or attrs.get("model_name") or ""
        print(f"{span.get('StartTime', '')[:19]}  {span.get('Name')}  [{attrs.get('span_type', '')}] {model}")
        print(f"    TraceID={span.get('Context', {}).get('TraceID')}  {status.get('Message', '')[:400]}")
    print(f"共 {found} 条有报错的 span（检查了最近 {args.limit} 条）")


def messages(args):
    session, ws = load_session(), workspace()
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(hours=args.hours)
    body = {"AppID": args.app_id,
            "ListOpt": {"Sort": [{"SortField": "created_at", "SortOrder": "desc"}], "PageNumber": 1, "PageSize": args.limit},
            "Filter": {"StartTime": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "EndTime": end.strftime("%Y-%m-%dT%H:%M:%S.000Z")}}
    result = call(session, ws, "ListAppMessageWithConLog", body)
    items = result.get("AppMessageWithConLogList") or []
    for item in items:
        query, answer = item.get("QueryInfo") or {}, item.get("AnswerInfo") or {}
        created = datetime.datetime.fromtimestamp(query.get("CreatedTime") or 0).strftime("%m-%d %H:%M:%S")
        print(f"{created}  状态={item.get('MessageStatus')}  会话={item.get('AppConversationID')}  消息={query.get('QueryID')}")
        print(f"    问：{(query.get('Query') or '')[:60]}  答：{(answer.get('Answer') or '')[:80]!r}")
    print(f"共 {len(items)} 条（最近 {args.hours} 小时，Total={result.get('Total')}）")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("errors")
    e.add_argument("--limit", type=int, default=500)
    e.add_argument("--message-id")
    e.add_argument("--trace-id")
    m = sub.add_parser("messages")
    m.add_argument("--app-id", required=True)
    m.add_argument("--hours", type=int, default=12)
    m.add_argument("--limit", type=int, default=30)
    args = p.parse_args()
    (errors if args.cmd == "errors" else messages)(args)


if __name__ == "__main__":
    main()
