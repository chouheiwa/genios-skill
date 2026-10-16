#!/usr/bin/env python3
"""NK-GeniOS 工作流节点级搭建库：不经过画布，用管理 API 建节点、写配置、连线、校验、试跑。

    import genios_api, genios_flow as gf
    session = genios_api.load_session(); ws = genios_api.workspace()
    flow = gf.Flow(session, ws, workflow_id)
    start, end = flow.reset()                       # 清掉 Start/End 以外的节点（重建是幂等的）
    llm = flow.add("LLM", "判断", 400, 200)
    flow.set(start, "Start", "Start", gf.start_inputs([("text", True, "用户原话")]))
    flow.set(llm, "判断", "LLM", gf.llm(model_id, [gf.ref(start, "text")], "系统提示", "用户：{{text}}"))
    flow.set(end, "End", "End", gf.end([("answer", llm, "raw_output")]))
    flow.link([(start, llm), (llm, end)])
    print(flow.check()); print(flow.run({"text": "..."}))

对话流型智能体的画布也用这套接口：Flow(session, ws, workflow_id, app_id=智能体ID)，check() 自动改用 CheckChatflow。

各节点配置格式与坑见 ../references/workflow-node-api.md、../references/chatflow.md。
"""
import json
import os
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from genios_api import call  # noqa: E402

STRING, INTEGER, BOOLEAN, NUMBER, OBJECT, ARRAY_STRING, ARRAY_OBJECT = 0, 1, 2, 3, 4, 5, 9


class Flow:
    """对单个工作流的节点级 API 封装。"""

    def __init__(self, session, workspace, flow_id, app_id=None):
        """app_id 不为空时表示这是对话流型智能体的画布（ChatFlowConfig.WorkflowID）。"""
        self.session, self.workspace, self.id, self.app_id = session, workspace, flow_id, app_id

    def api(self, action, body, attempts=3):
        """网络超时和 5xx 偶发失败时重试；业务错误（4xx、登录失效）直接退出。"""
        for attempt in range(1, attempts + 1):
            try:
                return call(self.session, self.workspace, action, {"WorkspaceID": self.workspace, **body})
            except (urllib.error.URLError, TimeoutError) as err:
                failure = str(err)
            except SystemExit as err:
                if "HTTP 5" not in str(err):
                    raise
                failure = str(err)
            print(f"{action} 第 {attempt} 次失败，重试：{failure[:120]}", file=sys.stderr)
            time.sleep(2 * attempt)
        sys.exit(f"{action}: 重试 {attempts} 次仍失败")

    def nodes(self):
        return self.api("GetWorkflow", {"ID": self.id})["Nodes"]

    def reset(self):
        """删除 Start/End 以外的节点，返回 (start_code, end_code)。"""
        codes = {}
        for node in self.nodes():
            if node["Type"] in ("Start", "End"):
                codes[node["Type"]] = node["Code"]
            else:
                self.api("DeleteFlowNode", {"FlowID": self.id, "ID": node["ID"]})
        return codes["Start"], codes["End"]

    def add(self, node_type, name, x, y):
        return self.api("CreateFlowNode", {"FlowID": self.id, "Type": node_type,
                                           "Layout": {"X": x, "Y": y}, "Name": name})["Node"]["Code"]

    def set(self, code, name, node_type, config, error_config=None):
        body = {"ID": code, "FlowID": self.id, "Name": name, "NodeConfig": {node_type + "Node": config}}
        if error_config:
            body["ErrorConfig"] = error_config
        self.api("UpdateFlowNode", body)

    def link(self, pairs):
        links = [{"From": {"NodeCode": p[0], **({"PortID": p[2]} if len(p) > 2 else {})},
                  "To": {"NodeCode": p[1]}} for p in pairs]
        self.api("UpdateFlowNodeLinks", {"FlowID": self.id, "Links": links})

    def check(self):
        # 对话流画布用 CheckWorkflow 会报 “not support ... user_variable when agentID is null”
        if self.app_id:
            return self.api("CheckChatflow", {"ID": self.id, "AppID": self.app_id})
        return self.api("CheckWorkflow", {"ID": self.id})

    def run(self, inputs, timeout=120):
        run_id = self.api("SubmitWorkflowDebug", {"ID": self.id, "InputData": json.dumps(inputs, ensure_ascii=False)})["runId"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(2)
            result = self.api("QueryDebugProcess", {"WorkflowId": self.id, "RunId": run_id})
            if result.get("status") not in ("processing", "running", None, ""):
                return result
        return {"status": "timeout", "runId": run_id}


def ref(code, path, name=None):
    return {"Name": name or path, "RefType": "node_field", "NodeCode": code, "Path": path}


def literal(value):
    return {"Name": "Right", "RefType": "value", "JsonValue": json.dumps(value, ensure_ascii=False)}


def start_inputs(params):
    """params: [(名称, 是否必填, 描述), ...]，类型均为 String。"""
    return {"InputSchema": [{"Name": n, "Type": STRING, "Required": r, "Desc": d} for n, r, d in params]}


def llm(model, inputs, system, user, max_tokens=512, temperature=0.2, vision=None):
    """LLM 节点。vision 为视觉理解输入（VisionInputs）的引用列表，每项带 Name，引用文件或文件数组变量
    （如对话流开始节点的 files）；模型须支持看图（ListModelByWorkspaceGrant 的 FeaturesConfig 含 vision），
    图片会作为图片输入交给模型。"""
    config = {"ModelID": model, "Temperature": temperature, "TopP": 0.5, "MaxTokens": max_tokens,
              "Input": inputs, "SystemPrompt": system, "Prompt": user, "OutputFormat": "text",
              "OutputSchema": [{"Name": "raw_output", "Type": STRING}],
              "TimeoutSeconds": 120, "Retries": 1, "ModelInteractiveMode": "direct"}
    if vision:
        config["VisionInputs"] = vision
    return config


def code(source, inputs, outputs):
    """Python Code 节点：source 是含 `def handler(params): return {...}` 的源码字符串。"""
    return {"Input": inputs, "Language": 1, "Code": source, "TimeoutSeconds": 30, "Retries": 0,
            "OutputSchema": [{"Name": n, "Type": STRING} for n in outputs]}


def condition(*branches):
    """branches: (port_name, logic, [(left_ref, value), ...])；logic 0=AND 1=OR，运算符 0=等于。"""
    return {"Conditions": [{"Name": port, "ConditionLogic": logic,
                            "SubConditions": [{"Left": left, "Operator": 0, "Right": literal(v)} for left, v in subs]}
                           for port, logic, subs in branches]}


def merge(groups):
    return {"Groups": [{"name": "Group%d" % i, "Type": STRING, "Variables": refs} for i, refs in enumerate(groups, 1)],
            "OutputSchema": [{"Name": "Group%d" % i, "Type": STRING} for i in range(1, len(groups) + 1)]}


def end(pairs):
    return {"OutputType": "Variable", "Input": [ref(c, p, n) for n, c, p in pairs]}


# ---- 对话流型智能体专用 ----

def user_var(name, alias=None):
    """引用对话流的用户变量（SaveChatFlowConfigDraft 的 UserVariableConfigs 里定义）。"""
    return {"Name": alias or name, "RefType": "user_variable", "Path": name}


def sys_var(name, alias=None):
    """引用对话流系统变量，如 SYS_USERID、SYS_USERNAME、SYS_USER_CHANNEL、SYS_CONVERSATION_ID。
    Web 服务（平台认证用户）下 SYS_USERNAME 是统一身份认证账号（学工号）、渠道为 IAM；
    API 渠道下 SYS_USERID 就是调用方传的 UserID，不可作为身份凭据。"""
    return {"Name": alias or name.lower(), "RefType": "conversation_variable", "Path": name}


def options_question(model, question, options, template_vars=None, branch=True):
    """信息收集节点（选项回答）：向用户提问并给出固定选项；branch=True 时每个选项一个出口端口
    （class01、class02…，按选项顺序；另有隐藏的 class_other 接“答非所问”），输出 optionId / optionContent。
    字段由平台前端与回读实测得出：问题文本是 QuestionTemplate（可用 {{变量}} 引用 TemplateVars），选项文本是 OptionContent。"""
    opts = [{"CondID": "class%02d" % (i + 1), "OptionID": chr(ord("A") + i), "OptionContent": text}
            for i, text in enumerate(options)]
    # 平台约定选项表末尾带一条隐藏的“其他”（class_other）；缺了它，展示给用户时会把最后一个真实选项当成“其他”吞掉
    opts.append({"CondID": "class_other", "OptionID": chr(ord("A") + len(options)), "OptionContent": "其他"})
    return {
        "ModelConfig": {"ModelID": model, "Temperature": 0.2, "TopP": 0.5, "MaxTokens": 256},
        "TemplateVars": template_vars or [], "QuestionTemplate": question,
        "AnswerType": "option", "ExtractParameters": False, "ModelInteractiveMode": "direct",
        "OptionConfig": {"BranchMode": branch, "OptionType": "solid", "Options": opts},
        "OutputSchema": {"Name": "root", "Type": 4, "SubParameters": [
            {"Name": "optionId", "Type": STRING}, {"Name": "optionContent", "Type": STRING}]}}


def assign(pairs):
    """变量赋值节点：pairs 为 [(用户变量名, 值的引用), ...]。"""
    return {"Variables": [dict(value, Name=name) for name, value in pairs],
            "OutputSchemas": [{"Name": "is_successful", "Type": BOOLEAN}]}


def agent(app_id, query_ref, history=True, files=None):
    """智能体节点：调用一个已发布的对话型智能体，输出字段为 output。
    history=True 时把对话流的对话历史带给它；关掉则被调用的智能体每轮都从头开始。
    files 是附件条目 [(文件名引用, 链接引用), ...]，两个引用都指向字符串变量。平台前端把第 i 条存成两条输入
    sys_user_file_list[i].name / sys_user_file_list[i].url；直接引用开始节点的 files 列表会被 CheckChatflow 判
    “invalid file list variable format”。
    注意（2026-09-28 实测）：当前这一轮的附件只会以“文件列表: 文件名…, 文件链接…”的文字交给模型，模型看不到图片内容，
    会凭空编造；附件条目为空时每轮还会多一行空的“文件列表”。要让模型看图，用 LLM 节点的 vision（VisionInputs）。"""
    inputs = [dict(query_ref, Name="sys_user_query")]
    for i, (name_ref, url_ref) in enumerate(files or []):
        inputs += [dict(name_ref, Name="sys_user_file_list[%d].name" % i), dict(url_ref, Name="sys_user_file_list[%d].url" % i)]
    return {"AppID": app_id, "Input": inputs, "EnableChatHistories": history}


def end_content(pairs, template):
    """对话流结束节点直接输出文本。默认的 Variable 模式会把回复包成 JSON，并且这段 JSON 会进入对话历史。"""
    return {"OutputType": "Content", "Template": template, "StreamOutput": True,
            "Input": [ref(c, p, n) for n, c, p in pairs]}


def chatflow_config(workflow_id, user_vars, rounds=20):
    """SaveChatFlowConfigDraft / PublishAppConfig 用的 ChatFlowConfig。
    user_vars: [(名称, 描述, 作用域)]，作用域 Conversation=单会话、Agent=该用户所有会话。"""
    return {"WorkflowID": workflow_id, "RoundsReserved": rounds, "VariableConfigs": [],
            "UserVariableConfigs": [{"Name": n, "Description": d, "Scope": scope} for n, d, scope in user_vars]}
