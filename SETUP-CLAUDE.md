# 给 Claude Code 的安装说明书

> **怎么用：** 在目标仓库打开 Claude Code，把本文件整份粘贴进去（或说「按 SETUP-CLAUDE.md 执行」并把文件放进仓库）。
> 下面的内容是给 Claude 的指令，不是给人读的操作手册。

---

你要在当前仓库装一套 Claude Code ↔ Codex 协作机制，然后**自己验证它真的在跑**，最后把结果报告给用户。

装完的效果：两个 Agent 共享同一套规范、同一份过程流水；一方做过的判断、否决过的路径、留下的未决项，另一方下次开会话时自动出现在上下文里，不需要用户手工转述。

## 0. 前置检查（不满足就停下问用户，不要自作主张）

```bash
git rev-parse --show-toplevel     # 必须是 git 仓库
git rev-parse --short HEAD        # 必须至少有一个 commit
/usr/bin/python3 -V               # 必须存在；脚本兼容 3.9
```

- **仓库没有任何 commit 时停下**：协议里的 HEAD 比对、空转判定全部依赖 HEAD 存在。先问用户是否可以建立第一个 commit，并确认哪些内容该进 `.gitignore`（运行日志、临时产物、`.DS_Store` 等）。
- 工具包（kit）文件夹的位置：默认与本文件同级的 `template/`。找不到就问用户要。

## 1. 复制文件（已存在且内容一致就跳过，本步骤幂等）

从 `template/` 复制到仓库根目录：

| 来源 | 目标 | 说明 |
|---|---|---|
| `template/journal/bin/*.py` | `journal/bin/` | 五个脚本，两侧共用，**不要改**（见第 6 节） |
| `template/journal/README.md` | `journal/README.md` | 这一层的规则说明 |
| `template/.claude/settings.json` | `.claude/settings.json` | Claude 侧三个 hook |
| `template/.codex/hooks.json` | `.codex/hooks.json` | Codex 侧三个 hook（你装文件，Codex 自己批准） |

仓库已有 `.claude/settings.json` 时**不要覆盖**：把 `hooks` 里的三项合并进去，其余配置原样保留。

## 2. 写协议（需要判断，别机械照抄）

- 仓库**没有** `AGENTS.md`：直接用 `template/AGENTS.md`，删掉顶部的模板说明段。
- 仓库**已有** `AGENTS.md`：把「多 Agent 协作协议」整节插到最前面，**保留原有全部内容**，一个字都不要删。

两处必须按本仓库填空，填完删掉 `【填空】` 标记：

1. **第 1 条的任务目录**——本仓库放任务产物的地方叫什么（`work/<task-id>/`、`analysis/<task-id>/`，或仓库已有的习惯）。**不要预建空目录**，用到时再建。
2. **第 2 条的知识层写入门槛**——二选一，删掉不用的那档：
   - A 档（严）：所有写入都要用户确认。
   - B 档（松）：纯新增可直接写，改写或删除必须先给用户看原文。

   **必须问用户选哪档**，不要替他决定。问的时候给判断依据：结论直接影响对外决策、错一条代价高 → A 档；日常调研迭代快、写回频繁 → B 档。

   填完检查目标仓库有没有**自己的知识写回条款**（如「会话路由与知识收尾」一类章节）——有的话两处必须一致，不一致就同步改掉另一处。曾有项目松档位与自有的「写前必须确认」互斥并存 5 天才被周检发现。

再写 `CLAUDE.md`（用 `template/CLAUDE.md`）：它只放一个指向 `AGENTS.md` 的指针。**不要在 CLAUDE.md 里复制协议内容**——两份规范一定会漂移，这是整套机制最容易坏的地方。

## 3. `.gitignore`

追加 `template/gitignore-additions.txt` 的内容（`.journal-state/`）。这是 hook 运行态，记录各会话起始 HEAD 和起始时间，不进版本控制。

## 4. Commit

```bash
git add AGENTS.md CLAUDE.md journal .claude .codex .gitignore
git commit -m "[claude] Add Claude/Codex collaboration layer: protocol, journal, hooks"
```

只 stage 上面这些路径，**禁止 `git add -A`**。若 `git status` 里有来源不明的改动，停下问用户，不要顺手提交。

## 5. 验证（逐项跑，把实际输出贴给用户）

前六项你现在就能做完，后两项需要用户配合。

### V1 读取侧能跑

```bash
echo '{"hook_event_name":"SessionStart","session_id":"verify"}' | /usr/bin/python3 journal/bin/context.py --agent claude
```

期望：一段 JSON，`additionalContext` 里含「协作流水（过程记录，不具备规范效力）」。首次安装时应显示「没有比自己上次记录更新的条目」。

### V2 每轮提醒够短

```bash
echo '{"hook_event_name":"UserPromptSubmit","session_id":"verify"}' | /usr/bin/python3 journal/bin/context.py --agent claude \
  | /usr/bin/python3 -c "import json,sys; print(len(json.load(sys.stdin)['hookSpecificOutput']['additionalContext']), '字符')"
```

期望：约 310–400 字符（提醒里含仓库绝对路径，路径长则偏多；实测两个仓库为 326 与 340）。这条每轮都注入，长了就是持续成本。
**不要用 `wc -c` 量**——那数的是整段 JSON 的字节数，中文一字三字节，量出来的不是注入长度。

### V2b 会话中途追赶（长会话不必重开也能收到对方的新条目）

