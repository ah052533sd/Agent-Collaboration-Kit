#!/usr/bin/env python3
"""协作机制的漂移检查：把能机械判定的部分从人的眼睛里拿走。

检查四件事：
1. **实现漂移**——各仓库的 `journal/bin/*.py` 与工具包模板是否逐字节一致。
   两侧共用一份实现是硬要求；曾经各写一份，半天内漂移出四个 bug。
2. **协议漂移**——各仓库 `AGENTS.md` 里的硬约束是否还在。只查「不得 / 禁止 / 必须」
   这类有约束力的句子，不比对措辞：项目特化的表述本来就该不同。
3. **协议逐行差异**——模板与各项目的协议节差异清单，交人判断是项目特化还是漏同步。
4. **机制健康度**——近 7 天 journal **按天**的信封 / 语义条目比例、每条平均长度。
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
    "不得依赖私有记忆",
    "不得就地改本仓库的协议",
    "--artifact",
]

# 必须与模板逐字节一致的文件。标 optional 的只在装了那一方的项目里存在，缺失不算漂移。
SYNCED_FILES = [
    ("journal/bin/_journal.py", False),
    ("journal/bin/append.py", False),
    ("journal/bin/context.py", False),
    ("journal/bin/end.py", False),
    ("journal/bin/peek.py", False),
    # TRAE 没有 hook，这份规则文件是它**唯一**的常驻上下文。漂移了它会照旧规矩干活，
    # 而且不像 hook 那样会因为报错暴露——所以更需要机械比对。
    (".trae/rules/project_rules.md", True),
]
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
    lines = ["## 1. 实现漂移（共用文件是否与模板一致）", ""]
    ok = True
    for rel, optional in SYNCED_FILES:
        ref = digest(TEMPLATE / rel)
        row = [f"- `{rel}` 模板 `{ref}`"]
        for repo in repos:
            path = repo / rel
            if optional and not path.exists():
                row.append(f"{repo.name} —未装")
                continue
            got = digest(path)
            mark = "✓" if got == ref else f"✗ {got}"
            row.append(f"{repo.name} {mark}")
            ok = ok and got == ref
        lines.append("｜".join(row))
    lines += ["", "**结论：** " + ("已装的处处一致。" if ok else "**存在漂移，必须修**——各方共用一份实现是硬要求。"), ""]
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


def check_health(repos: list, days: int = 7, recent: int = 1) -> list:
    """按天摊开信封 / 语义比例，结论只看最近 `recent` 个有流水的日子。

    把 7 天聚合成一个数字会让单个安装或调试日污染整周：实测装机当天堆出 37 条信封
    对 8 条语义，此后一周每次检查都报同一个警，而次日实际只有 2 条信封。按天出数才
    分得清「那天出过问题、已修」和「现在正在出问题」。

    `recent` 默认 1——结论要回答的是「机制现在是否正常」，最新的有流水日就是最新证据。
    取 2 天在流水只有两天时会把安装日本身圈进结论，等于没修。当天数据不完整只会让比例
    偏低（信封还没攒够），是漏报而非误报，次日自动纠正；小样本另有 5 条信封的下限兜着。

    更早的异常日留在明细里但不进结论——「那天是不是在装机或调协议」机械判定不了，
    交人看。检查器的职责是把能机械判定的部分从人的眼睛里拿走，不是制造虚假确定性。
    """
    lines = [f"## 4. 机制健康度（近 {days} 天 journal，按天）", ""]
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    for repo in repos:
        files = sorted(p for p in (repo / "journal").glob("20??-??-??.md") if p.name[:10] >= cutoff)
        lines += [f"### {repo.name}", ""]
        if not files:
            lines += [f"近 {days} 天没有流水文件。**结论：** 机制可能没在跑，或这段时间没开过会话。", ""]
            continue
        rows = []  # (日期, 语义数, 信封数, 是否异常)
        lengths = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            matches = list(HEADING.finditer(text))
            env = sem = 0
            for i, m in enumerate(matches):
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                if "会话信封" in m.group("rest"):
                    env += 1
                else:
                    sem += 1
                    lengths.append(end - m.start())
            # 信封少于 5 条时比例不稳——一天开两次会话就能触发，那是正常使用不是失效。
            odd = env >= 5 and env > max(sem, 1) * 2
            rows.append((path.name[:10], sem, env, odd))
        for date, sem, env, odd in rows:
            mark = f"  ⚠️ 信封是语义的 {env / max(sem, 1):.1f} 倍" if odd else ""
            lines.append(f"- {date}：语义 {sem} 条 / 信封 {env} 条{mark}")
        lines.append("")

        recent_odd = [r[0] for r in rows[-recent:] if r[3]]
        older_odd = [r[0] for r in rows[:-recent] if r[3]]
        avg = round(sum(lengths) / len(lengths)) if lengths else 0
        if recent_odd:
            lines.append(
                f"**结论：{'、'.join(recent_odd)} 异常**：查空转判定"
                "（信封应只在会话真干过活时写），或有人只写信封不写判断。"
            )
        else:
            lines.append(f"**结论：** 最近有流水的 {recent} 天（{rows[-1][0]}）正常。")
        if older_odd:
            lines.append(
                f"更早的异常日：{'、'.join(older_odd)}——若那天在装机或调协议，属预期；否则查空转判定。"
            )
        lines.append(f"语义条目均长 {avg} 字符（{len(files)} 天合计）。"
                     + ("  ⚠️ 条目偏长：细节应进任务目录，此处只留判断和理由" if avg > 4000 else ""))
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
