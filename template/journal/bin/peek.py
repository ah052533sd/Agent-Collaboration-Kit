#!/usr/bin/env python3
"""兜底通道的**便宜读法**：只抽原始会话记录里的 user / assistant 消息。

丢掉 tool call、tool output 和 reasoning（这三类占绝大部分体积）。单个 jsonl 常在
0.5–1MB，直接 Read / cat 一次就吃掉十几万 token；抽取后通常只剩 1%–5%。

用法：
  /usr/bin/python3 journal/bin/peek.py --agent codex           # 对方近 24h 记录（限本项目）
  /usr/bin/python3 journal/bin/peek.py --agent claude
  /usr/bin/python3 journal/bin/peek.py --agent codex <jsonl 路径> ...
  /usr/bin/python3 journal/bin/peek.py --agent codex --full    # 不截断单条消息
  /usr/bin/python3 journal/bin/peek.py --agent codex --days 3 --all-projects

**禁止对 jsonl 直接用 Read / cat。**
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import _journal as J

DEFAULT_CAP = 600
SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
# 每次会话开头的环境注入，体积大且无判断价值。
NOISE_PREFIXES = (
    "<environment_context",
    "<user_instructions",
    "<system-reminder",
    "<recommended_plugins",
)


def clean(text: str) -> str:
    text = SYSTEM_REMINDER.sub("", text).strip()
    return "" if text.startswith(NOISE_PREFIXES) else text


def blocks_text(content) -> str:
    """content 可能是纯字符串，也可能是块数组；只取文本块。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") in (None, "text", "input_text", "output_text"):
            parts.append(str(block.get("text") or ""))
    return " ".join(p for p in parts if p)


def extract_line(line: str, include_sidechain: bool):
    """两种格式共用一个解析器：Codex rollout 与 Claude transcript。"""
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    kind = data.get("type")

    # Codex：{"type":"response_item","payload":{"type":"message","role":...}}
    if kind == "response_item":
        payload = data.get("payload") or {}
        if payload.get("type") != "message" or payload.get("role") not in ("user", "assistant"):
            return None
        return payload["role"], blocks_text(payload.get("content"))

    # Claude：{"type":"user"|"assistant","message":{"role":...,"content":...}}
    if kind in ("user", "assistant"):
        if data.get("isSidechain") and not include_sidechain:
            return None
        message = data.get("message") or {}
        return kind, blocks_text(message.get("content"))

    return None


def dump(path: Path, cap: int, include_sidechain: bool) -> None:
    print("\n===== {} =====".format(path.name))
    try:
        handle = path.open(encoding="utf-8")
    except OSError as error:
        print("（无法读取：{}）".format(error))
        return
    with handle:
        for line in handle:
            parsed = extract_line(line, include_sidechain)
            if not parsed:
                continue
            role, text = parsed
            text = clean(text)
            if not text:
                continue
            text = " ".join(text.split())
            if len(text) > cap:
                text = text[:cap] + " …[截断]"
            print("[{}] {}".format(role, text))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=J.AGENTS, help="读谁的记录")
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--full", action="store_true", help="单条消息上限放宽到 100000 字符")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--all-projects", action="store_true", help="Codex：不按本项目过滤")
    parser.add_argument("--sidechain", action="store_true", help="Claude：包含子 Agent 分支")
    args = parser.parse_args()

    if args.paths:
        targets = [p for p in args.paths if p.is_file()]
        missing = [str(p) for p in args.paths if not p.is_file()]
        for path in missing:
            print("（跳过不存在的路径：{}）".format(path), file=sys.stderr)
    elif args.agent == "codex":
        targets = J.codex_rollouts(args.days, args.limit, not args.all_projects)
    else:
        targets = J.claude_transcripts(args.days, args.limit)

    if not targets:
        print("近 {} 天没有本项目的 {} 会话记录。".format(args.days, args.agent))
        return 0

    cap = 100000 if args.full else DEFAULT_CAP
    for path in targets:
        dump(path, cap, args.sidechain)
    return 0


if __name__ == "__main__":
    sys.exit(main())