SessionStart 每会话只跑一次，所以对方在你会话进行中写的条目，靠它是拿不到的。每轮提醒的 hook 会顺带比对一次本会话水位，把新条目带进来。验证：

```bash
mkdir -p .journal-state
echo '{"hook_event_name":"SessionStart","session_id":"mid"}' | /usr/bin/python3 journal/bin/context.py --agent claude > /dev/null
/usr/bin/python3 journal/bin/append.py --agent codex --title "中途测试" --judgment "临时条目" > /dev/null
for i in 1 2; do
  echo '{"hook_event_name":"UserPromptSubmit","session_id":"mid"}' | /usr/bin/python3 journal/bin/context.py --agent claude \
    | /usr/bin/python3 -c "import json,sys; print('第 $i 轮带出新条目:', '本次会话期间新增' in json.load(sys.stdin)['hookSpecificOutput']['additionalContext'])"
done
```

期望：**第 1 轮 True，第 2 轮 False**——带出一次，水位前移，同一条不重复灌。验证完删掉这条测试条目和 `.journal-state/`。

### V3 写入侧能跑

```bash
/usr/bin/python3 journal/bin/append.py --agent claude --title "安装验证" --judgment "验证 append 可用，稍后删除"
```

期望：打印出 `journal/<今天>.md` 路径，文件里出现 `## [claude] HH:MM TZ — 安装验证`。**验证完把这条测试条目删掉**，别留在流水里。

### V4 空转会话不写信封

```bash
mkdir -p .journal-state/claude && git rev-parse --short HEAD > .journal-state/claude/idle.head
git status --porcelain           # 先确认工作区干净
echo '{"hook_event_name":"SessionEnd","session_id":"idle"}' | /usr/bin/python3 journal/bin/end.py --agent claude
```

期望：**没有任何新增信封**。这一条最容易被漏测，一旦坏了，流水会被无内容条目淹没（实测出现过一天 25 条信封对 4 条语义）。

### V5 干过活的会话写信封，且重放不重复

```bash
git rev-parse --short HEAD > .journal-state/claude/work.head
/usr/bin/python3 journal/bin/append.py --agent claude --session-id "work" --title "信封验证" --judgment "临时条目"
echo '{"hook_event_name":"SessionEnd","session_id":"work"}' | /usr/bin/python3 journal/bin/end.py --agent claude
echo '{"hook_event_name":"SessionEnd","session_id":"work"}' | /usr/bin/python3 journal/bin/end.py --agent claude
```

期望：只出现**一条**信封（第二次是幂等重放，不应重复写）。验证完删掉这两条测试条目和 `.journal-state/`。

### V6 兜底通道

```bash
/usr/bin/python3 journal/bin/peek.py --agent codex
```

期望：输出 Codex 在**本项目**的近 24h 记录摘要，或「近 1 天没有本项目的 codex 会话记录」。两者都算通过——它证明脚本能定位并过滤。

**任何时候都不要对 `.jsonl` 用 Read 或 cat**：实测单个 Codex rollout 达 135 MB，读一次就撑爆上下文。

### V7 真实会话注入（需要用户配合）

hook 在会话**启动时**加载，所以**本次会话装的 hook 对本次会话不生效**。请用户结束当前会话、重新打开一次，然后确认：

- 会话开头出现「协作流水」块；
- `.journal-state/claude/<session-id>.head` 生成了。

### V8 跨 Agent 握手（最终验收）

这是唯一能证明「协作」成立的测试，前七项都只证明了单边可用：

1. 你现在写一条真实的语义条目（不是测试条目），说明本次装了什么、有哪些未决项：
   ```bash
   /usr/bin/python3 journal/bin/append.py --agent claude --session-id "<本次会话 id>" \
     --title "装好协作层，等待 Codex 侧信任审批" \
     --doing "安装 Claude ↔ Codex 协作机制" \
     --judgment "<你实际做的判断，例如知识层门槛选了哪档、任务目录定在哪>" \
     --open "Codex 侧需用户批准 .codex/hooks.json 后验证" \
     --artifact "AGENTS.md" --artifact "journal/README.md"
   ```
2. 请用户在同一仓库开一次 Codex，按 `SETUP-CODEX.md` 执行。
3. Codex 那侧应当在会话开头看到你这条，并回写一条它自己的。
4. 用户再开一次 Claude 会话，你应当在开头看到 Codex 那条——**看到即握手成功**。

## 6. 三条绝对不要做的事

1. **不要把脚本改成 Claude 专用、或在 `.claude/hooks/` 下另写一份。** 两侧共用 `journal/bin/*.py` 是硬要求：曾经两侧各写一份，半天内漂移出四个 bug，其中「游标把会话信封当成语义条目」会让对方的判断**永久不被读到且不报错**。
2. **不要替 Codex 批准它的 hook**（不要去写 `~/.codex/config.toml` 的 `trusted_hash`，不要用绕过参数）。hook 能执行任意命令，自批等于取消这道安全控制。那是用户在 Codex 里点一下的事。
3. **不要把半成品写进知识层。** 未验证的判断、被否决的路径、还没想清的方向，全部进 `journal/`——那层不需要用户确认，正是为此存在。

## 7. 报告

给用户一张表：装了哪些文件、V1–V6 各自的实际输出、V7–V8 需要他做什么、协议里两处填空最终填成什么。有任何一项没过，直接说没过，不要含糊。
