#!/usr/bin/env python3
"""协作流水（Collaboration Journal）共用逻辑：所有 Agent 共用同一份实现。

各方的差别只有 `--agent` 一个参数——读取游标认自己的语义条目，兜底通道指向其余各方的
会话记录。行为变更只改这里，各方不会漂移。

设计约束见 `journal/README.md`「成本控制」。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
JOURNAL_DIR = REPO_ROOT / "journal"
BIN_DIR = JOURNAL_DIR / "bin"
STATE_DIR = REPO_ROOT / ".journal-state"

AGENTS = ("claude", "codex", "trae")

# 条目标题：`## [agent] 14:30 PDT — 标题` 或 `## [agent] 会话信封 14:30 PDT`
HEADING = re.compile(r"(?m)^## \[(?P<agent>[^\]]+)\]\s*(?P<rest>.*)$")
ENVELOPE_MARK = "会话信封"

# 产物路径行：`- **产物：** `path``。降级注入时必须原样带上，见 entry_digest()。
ARTIFACT_LABEL = "产物"
ARTIFACT_LINE = re.compile(r"(?m)^- \*\*{}：\*\*.*$".format(ARTIFACT_LABEL))

# 注入预算：单文件 6000 字符、最多 3 天。超出部分显式标注，提示主动补读。
MAX_FILES = 3
MAX_CHARS_PER_FILE = 6000


# ---------------------------------------------------------------- 基础工具


def other_agents(agent: str) -> tuple:
    """除自己以外的**所有** Agent。

    返回元组而不是单个值：协作方不止两个时，「对方 = 另一个」会静默只渲染其中一方的
    兜底通道，另一方的存在就此消失且不报错。
    """
    return tuple(a for a in AGENTS if a != agent)


def now() -> datetime:
    """必须 astimezone()：naive datetime 的 %Z 是空字符串。"""
    return datetime.now().astimezone()


def read_hook_input() -> dict:
    try:
        value = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def emit(event: str, context: str) -> None:
    json.dump(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}},
        sys.stdout,
        ensure_ascii=False,
    )


def git_raw(*args: str) -> str:
    """不 strip——`git status --porcelain` 首行的前导空格是状态位，不能丢。"""
    try:
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def git(*args: str) -> str:
    return git_raw(*args).strip()


def head_short() -> str:
    """仓库尚无 commit 时 `rev-parse HEAD` 会失败，返回 `unknown` 而不是抛错。"""
    return git("rev-parse", "--short", "HEAD") or "unknown"


def display_path(raw: str) -> str:
    home = str(Path.home())
    return "~" + raw[len(home):] if raw.startswith(home + os.sep) else raw


def append_locked(path: Path, content: str, day: str, marker: str = "") -> None:
    """flock 追加：多方同时结束会话时不会互相截断。marker 非空时做幂等去重。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            if marker:
                handle.seek(0)
                if marker in handle.read():
                    return
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write("# {}\n".format(day))
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------- 流水解析


