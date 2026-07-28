#!/usr/bin/env python3
"""SessionStart / UserPromptSubmit hook：协作流水的**读取侧**（有 hook 的各方共用）。

SessionStart   注入「比自己上次语义条目更新」的条目，给出对方原始记录的位置，
               并记录本会话起始 HEAD（供 SessionEnd 判断是否空转）。
UserPromptSubmit 每轮注入一句极短提醒（约 300 字符），把 journal 义务留在上下文里。

用法：/usr/bin/python3 journal/bin/context.py --agent claude|codex   （hook 输入走 stdin）

TRAE 不在这里：它没有 lifecycle hook，本脚本靠 hook 的 stdin 取事件名和 session id，
直接跑会什么都不输出。它的读取路径另行解决，不要在这里加 `trae` 假装能用。
"""
from __future__ import annotations

import argparse
import sys

import _journal as J


def clipped(body: str, rel) -> str:
    """单条就超预算时才截断：保留开头，末尾补回产物行，并显式标注截断。"""
    if len(body) <= J.MAX_CHARS_PER_FILE:
        return body
    return "\n".join([
        body[:J.MAX_CHARS_PER_FILE],
        "",
        "> ⚠️ 本条共 {} 字符，已截断；需要完整内容时补读 `{}`。".format(len(body), rel),
        "",
    ] + J.artifact_lines(body))


def render_file_block(path, bodies: list) -> list:
    """单个日文件：预算内的条目给全文，超预算的**整条丢掉**并留下标题与产物。

    不按字符拦腰截断——那会把一条判断从句子中间切开，读的人分不清是没写完还是被切了；
    且产物路径写在正文里，一截就没了，接手方只能按标题猜是哪个文件，猜错还不报错。
    保留最新的若干条：接力方需要的是最近状态，不是当天最早那几条。
    """
    rel = path.relative_to(J.REPO_ROOT)
    kept, budget = [], J.MAX_CHARS_PER_FILE
    for body in reversed(bodies):
        if kept and len(body) > budget:
            break
        budget -= len(body)
        kept.append(body)
    kept.reverse()
    dropped = bodies[:len(bodies) - len(kept)]

    lines = ["### {}".format(rel), ""]
    if dropped:
        lines += [
            "> ⚠️ 该文件另有 {} 条较早未读条目未注入（共 {} 字符，超出单文件 {} 字符预算）。"
            "标题与产物如下，需要正文时补读 `{}`：".format(
                len(dropped), sum(len(b) for b in dropped), J.MAX_CHARS_PER_FILE, rel
            ),
            "",
        ] + [J.entry_digest(b) for b in dropped] + [""]
    return lines + ["\n\n".join(clipped(b, rel) for b in kept), ""]


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
        lines += render_file_block(path, grouped[path])
    return lines


def render_fallback(agent: str) -> list:
    """兜底通道：只给路径，不给内容；读取必须走抽取脚本。

    **其余每一方都要渲染**：漏掉一方，它的会话记录对本次会话就等于不存在，而且不报错。
    """
    lines = []
    for peer in J.other_agents(agent):
        records = J.records_for(peer)
        if not records:
            continue
        lines += [
            "## {} 近 24h 会话记录（兜底通道，本项目）".format(peer.capitalize()),
            "",
            "仅在 journal 缺失或需复核对方判断的原始上下文时读取。**禁止对 jsonl 用 "
            "Read / cat**（单个可达百 MB），一律用：`{}`。".format(J.peek_command(peer)),
            "",
        ] + [str(J.display_path(str(p))) for p in records] + [""]
    return lines


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
        digests = "\n".join(J.entry_digest(b) for b in bodies)
        content = "{}\n\n> 共 {} 字符，超出本轮注入预算，上面只给了标题与产物；需要正文时主动 Read `{}`。".format(
            digests, total, "、".join(files)
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
