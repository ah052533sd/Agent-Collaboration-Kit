#!/usr/bin/env python3
"""SessionEnd hook：协作流水的**写入侧机械部分**（有 hook 的各方共用）。

只追加一条**单行**会话信封：HEAD、未提交路径、原始记录位置。它的唯一作用是让另一
Agent 能发现「这里发生过一个会话，原始记录在哪」。

**空转会话不写信封**——HEAD 未变、工作区相对会话起点无变化、且本次会话没写过语义
条目时直接退出，否则会堆出一串无内容条目，反过来挤占注入预算。

语义内容（关键判断、否决理由、未决项）由 Agent 在会话中用 `append.py` 自行追加，
hook 代劳不了：SessionEnd 触发时会话已结束，取不到模型的总结。

用法：/usr/bin/python3 journal/bin/end.py --agent claude|codex   （hook 输入走 stdin）

TRAE 不写信封：它没有 SessionEnd hook，而它的 session memory 自动落盘且带语义摘要，
「会话发生过、记录在哪」已由那个目录保证——再补一条单行信封是重复。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import _journal as J

MAX_LISTED_PATHS = 6


def marker_for(agent: str, session_id: str, transcript: str) -> str:
    key = session_id or transcript or "unknown"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    return "<!-- {}-session-end:{} -->".format(agent, digest)


def transcript_path_for(agent: str, session_id: str, provided: str) -> str:
    """路径必须校验存在性：推导值可能对不上（会话被 resume / fork 时文件名会变），
    对方按一个不存在的路径去抽取会白跑一趟，还以为是自己命令写错了。"""
    if provided:
        path = Path(provided)
    elif agent == "claude" and session_id:
        path = J.claude_transcript_dir() / "{}.jsonl".format(session_id)
    else:
        return "（未提供）"
    shown = J.display_path(str(path))
    return shown if path.exists() else "{}（推导值，当前未找到）".format(shown)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=J.AGENTS)
    args = parser.parse_args()
    agent = args.agent

    data = J.read_hook_input()
    if data and str(data.get("hook_event_name", "SessionEnd")) != "SessionEnd":
        return 0
    session_id = str(data.get("session_id", ""))
    transcript = str(data.get("transcript_path") or "")

    head = J.head_short()
    # porcelain 格式为 `XY <path>`：状态位固定 2 字符 + 1 空格。
    dirty = [
        line[3:].strip()
        for line in J.git_raw("status", "--porcelain").splitlines()
        if line.strip()
    ]
    # journal/ 的改动不算「本次会话干过活」：可能是另一个 Agent 刚追加的条目，
    # 也可能是本方的语义条目——后者已由 session marker 精确覆盖。不排除的话，
    # 对方一写 journal，本方所有空转会话都会跟着写信封。.journal-state/ 同理：
    # 它正常被 gitignore，但漏配时不该让状态文件自己触发信封。
    dirty_signal = [p for p in dirty if not p.startswith(("journal/", ".journal-state/"))]

    stamp = J.now()
    day = stamp.strftime("%Y-%m-%d")
    path = J.JOURNAL_DIR / "{}.md".format(day)
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        existing = ""

    # --- 空转判定：三个信号都没有就不写 ---
    state = J.state_file(agent, session_id)
    start_head, start_status, since = J.read_start_state(agent, session_id)
    head_moved = bool(start_head) and start_head != head
    if start_status:
        # 主判据：工作区相对会话起点**有没有变化**，不是「脏不脏」。产物长期不
        # commit 的使用模式下「脏」是常态、恒为真，空会话也会跟着写信封。
        worked = start_status != J.nonjournal_status_digest()
    else:
        # 旧格式状态文件（只有 HEAD 行）或漏跑 SessionStart：没有起点快照就无法判断
        # 工作区是否变化。产物长期不 commit 的使用模式下「脏」恒为真——2026-07-30
        # 曾因此一分钟内写出 12 条重复信封——故此时不看工作区，只认 HEAD 移动或
        # 本会话语义条目。代价是这类会话真干了活但没 commit 也没写语义条目时会漏
        # 一条信封；信封本身无语义内容，漏写比重复噪音便宜。
        worked = False
    wrote_semantics = J.wrote_semantics_this_session(agent, session_id, existing, since)

    if not (head_moved or worked or wrote_semantics):
        _cleanup(state)
        return 0

    marker = marker_for(agent, session_id, transcript)
    changed = ", ".join(dirty[:MAX_LISTED_PATHS])
    if len(dirty) > MAX_LISTED_PATHS:
        changed += " 等 {} 项".format(len(dirty))

    content = (
        "\n## [{agent}] 会话信封 {time}\n\n"
        "HEAD `{head}`｜未提交 {changed}｜记录 `{transcript}` {marker}\n"
    ).format(
        agent=agent,
        time=stamp.strftime("%H:%M %Z"),
        head=head,
        changed=changed or "无",
        transcript=transcript_path_for(agent, session_id, transcript),
        marker=marker,
    )

    try:
        J.append_locked(path, content, day, marker)
    except OSError:
        return 0
    _cleanup(state)
    return 0


def _cleanup(state) -> None:
    try:
        state.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