def journal_sections() -> list:
    """返回 [(文件, agent, 是否信封, 正文)]，按文件名和文件内顺序。"""
    sections = []
    for path in sorted(JOURNAL_DIR.glob("20??-??-??.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        matches = list(HEADING.finditer(text))
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections.append(
                (
                    path,
                    match.group("agent").strip().lower(),
                    ENVELOPE_MARK in match.group("rest"),
                    text[match.start():end].rstrip(),
                )
            )
    return sections


def entry_title(body: str) -> str:
    """条目标题行，去掉 markdown 的 `## `。"""
    return (body.splitlines()[0] if body else "").lstrip("# ").strip()


def artifact_lines(body: str) -> list:
    return [m.group(0) for m in ARTIFACT_LINE.finditer(body)]


def entry_digest(body: str) -> str:
    """预算不够时保留的最小可定位单位：标题 + 产物路径。

    只留标题不够——产物路径只写在正文里，一超预算就被丢掉，接手方只能按标题的语义
    相似度猜是哪个文件，**猜错了还不报错**（实测：一天 28 条语义条目 30876 字符，
    三条同主题条目 4295 字符全被压成三行标题，另一方据此定位到了错的产物）。
    """
    return "\n".join(["- {}".format(entry_title(body))]
                     + ["  {}".format(line) for line in artifact_lines(body)])


def unread_sections(agent: str) -> list:
    """游标 = 自己最后一条**语义**条目；其后的条目里再剔掉所有信封。

    信封不携带语义，既不算游标也不进注入——否则注入量会随会话数无限增长。
    """
    sections = journal_sections()
    cursor = -1
    for i, (_, owner, envelope, _) in enumerate(sections):
        if owner == agent and not envelope:
            cursor = i
    return [
        (path, body)
        for path, _, envelope, body in sections[cursor + 1:]
        if not envelope
    ]


def has_semantic_entry_today(agent: str, day_text: str) -> bool:
    """今天这份文件里有没有本方的语义条目。"""
    for match in HEADING.finditer(day_text):
        if match.group("agent").strip().lower() == agent and ENVELOPE_MARK not in match.group("rest"):
            return True
    return False


def has_semantic_entry_after(agent: str, day_text: str, since: datetime) -> bool:
    """本方在 `since` 之后写过语义条目吗（精度到分钟，边界宁可放宽一分钟）。"""
    for match in HEADING.finditer(day_text):
        rest = match.group("rest")
        if match.group("agent").strip().lower() != agent or ENVELOPE_MARK in rest:
            continue
        stamp = re.match(r"\s*(\d{1,2}):(\d{2})", rest)
        if not stamp:
            continue
        if int(stamp.group(1)) * 60 + int(stamp.group(2)) >= since.hour * 60 + since.minute:
            return True
    return False


def wrote_semantics_this_session(agent, session_id, day_text, since=None):
    """**本次会话**有没有写过语义条目——空转判定必须精确到会话，不是精确到当天。

    按天判断会退化：当天写过第一条之后，之后每个会话（哪怕只问了一句话）都会被
    判成「干过活」而写信封，一天堆出几十条无内容条目，反过来挤占注入预算。

    两级判定，都不依赖调用方记得传参：
    1. `append.py` 在条目末尾写的 `<!-- <agent>-session:<id> -->` 标记（最精确）；
    2. 手工追加、忘了带 `--session-id` 时，退回比对会话起始时间（`since` 取
       `.journal-state/` 状态文件的 mtime，由 SessionStart 写入）。
    两者都拿不到才退回按天判断——宁可多写一条信封，也不漏记会话。
    """
    if session_id and "<!-- {}-session:{} -->".format(agent, session_id) in day_text:
        return True
    if since is not None:
        return has_semantic_entry_after(agent, day_text, since)
    return has_semantic_entry_today(agent, day_text)


# ------------------------------------------------------- 兜底通道：原始记录


def project_slug() -> str:
    """项目路径转写：非字母数字字符逐个替换为 `-`。Claude 与 TRAE 实测是同一套规则。"""
    return "".join(c if c.isalnum() else "-" for c in str(REPO_ROOT))


def claude_transcript_dir() -> Path:
    return Path.home() / ".claude" / "projects" / project_slug()


def claude_transcripts(days: int = 1, limit: int = 5) -> list:
    directory = claude_transcript_dir()
    if not directory.is_dir():
        return []
    cutoff = (now() - timedelta(days=days)).timestamp()
    found = [p for p in directory.glob("*.jsonl") if p.stat().st_mtime >= cutoff]
    return sorted(found, key=lambda p: p.stat().st_mtime)[-limit:]


def codex_rollouts(days: int = 1, limit: int = 5, this_project_only: bool = True) -> list:
    """Codex 的 sessions 目录是全局的（所有项目混在一起）。

    每个 rollout 首行是 `session_meta`，其中带 `cwd`——只读首行即可按项目过滤，
    避免把别的项目的会话记录塞进来。
    """
    root = Path.home() / ".codex" / "sessions"
    if not root.is_dir():
        return []
    cutoff = (now() - timedelta(days=days)).timestamp()
    candidates = []
    for path in root.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        if this_project_only and rollout_cwd(path) != str(REPO_ROOT):
            continue
        candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime)[-limit:]


def rollout_cwd(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as handle:
            first = handle.readline()
    except OSError:
        return ""
    try:
        payload = json.loads(first).get("payload", {})
    except (json.JSONDecodeError, ValueError, AttributeError):
        return ""
    return str(payload.get("cwd", "")) if isinstance(payload, dict) else ""


def trae_memories(days: int = 1, limit: int = 5) -> list:
    """TRAE 的会话记忆：`~/.trae-cn/memory/projects/<slug>/YYYYMMDD/session_memory_*.jsonl`。

    与另一批「原始对话」记录不同，这里落盘的**已经是结构化摘要**（intent / actions /
    outcome / learned）——所以 TRAE 侧不写会话信封：信封只保证「会话发生过、记录在
    哪」，这个目录本身就已经做到，还多带了语义。
    """
    directory = Path.home() / ".trae-cn" / "memory" / "projects" / project_slug()
    if not directory.is_dir():
        return []
    cutoff = (now() - timedelta(days=days)).timestamp()
    found = []
    for path in directory.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime >= cutoff:
                found.append(path)
        except OSError:
            continue
    return sorted(found, key=lambda p: p.stat().st_mtime)[-limit:]


def records_for(agent: str, days: int = 1, limit: int = 5, this_project_only: bool = True) -> list:
    """按 agent 分派到各自的记录目录。

    渲染侧（`context.py`）和读取侧（`peek.py`）共用这一份分派——各写一份 if/else
    就是漂移的开始，而且漏掉一个分支时会静默落到 else，读成另一个 Agent 的记录。
    """
    if agent == "codex":
        return codex_rollouts(days, limit, this_project_only)
    if agent == "trae":
        return trae_memories(days, limit)
    return claude_transcripts(days, limit)


def peek_command(agent_to_read: str) -> str:
    """读对方原始记录的唯一合法方式：抽取，不是全读。"""
    return '/usr/bin/python3 "{}/peek.py" --agent {}'.format(BIN_DIR, agent_to_read)


def append_command(agent: str, session_id: str = "") -> str:
    """每轮提醒里的写入模板。`--artifact` 放进模板而不是只写进协议文档：

    它是每轮都进上下文的机制提示，文档不是——能用机制保证的不靠文档提醒。
    """
    session = ' --session-id "{}"'.format(session_id) if session_id else ""
    return (
        '/usr/bin/python3 "{}/append.py" --agent {}{} '
        '--title "<标题>" --doing "<单一主目标>" --judgment "<关键判断>" '
        '--artifact "<产出或改写的文件路径>"'
    ).format(BIN_DIR, agent, session)


# ---------------------------------------------------------------- 会话状态


def state_file(agent: str, session_id: str) -> Path:
    return STATE_DIR / agent / "{}.head".format(session_id or "unknown")


def watermark_file(agent: str, session_id: str) -> Path:
    return STATE_DIR / agent / "{}.seen".format(session_id or "unknown")


def section_key(path: Path, body: str) -> str:
    """条目指纹：文件名 + 标题行。标题含 agent 与时间，同文件内足够唯一。"""
    return "{}|{}".format(path.name, body.splitlines()[0] if body else "")


def record_watermark(agent: str, session_id: str, sections=None) -> None:
    """记下「本会话已经看到哪一条」，供每轮提醒判断中途有没有新条目。

    水位取当时的**最后一条**（不论是谁的、是不是信封），这样后续只要出现任何
    新条目都能被发现；真正注入时再过滤掉信封和自己的条目。
    """
    if not session_id:
        return
    if sections is None:
        sections = journal_sections()
    key = section_key(sections[-1][0], sections[-1][3]) if sections else ""
    path = watermark_file(agent, session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key, encoding="utf-8")
    except OSError:
        pass


def unread_since_watermark(agent: str, session_id: str) -> list:
    """本会话开始（或上次注入）之后，对方新增的语义条目。

    找不到水位记录时返回空——宁可不注入，也不要在会话中途重复灌历史内容。
    """
    if not session_id:
        return []
    path = watermark_file(agent, session_id)
    try:
        key = path.read_text(encoding="utf-8").strip() if path.exists() else None
    except OSError:
        return []
    if key is None:
        return []

    sections = journal_sections()
    start = 0
    if key:
        start = None
        for i, (sec_path, _, _, body) in enumerate(sections):
            if section_key(sec_path, body) == key:
                start = i + 1
                break
        if start is None:  # 水位对应的条目被改写或删除，放弃本轮追赶
            return []
    return [
        (sec_path, body)
        for sec_path, owner, envelope, body in sections[start:]
        if not envelope and owner != agent
    ]


def nonjournal_status_digest() -> str:
    """工作区状态指纹：`git status --porcelain` 里除 `journal/` 外的行的稳定摘要。

    空转判定要比的是「本次会话改了什么」，不是「工作区脏不脏」——实际使用模式是
    产物长期不 commit（push 等用户指令），工作区常年带着几十项未提交改动，「脏 =
    干过活」在这种模式下恒为真：2026-07-30 实测一个连 transcript 都没有的空会话
    照样写了信封。排除 `journal/` 与 end.py 的 dirty_signal 同理：对方追加条目
    不算本方干活。`.journal-state/` 正常情况下被 gitignore，但指纹不赌这件事——
    哪个项目漏配了那一行，SessionStart 写的状态文件就会让每个会话都被判成「干过活」。"""
    lines = sorted(
        line for line in git_raw("status", "--porcelain").splitlines()
        if line.strip() and not line[3:].startswith(("journal/", ".journal-state/"))
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:12]


def record_start_head(agent: str, session_id: str) -> None:
    """记录会话起点：第一行 HEAD、第二行工作区状态指纹。

    **已存在时不覆盖**：compact / resume / clear 都会再次触发 SessionStart，
    覆盖会把基线刷新到触发时刻，会话早期的改动就从「变化」里消失了。"""
    if not session_id:
        return
    path = state_file(agent, session_id)
    if path.exists():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "{}\n{}".format(head_short(), nonjournal_status_digest()),
            encoding="utf-8",
        )
    except OSError:
        pass


def read_start_state(agent: str, session_id: str):
    """读会话起点：(起始 HEAD, 起始状态指纹, 起始时间)。

    旧格式状态文件（只有 HEAD 一行）的指纹返回空串——调用方退回「工作区是否脏」
    的旧判据，正在进行的会话平滑过渡，不因格式升级误判。状态文件的 mtime 即会话
    起始时间：`append.py` 漏传 --session-id 时空转判定的兜底判据。"""
    state = state_file(agent, session_id)
    try:
        if not state.exists():
            return "", "", None
        lines = state.read_text(encoding="utf-8").splitlines()
        since = datetime.fromtimestamp(state.stat().st_mtime).astimezone()
    except OSError:
        return "", "", None
    head = lines[0].strip() if lines else ""
    status = lines[1].strip() if len(lines) > 1 else ""
    return head, status, since


STALE_STATE_DAYS = 7


def cleanup_stale_state(days: int = STALE_STATE_DAYS) -> None:
    """清理超龄状态文件。SessionEnd 不保证触发（强关、断电时 harness 不跑 hook），
    `.head` / `.seen` 会残留；单个只有几十字节，但没人清就只增不减。挂在
    SessionStart 顺手做，不新增触发点。"""
    if not STATE_DIR.is_dir():
        return
    cutoff = now().timestamp() - days * 86400
    for path in STATE_DIR.rglob("*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue
