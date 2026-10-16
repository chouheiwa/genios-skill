#!/usr/bin/env python3
"""发布 NK-GeniOS 单智能体：写入提示词与模型参数 → 发布配置 → 发布 API 渠道 → 等待自动审核。

模型以平台草稿为准（在界面或草稿里切换）；其余只在传入参数时覆盖。默认只打印将要发布的配置，加 --apply 才写入。
    export GENIOS_SESSION_FILE=<项目外>/session.env GENIOS_TEAM_WORKSPACE=<团队空间ID>
    python3 genios_publish.py --app-id <AppID> [--prompt-file 提示词.md [--prompt-marker '## 2. 系统提示词']] \\
        [--max-tokens 2048] [--reasoning disabled] [--history-rounds 100] \\
        [--qa-match auto --qa-similarity 0.92] [--apply]

--prompt-marker 给出时，取文件中该标记之后第一个 ```text 代码块作为提示词；否则整个文件就是提示词。
发布保护：草稿里思考模式不是 disabled 且没有显式传 --reasoning 时拒绝发布——部分模型在 API 渠道下开思考会直接报
“大模型接口调用出错”（doubao-seed-2-1-pro 的 auto 即如此），确认该模型支持后用 --reasoning 明确指定。
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from genios_api import call, load_session, require_team_workspace, workspace  # noqa: E402

DROP_KEYS = ("UpdateTime", "ModelName", "SummaryModelName", "Version", "VersionDescription")  # 只读字段，写回会报错
REVIEW_TIMEOUT = 600
API_CHANNEL = {"APIPublishConfigData": {"Enabled": True}}


def extract_block(markdown: str, marker: str) -> str:
    """取 marker 之后第一个 ```text 代码块。"""
    if marker not in markdown:
        sys.exit(f"提示词文档中找不到「{marker}」")
    match = re.search(r"```text\n(.*?)\n```", markdown.split(marker, 1)[1], re.S)
    if not match:
        sys.exit(f"提示词文档中「{marker}」后没有 text 代码块")
    return match.group(1)


def read_prompt(path: str, marker: str = None) -> str:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return extract_block(text, marker) if marker else text.strip()


def build_config(draft: dict, args) -> dict:
    config = {key: value for key, value in draft.items() if key not in DROP_KEYS}
    if args.prompt_file:
        config["PrePrompt"] = read_prompt(args.prompt_file, args.prompt_marker)
    qa = dict(draft.get("QADatasetConfig") or {})
    if args.qa_match:
        qa["MatchType"] = args.qa_match
    if args.qa_similarity is not None:
        qa["Similarity"] = args.qa_similarity
    config["QADatasetConfig"] = qa
    model_config = dict(draft.get("ModelConfig") or {})
    if "ReasoningMode" in model_config:
        model_config["ReasoningMode"] = bool(model_config["ReasoningMode"])  # 必须是布尔值，否则发布报错
    if args.history_rounds:
        model_config["RoundsReserved"] = args.history_rounds  # 平台默认 3，上限 100，无历史压缩
    if args.max_tokens:
        model_config["MaxTokens"] = args.max_tokens
    if args.reasoning:
        model_config["ReasoningSwitchType"] = args.reasoning
        model_config["ReasoningMode"] = args.reasoning != "disabled"
    elif model_config.get("ReasoningSwitchType") not in (None, "", "disabled"):
        sys.exit(f"草稿的思考模式是 {model_config['ReasoningSwitchType']}，已拒绝发布：部分模型在 API 渠道下开思考会报"
                 "“大模型接口调用出错”。确认模型支持后用 --reasoning 明确指定，或 --reasoning disabled 关闭。")
    config["ModelConfig"] = model_config
    return config


def wait_review(session, ws, app_id, publish_id):
    deadline = time.time() + REVIEW_TIMEOUT
    while time.time() < deadline:
        items = call(session, ws, "ListPublishAppChannelHistory",
                     {"AppID": app_id, "PageNumber": 1, "PageSize": 5}).get("Items") or []
        record = next((item for item in items if item["PublishID"] == publish_id), None)
        status = record["ChannelPublishStatusList"][0] if record else {}
        if status.get("Status") not in (None, "InReview"):
            return status
        time.sleep(20)
    return {"Status": "InReview", "StatusMessage": "等待超时，请稍后用 ListPublishAppChannelHistory 复查"}


def publish(session, ws, app_id, config, description="API 渠道发布") -> tuple:
    """保存草稿、发布配置、发布 API 渠道并等待审核，返回 (PublishID, 渠道状态)。"""
    base = {"AppID": app_id}
    call(session, ws, "SaveAppConfigDraft", {**base, "AgentMode": "Single", "AppConfigDraft": config})
    publish_id = call(session, ws, "PublishAppConfig", {**base, "AgentMode": "Single", "AppConfig": config})["PublishID"]
    _publish_api_channel(session, ws, app_id, description)
    return publish_id, wait_review(session, ws, app_id, publish_id)


def publish_chatflow(session, ws, app_id, version, description) -> tuple:
    """对话流型智能体：以平台草稿的 ChatFlowConfig 发布，再发布 API 渠道并等待审核。
    对话流型不传 AgentMode；ChatFlowConfig 里必须带 Version，否则报 BadParameters。
    平台审核由模型自动完成，名称或简介写“临时测试”之类会被驳回。"""
    config = call(session, ws, "GetAppConfigDraft", {"AppID": app_id})["ChatFlowConfigDraft"]
    config = {k: v for k, v in config.items() if k != "UpdateTime"}
    config.update(Version=version, VersionDescription=description)
    publish_id = call(session, ws, "PublishAppConfig", {"AppID": app_id, "ChatFlowConfig": config})["PublishID"]
    _publish_api_channel(session, ws, app_id, description)
    return publish_id, wait_review(session, ws, app_id, publish_id)


# 渠道代码 → GetAppBuiltinChannelPublishConfig 里的状态键、PublishAppChannel 里的配置键
CHANNEL_KEYS = {"api": ("APIPublishConfigDetailAllStatus", "APIPublishConfigData"),
                "web": ("WebPublishConfigDetailAllStatus", "WebPublishConfigData"),
                "websdk": ("WebSDKPublishConfigDetailAllStatus", "WebSDKPublishConfigData"),
                "lark": ("LarkPublishConfigDetailAllStatus", "LarkPublishConfigData")}


def _publish_api_channel(session, ws, app_id, description):
    """把新发布的配置推到所有已开通的渠道。
    每个渠道都绑定发布时的 PublishID：只发 PublishAppConfig、只重发 API 渠道时，Web/飞书仍停在旧版本
    （2026-09-24 实测：API 0.8.0、飞书 0.7.0、Web 0.6.0 并存，Web 还在用已删除的旧后端密钥）。"""
    base = {"AppID": app_id}
    call(session, ws, "SaveAppBuiltinChannelPublishConfigDraft",
         {**base, "ChannelCode": "api", "BuiltinChannelConfigData": API_CHANNEL})
    brief = next((a for a in call(session, ws, "ListAppBriefs", {"PageNumber": 1, "PageSize": 100}).get("Items") or []
                  if a["ID"] == app_id), {})
    channels = [c for c in (brief.get("PublishedChannels") or []) if c in CHANNEL_KEYS] or ["api"]
    if "api" not in channels:
        channels.insert(0, "api")
    data = {"APIPublishConfigData": API_CHANNEL["APIPublishConfigData"]}
    for code in channels:
        if code == "api":
            continue
        status_key, data_key = CHANNEL_KEYS[code]
        detail = call(session, ws, "GetAppBuiltinChannelPublishConfig", {**base, "ChannelCode": code})
        cfg = (((detail.get("ConfigDetailAllStatus") or {}).get(status_key) or {}).get("DraftConfigDetail") or {}).get("ConfigData")
        if cfg:
            data[data_key] = cfg
        else:
            channels.remove(code)
    call(session, ws, "PublishAppChannel", {**base, "BuiltinChannels": channels,
                                             "BuiltinChannelPublishConfigData": data, "Description": description})


def summary(config: dict) -> str:
    mc = config["ModelConfig"]
    return (f"模型 {config.get('ModelID')}；提示词 {len(config.get('PrePrompt') or '')} 字；MaxTokens {mc.get('MaxTokens')}；"
            f"思考 {mc.get('ReasoningSwitchType')}；历史 {mc.get('RoundsReserved')} 轮；问答库召回 {config['QADatasetConfig']}；"
            f"工作流 {config.get('WorkflowIDs')}")


def parser(description=__doc__):
    p = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workspace", help="默认取 GENIOS_TEAM_WORKSPACE，传入时必须一致")
    p.add_argument("--app-id", required=True)
    p.add_argument("--prompt-file")
    p.add_argument("--prompt-marker")
    p.add_argument("--max-tokens", type=int)
    p.add_argument("--reasoning", choices=["auto", "enabled", "disabled"])
    p.add_argument("--history-rounds", type=int)
    p.add_argument("--qa-match", choices=["auto", "force"])
    p.add_argument("--qa-similarity", type=float)
    p.add_argument("--apply", action="store_true")
    return p


def run(args) -> None:
    ws = workspace()
    if args.workspace:
        require_team_workspace(args.workspace)
    session = load_session()
    draft = call(session, ws, "GetAppConfigDraft", {"AppID": args.app_id})["AppConfigDraft"]
    config = build_config(draft, args)
    print(summary(config))
    if not args.apply:
        print("未发送写请求；确认后加 --apply。")
        return
    publish_id, status = publish(session, ws, args.app_id, config)
    print(f"已发布配置 {publish_id}；API 渠道：{status.get('Status')} {(status.get('StatusMessage') or '')[:120]}")


if __name__ == "__main__":
    run(parser().parse_args())
