#!/usr/bin/env python3
"""平台行为验证：区分“工作流输出不进下一轮模型上下文”是平台原因还是模型能力原因。

临时工作流每次调用生成随机暗号，只放在输出字段 secret 中，不出现在 reply 里；
第 2 轮问智能体暗号。能原样答出 → 输出在历史里（当初失败是模型能力）；答不出 → 平台不放进历史。
所有临时资源建在团队空间，结束时删除（DeleteAPIKey → DeleteApp → DeleteWorkflow）。
2026-09-22 结果：doubao-seed-2-0-mini、doubao-seed-2-1-pro 各 3 次均拿不到暗号，确认为平台行为。
用法（会话过期时 genios_deploy.call 自动续期）：
    export GENIOS_SESSION_FILE=<scratchpad>/session.env GENIOS_TEAM_WORKSPACE=<团队空间ID>
    GENIOS_USER_ID=... GENIOS_ICON=upload/full/... GENIOS_PROBE_MODELS=名称=模型ID,... python3 genios_probe_history.py
结果写到 GENIOS_SESSION_FILE 同目录的 state_probe_result.json。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genios_flow as build  # noqa: E402
from genios_api import call, load_session, workspace  # noqa: E402

W = workspace()
USER_ID = os.environ.get("GENIOS_USER_ID") or sys.exit("请设置 GENIOS_USER_ID（平台内部 UserID，建智能体用）")
ICON = os.environ.get("GENIOS_ICON") or sys.exit("请设置 GENIOS_ICON（有效的 upload/full/... 图标路径，建工作流用）")
# 待比较的模型：GENIOS_PROBE_MODELS="名称=ID,名称=ID"
MODELS = dict(pair.split("=", 1) for pair in os.environ.get("GENIOS_PROBE_MODELS", "").split(",") if "=" in pair) \
    or sys.exit("请设置 GENIOS_PROBE_MODELS，例如 mini=d9a3...,pro=d9a4...")
RUNS = 3
PROMPT = """你是一个测试助手。
- 用户要求“记录”时，调用工作流 [tmp-state-probe]，参数 q 传用户原话，然后只回复工具输出里的 reply 字段。
- 用户问“暗号”或 secret 时，从你之前调用工具得到的返回结果里找出 secret 字段，原样回答；如果你看不到之前的工具返回结果，就回答“我看不到之前的工具返回结果”，不要猜测或编造。"""
CODE = '''import uuid
def handler(params):
    return {"reply": "已记录，本次记录完成。", "secret": "NONCE-" + uuid.uuid4().hex[:12].upper()}
'''

session = load_session()
# 临时 API Key 与结果放在会话文件所在目录（项目目录外）
OUT_DIR = os.path.dirname(os.path.abspath(os.path.expanduser(os.environ["GENIOS_SESSION_FILE"])))


def api(action, body):
    return call(session, W, action, {"WorkspaceID": W, **body})


def make_workflow():
    flow_id = api("CreateWorkflow", {"Name": "tmp-state-probe", "Description": "临时探测：工作流输出是否进入对话历史，用完即删",
                                     "Icon": ICON})["ID"]
    flow = build.Flow(session, W, flow_id)
    s, e = flow.reset()
    node = flow.add("Code", "生成暗号", 400, 200)
    flow.set(s, "Start", "Start", build.start_inputs([("q", True, "用户原话")]))
    flow.set(node, "生成暗号", "Code", {"Input": [build.ref(s, "q")], "Language": 1, "Code": CODE,
                                       "TimeoutSeconds": 30, "Retries": 0,
                                       "OutputSchema": [{"Name": "reply", "Type": 0}, {"Name": "secret", "Type": 0}]})
    flow.set(e, "End", "End", build.end([("reply", node, "reply"), ("secret", node, "secret")]))
    flow.link([(s, node), (node, e)])
    assert flow.check().get("Valid"), "探测工作流校验未通过"
    api("PublishWorkflow", {"ID": flow_id, "Version": "v0.0.1", "VersionNote": "临时探测"})
    return flow_id


def publish(app_id, model_id):
    draft = api("GetAppConfigDraft", {"AppID": app_id})["AppConfigDraft"]
    cfg = {k: v for k, v in draft.items() if k not in ("UpdateTime", "ModelName", "SummaryModelName", "Version",
                                                     "VersionDescription")}
    cfg["ModelID"] = model_id
    cfg["ModelConfig"] = dict(cfg.get("ModelConfig") or {}, RoundsReserved=100, MaxTokens=1024,
                              ReasoningSwitchType="disabled", ReasoningMode=False, Strategy="function_call")
    api("SaveAppConfigDraft", {"AppID": app_id, "AgentMode": "Single", "AppConfigDraft": cfg})
    pid = api("PublishAppConfig", {"AppID": app_id, "AgentMode": "Single", "AppConfig": cfg})["PublishID"]
    conf = {"APIPublishConfigData": {"Enabled": True}}
    api("SaveAppBuiltinChannelPublishConfigDraft", {"AppID": app_id, "ChannelCode": "api", "BuiltinChannelConfigData": conf})
    api("PublishAppChannel", {"AppID": app_id, "BuiltinChannels": ["api"], "BuiltinChannelPublishConfigData": conf,
                              "Description": "临时探测"})
    for _ in range(40):
        items = api("ListPublishAppChannelHistory", {"AppID": app_id, "PageNumber": 1, "PageSize": 5}).get("Items") or []
        rec = next((x for x in items if x["PublishID"] == pid), None)
        status = rec["ChannelPublishStatusList"][0]["Status"] if rec else "InReview"
        if status != "InReview":
            return status
        time.sleep(15)
    return "timeout"


def chat_round(ga, conv, text):
    answer, calls = [], []
    for evt in ga.chat_stream(text, conv):
        if evt.get("event") == "agent_thought_end" and evt.get("observation"):
            calls.append(evt["observation"])
        if evt.get("event") == "message":
            answer.append(evt.get("answer") or "")
    return "".join(answer), calls


def probe(ga, label):
    results = []
    for i in range(RUNS):
        conv = ga.create_conversation()
        _, calls = chat_round(ga, conv, "请帮我记录一下今天的测试")
        secret = json.loads(calls[-1]).get("secret") if calls else None
        answer, calls2 = chat_round(ga, conv, "刚才工具返回结果里的暗号（secret 字段）是什么？请原样给出。")
        hit = bool(secret) and secret in answer
        results.append({"secret": secret, "answer": answer[:120], "hit": hit, "tool_called_again": bool(calls2)})
        print(f"[{label}] 第{i + 1}次 暗号={secret} 命中={hit} 第2轮又调工具={bool(calls2)} 回答={answer[:80]!r}", flush=True)
        if i == 0:
            history = ga.post("get_conversation_messages", {"AppConversationID": conv, "UserID": ga.USER_ID, "Limit": 20})
            dump = json.dumps(history, ensure_ascii=False)
            print(f"[{label}] 历史消息接口里是否出现暗号：{bool(secret) and secret in dump}；"
                  f"是否含 agent_thoughts 字段：{'agent_thought' in dump.lower() or 'AgentThought' in dump}", flush=True)
    return results


def main():
    flow_id = app_id = key_id = None
    summary = {}
    try:
        flow_id = make_workflow()
        print("探测工作流", flow_id, flush=True)
        app_id = api("CreateAppWithConfig", {"UserID": USER_ID, "Name": "tmp-state-probe-agent",
                                             "Description": "临时探测智能体，用完即删", "Prompt": PROMPT,
                                             "WorkflowIDs": [flow_id], "OnlyDraft": True})
        app_id = app_id.get("AppID") or app_id.get("ID")
        print("临时智能体", app_id, flush=True)
        key = api("CreateAppAPIKey", {"AppID": app_id, "Expired": "1h", "Description": "临时探测，用完即删"})
        key_id = key["AppKeyID"]
        key_file = os.path.join(OUT_DIR, "probe_key.txt")
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(key["APIKey"])
        os.environ["GENIOS_KEY_FILE"] = key_file
        import genios_agent as ga
        for label, model_id in MODELS.items():
            status = publish(app_id, model_id)
            print(f"[{label}] 渠道审核：{status}", flush=True)
            if status != "Success":
                summary[label] = f"渠道审核未通过：{status}"
                continue
            summary[label] = probe(ga, label)
    finally:
        if key_id and app_id:
            api("DeleteAppAPIKey", {"AppID": app_id, "APIKeyID": key_id})
        if app_id:
            api("DeleteApp", {"AppID": app_id})
        if flow_id:
            api("DeleteWorkflow", {"ID": flow_id})
        for f in ("probe_key.txt",):
            p = os.path.join(OUT_DIR, f)
            if os.path.exists(p):
                os.remove(p)
        print("临时资源已清理：", {"workflow": flow_id, "app": app_id, "key": key_id}, flush=True)
    with open(os.path.join(OUT_DIR, "state_probe_result.json"), "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
