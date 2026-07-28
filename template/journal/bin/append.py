#!/usr/bin/env python3
"""向协作流水追加一条**语义条目**（Claude 与 Codex 共用）。

这是两侧写 journal 的唯一入口：flock 加锁、自动建当日文件、格式统一，
两个 Agent 同时写也不会互相截断。

用法（`--session-id` 请尽量带上：`end.py` 靠它精确判断本次会话是否空转）：
  /usr/bin/python3 journal/bin/append.py --agent claude \\
      --session-id "<本次会话 id>" \\
      --title "<一句话标题>" \\
      --doing "<本次会话的单一主目标>" \\
      --judgment "<关键判断及依据，包括还不确定的>" \\
      --rejected "<试过或考虑过但放弃的路径，以及理由>" \\
      --finding "<过程中查证到的事实>" \\
      --open "<留给下一个会话或另一方的问题>" \\
      --next "<接手的人该从哪一步动手>" \\
      --artifact "<本次产出或改写的文件路径>"

字段可重复传入；没有的字段直接省略，不要写「无」凑格式。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _journal as J

FIELDS = (
    ("在做什么", "doing"),
    ("过程判断", "judgment"),
    ("否决了什么", "rejected"),
    ("发现", "finding"),
    ("未决项", "open_item"),
    # 接力场景专用：未决项是「还没解决的问题」，下一步是「接手的人该从哪动手」，两者不同。
    ("下一步", "next_step"),
)


def indented(value: str) -> str:
    return value.strip().replace("\n", "\n  ")


def build_entry(args, stamp) -> str:
    title = " ".join(args.title.splitlines()).strip()
    lines = ["\n## [{}] {} — {}\n".format(args.agent, stamp.strftime("%H:%M %Z"), title)]
    for label, attr in FIELDS:
        for value in getattr(args, attr):
            if value.strip():
                lines.append("- **{}：** {}".format(label, indented(value)))
    # 产物单独成行、路径加反引号：注入预算不够时 context.py 只保留标题和这几行。
    for value in args.artifact:
        if value.strip():
            lines.append("- **{}：** `{}`".format(J.ARTIFACT_LABEL, value.strip()))
    if args.session_id:
        lines.append("<!-- {}-session:{} -->".format(args.agent, args.session_id))
    return "\n".join(lines) + "\n"


def warn_unknown_artifacts(values: list) -> None:
    """路径不存在只警告不阻断：可能还没落盘，也可能名字写错了——后者正是要抓的。"""
    for value in values:
        rel = value.strip()
        if rel and not (J.REPO_ROOT / rel).exists() and not Path(rel).exists():
            print("⚠️ --artifact 路径当前不存在：{}".format(rel), file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=J.AGENTS)
    parser.add_argument("--title", required=True)
    parser.add_argument("--doing", action="append", default=[])
    parser.add_argument("--judgment", action="append", default=[])
    parser.add_argument("--rejected", action="append", default=[])
    parser.add_argument("--finding", action="append", default=[])
    parser.add_argument("--open", dest="open_item", action="append", default=[])
    parser.add_argument("--next", dest="next_step", action="append", default=[],
                        help="接力方从哪一步继续；token 快耗尽或即将换手时必写")
    parser.add_argument("--artifact", action="append", default=[],
                        help="本次产出或改写的文件路径；产出了文件必写，否则接手方只能按标题猜")
    parser.add_argument("--session-id", default="")
    args = parser.parse_args()

    warn_unknown_artifacts(args.artifact)
    stamp = J.now()
    day = stamp.strftime("%Y-%m-%d")
    path = J.JOURNAL_DIR / "{}.md".format(day)
    J.append_locked(path, build_entry(args, stamp), day)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
