#!/usr/bin/env python3
"""协作机制的漂移检查：把能机械判定的部分从人的眼睛里拿走。

检查四件事：
1. **实现漂移**——各仓库的 `journal/bin/*.py` 与工具包模板是否逐字节一致。
   两侧共用一份实现是硬要求；曾经各写一份，半天内漂移出四个 bug。
2. **协议漂移**——各仓库 `AGENTS.md` 里的硬约束是否还在。只查「不得 / 禁止 / 必须」
   这类有约束力的句子，不比对措辞：项目特化的表述本来就该不同。
3. **协议逐行差异**——模板与各项目的协议节差异清单，交人判断是项目特化还是漏同步。
4. **机制健康度**——近 7 天 journal 的信封 / 语义条目比例、每条平均长度。
   信封远多于语义条目说明有会话在空转却写了信封，或有人忘了写语义条目。

只读、只报告，不改任何文件。

用法：/usr/bin/python3 check-drift.py [仓库路径 ...]
      不传路径时读 repos.local.txt（本机配置，不进版本控制）。
"""
from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

KIT = Path(__file__).resolve().parent
TEMPLATE = KIT / "template"

# 要检查哪些仓库：命令行参数优先，其次读 repos.local.txt（一行一个路径，`#` 开头为注释）。
# 该文件不进版本控制——仓库路径是本机信息，不该跟着工具包分发出去。
REPOS_FILE = KIT / "repos.local.txt"


def configured_repos() -> list:
    if not REPOS_FILE.exists():
        return []
    lines = REPOS_FILE.read_text(encoding="utf-8").splitlines()
    return [Path(l.strip()).expanduser() for l in lines if l.strip() and not l.startswith("#")]

# 有约束力的句子；措辞可以不同，约束不能丢。
HARD_CONSTRAINTS = [
    "不得为满足本协议而越权",
    "不得按 Agent 分区",
    "无复核的转述写入",
    "不引入写入锁",
    "工作区干净不代表没有并发",
    "来源未知",
    "不得自行裁决",
    "禁止 `git add -A`",
    "不得做 hunk 级裁决",
    "push 必须由用户明确要求",
    "禁止对 jsonl",
    "不得仅凭 manifest",
    "静默改写永远禁止",
    "不得给另一 Agent 派活",
    "全量注入是有意保留的",
    "先形成自己的判断再对照",
    "接手前先确认换手原因",
    "只往下做",
    "第三份",
]

SCRIPTS = ["_journal.py", "append.py", "context.py", "end.py", "peek.py"]
HEADING = re.compile(r"(?m)^## \[(?P<agent>[^\]]+)\]\s*(?P<rest>.*)$")


def digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return "缺失"


def protocol_section(agents_md: Path) -> str:
    try:
        text = agents_md.read_text(encoding="utf-8")
    except OSError:
        return ""
    start = text.find("## 多 Agent 协作协议")
    if start < 0:
        return ""
    end = text.find("\n## ", start + 10)
    return text[start:end if end > 0 else len(text)]


def check_implementation(repos: list) -> list:
    lines = ["## 1. 实现漂移（journal/bin/*.py 是否与模板一致）", ""]
    ok = True
    for name in SCRIPTS:
        ref = digest(TEMPLATE / "journal" / "bin" / name)
        row = [f"- `{name}` 模板 `{ref}`"]
        for repo in repos:
            got = digest(repo / "journal" / "bin" / name)
            mark = "✓" if got == ref else f"✗ {got}"
            row.append(f"{repo.name} {mark}")
            ok = ok and got == ref
        lines.append("｜".join(row))
    lines += ["", "**结论：** " + ("三处一致。" if ok else "**存在漂移，必须修**——两侧共用一份实现是硬要求。"), ""]
    return lines


def check_protocol(repos: list) -> list:
    lines = ["## 2. 协议漂移（硬约束是否还在）", ""]
    targets = [("模板", TEMPLATE / "AGENTS.md")] + [(r.name, r / "AGENTS.md") for r in repos]
    for label, path in targets:
        section = protocol_section(path)
        if not section:
            lines.append(f"- **{label}**：⚠️ 找不到「多 Agent 协作协议」小节")
            continue
        missing = [c for c in HARD_CONSTRAINTS if c not in section]
        rules = len(re.findall(r"(?m)^### \d+\.", section))
        size = len(section)
        status = "✓ 全在" if not missing else "✗ 缺 " + "、".join(f"`{m}`" for m in missing)
        lines.append(f"- **{label}**：{rules} 条 / {size} 字符 / {status}")
    lines += [
        "",
        "> 缺失项要分辨是**被有意删掉**（需在 journal 或 decisions 里找到理由）还是**改写时漏了**。",
        "> 前者补记录，后者补回原文。项目特化的措辞差异不算漂移。",
        "",
    ]
    return lines


def check_diff(repos: list, max_lines: int = 24) -> list:
    """协议节的逐行差异。项目特化本来就该有差异，所以这里只列出来交人判断。"""
    import difflib

    lines = ["## 3. 协议逐行差异（模板 vs 各项目）", ""]
    base = protocol_section(TEMPLATE / "AGENTS.md").splitlines()
    for repo in repos:
        got = protocol_section(repo / "AGENTS.md").splitlines()
        delta = [
            l for l in difflib.unified_diff(base, got, lineterm="", n=0)
            if l[:1] in "+-" and not l.startswith(("---", "+++"))
        ]
        lines.append(f"### {repo.name}（{len(delta)} 行差异）")
        lines.append("")
        if not delta:
            lines += ["与模板逐行一致。", ""]
            continue
        shown = [f"`{l[:1]}` {l[1:].strip()[:110]}" for l in delta[:max_lines]]
        lines += shown
        if len(delta) > max_lines:
            lines.append(f"…还有 {len(delta) - max_lines} 行，自行读取两份文件比对。")
        lines.append("")
    lines += [
        "> `-` 只在模板里，`+` 只在项目里。**差异不等于漂移**：任务目录名、写入门槛档位、项目特有条款",
        "> 本来就该不同。要判断的是——**这处差异是有意的项目特化，还是有人只改了一边**。",
        "> 后者的处理方式是先改模板，再同步到各项目，不要就地改完了事。",
        "",
    ]
    return lines


def check_health(repos: list, days: int = 7) -> list:
    lines = [f"## 4. 机制健康度（近 {days} 天 journal）", ""]
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    for repo in repos:
        files = sorted(p for p in (repo / "journal").glob("20??-??-??.md") if p.name[:10] >= cutoff)
        env = sem = 0
        lengths = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            matches = list(HEADING.finditer(text))
            for i, m in enumerate(matches):
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                if "会话信封" in m.group("rest"):
                    env += 1
                else:
                    sem += 1
                    lengths.append(end - m.start())
        avg = round(sum(lengths) / len(lengths)) if lengths else 0
        flag = ""
        if sem and env > sem * 2:
            flag = "  ⚠️ 信封远多于语义条目：查空转判定，或有人只写信封不写判断"
        if avg > 4000:
            flag += "  ⚠️ 条目偏长：细节应进任务目录，此处只留判断和理由"
        lines.append(f"- **{repo.name}**：{len(files)} 天 / 语义 {sem} 条 / 信封 {env} 条 / 语义条目均长 {avg} 字符{flag}")
    lines.append("")
    return lines


def main() -> int:
    repos = [Path(a).expanduser() for a in sys.argv[1:]] or configured_repos()
    if not repos:
        print("没有要检查的仓库。用法：check-drift.py <仓库路径 ...>，")
        print(f"或在 {REPOS_FILE.name} 里一行一个写好本机的仓库路径（该文件不进版本控制）。")
        return 1
    missing = [r for r in repos if not (r / "AGENTS.md").exists()]
    for r in missing:
        print(f"⚠️ 跳过 {r}：没有 AGENTS.md", file=sys.stderr)
    repos = [r for r in repos if r not in missing]
    out = [f"# 协作机制漂移检查 — {datetime.now().astimezone():%Y-%m-%d %H:%M %Z}", ""]
    out += check_implementation(repos)
    out += check_protocol(repos)
    out += check_diff(repos)
    out += check_health(repos)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
