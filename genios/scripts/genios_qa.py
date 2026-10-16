#!/usr/bin/env python3
"""把问答条目（JSON 文件：{"entries": [{document_id, main_question, similar_questions, answer}]}）追加写入问答库。

按 document_id 去重：问答库中描述以该编号开头的条目视为已存在，跳过不写，可重复执行。
默认只打印计划，加 --apply 才写入。
    export GENIOS_SESSION_FILE=<scratchpad>/session.env
    export GENIOS_TEAM_WORKSPACE=<团队空间ID>
    python3 genios_qa.py --dataset-id <问答库ID> --kb-file <条目.json> [--apply]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from genios_api import call, load_session, require_team_workspace, workspace  # noqa: E402

PAGE_SIZE = 50


def existing_ids(session, workspace: str, dataset_id: str) -> set:
    ids, page = set(), 1
    while True:
        result = call(session, workspace, "ListQADocuments",
                      {"WorkspaceID": workspace, "DatasetID": dataset_id, "PageNumber": page, "PageSize": PAGE_SIZE})
        items = result.get("Items") or result.get("Documents") or []
        ids.update((item.get("Description") or "").split(" ", 1)[0] for item in items)
        if len(items) < PAGE_SIZE:
            return ids
        page += 1


def document_body(workspace: str, dataset_id: str, entry: dict) -> dict:
    return {"WorkspaceID": workspace, "DatasetID": dataset_id,
            "Description": f"{entry['document_id']} official",
            "Questions": {"MainQuestion": entry["main_question"], "SimilarQuestions": entry["similar_questions"]},
            "Answer": entry["answer"]}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workspace", help="默认取 GENIOS_TEAM_WORKSPACE，传入时必须一致")
    p.add_argument("--dataset-id", required=True)
    p.add_argument("--kb-file", required=True)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    ws = workspace()
    if args.workspace:
        require_team_workspace(args.workspace)
    args.workspace = ws
    with open(args.kb_file, encoding="utf-8") as f:
        entries = json.load(f)["entries"]
    if not args.apply:
        for entry in entries:
            print(f"[dry-run] CreateQADocument {entry['document_id']} {entry['main_question']}")
        print(f"共 {len(entries)} 条，未发送请求；确认后加 --apply。")
        return
    session = load_session()
    present = existing_ids(session, args.workspace, args.dataset_id)
    created = 0
    for entry in entries:
        if entry["document_id"] in present:
            print(f"跳过（已存在）{entry['document_id']}")
            continue
        call(session, args.workspace, "CreateQADocument", document_body(args.workspace, args.dataset_id, entry))
        created += 1
        print(f"已写入 {entry['document_id']} {entry['main_question']}")
    print(f"新增 {created} 条，跳过 {len(entries) - created} 条。")


if __name__ == "__main__":
    main()
