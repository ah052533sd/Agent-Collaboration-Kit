#!/usr/bin/env python3
"""SessionStart / UserPromptSubmit hook：协作流水的**读取侧**（Claude 与 Codex 共用）。

SessionStart   注入「比自己上次语义条目更新」的条目，给出对方原始记录的位置，
               并记录本会话起始 HEAD（供 SessionEnd 判断是否空转）。
UserPromptSubmit 每轮注入一句极短提醒（约 300 字符），把 journal 义务留在上下文里。

用法：/usr/bin/python3 journal/bin/context.py --agent claude|codex   （hook 输入走 stdin）
"""
from __future__ import annotations

import argparse
import sys

import _journal as J


def render_unread(agent: str) -> list:
    lines = ["## 协作流水（过程记录，不具备规范效力）", ""]
    unread = J.unread_sections(agent)
    if not unread:
        return lines + ["没有比自己上次记录更新的条目。", ""]

    grouped = {}
    for path, body in unread:
        grouped.setdefault(path, []).append(body)
    paths = list(grouped)
    omitted, selected = paths[:-J.MAX_FILES], paths[-J.MAX_FILES:]

    if omitted:
        names = "、".join(str(p.relative_to(J.REPO_ROOT)) for p in omitted)
        lines += [
            "> ⚠️ 另有较早未读日文件未注入：{}。开始实质工作前按需主动读取。".format(names),
            "",
        ]

    for path in selected:
        body = "\n\n".join(grouped[path])
        rel = path.relative_to(J.REPO_ROOT)
        if len(body) > J.MAX_CHARS_PER_FILE:
            half = J.MAX_CHARS_PER_FILE // 2
            body = "\n".join([
                body[:half],
                "",
                "> ⚠️ 此文件未读内容共 {} 字符，中间已截断；需要完整内容时补读 `{}`。".format(len(body), rel),
                "",
                body[-half:],
            ])
        lines += ["### {}".format(rel), "", body, ""]
    return lines


def render_fallback(agent: str) -> list:
    """兜底通道：只给路径，不给内容；读取必须走抽取脚本。"""
    peer = J.other_agent(agent)
    records = J.codex_rollouts() if peer == "codex" else J.claude_transcripts()
    if not records:
        return []
    return [
        "## {} 近 24h 原始会话记录（兜底通道，本项目）".format(peer.capitalize()),
        "",
        "仅在 journal 缺失或需复核对方判断的原始上下文时读取。**禁止对 jsonl 用 Read / cat**"
        "（单个常 0.5–1MB），一律用：`{}`。".format(J.peek_command(peer)),
        "",
    ] + [str(J.display_path(str(p))) for p in records] + [""]


def render_obligation(agent: str, session_id: str) -> list:
    return [
        "## 本会话 journal 义务",
        "",
        "出现可供另一 Agent 复核的关键判断、否决路径或未决项时**立即追加**，不要等会话结束：",
        "",
        "`{}`".format(J.append_command(agent, session_id)),
        "",
        "半成品、未验证判断进 journal，不进 `knowledge/`；写 `knowledge/` 仍需用户明确确认。"
        "SessionEnd 只自动写 HEAD / 未提交改动 / 记录路径，不会替你生成语义摘要。",
    ]


MAX_MIDSESSION_CHARS = 2000


def render_reminder(agent: str, session_id: str) -> str:
    return (
        "若本轮形成了可供另一 Agent 复核的关键判断、否决路径或未决项，立即追加 journal 条目："
        "`{}`。半成品进 journal，不进 knowledge/；写 knowledge/ 需用户明确确认。"
    ).format(J.append_command(agent, session_id))


def render_midsession(agent: str, session_id: str, fresh: list) -> str:
    """会话进行中对方写了新条目——借每轮提醒这趟车带进来，不额外轮询。

    水位随注入前移，同一条不会重复注入；超出预算时只给标题和补读指引。
    """
    bodies = [body for _, body in fresh]
    total = sum(len(b) for b in bodies)
    header = "## 协作流水：对方在你本次会话期间新增了 {} 条（过程记录，不具备规范效力）".format(len(fresh))

    if total <= MAX_MIDSESSION_CHARS:
        content = "\n\n".join(bodies)
    else:
        files = sorted({str(p.relative_to(J.REPO_ROOT)) for p, _ in fresh})
        titles = "\n".join(
            "- {}".format(b.splitlines()[0].lstrip("# ").strip()) for b in bodies
        )
        content = "{}\n\n> 共 {} 字符，超出本轮注入预算；需要内容时主动 Read `{}`。".format(
            titles, total, "、".join(files)
        )

    return "{}\n\n{}\n\n{}".format(header, content, render_reminder(agent, session_id))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=J.AGENTS)
    args = parser.parse_args()

    data = J.read_hook_input()
    event = str(data.get("hook_event_name", ""))
    session_id = str(data.get("session_id", ""))

    if event == "SessionStart":
        J.record_start_head(args.agent, session_id)
        blocks = render_unread(args.agent) + render_fallback(args.agent) + render_obligation(args.agent, session_id)
        context = "\n".join(blocks)
        J.record_watermark(args.agent, session_id)
    elif event == "UserPromptSubmit":
        fresh = J.unread_since_watermark(args.agent, session_id)
        if fresh:
            context = render_midsession(args.agent, session_id, fresh)
            J.record_watermark(args.agent, session_id)
        else:
            context = render_reminder(args.agent, session_id)
    else:
        return 0

    J.emit(event, context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
