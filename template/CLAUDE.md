# CLAUDE.md

本项目的协作规范以 [`AGENTS.md`](AGENTS.md) 为唯一真相源（single source of truth）。
所有协作的 Agent 共用同一套规则。**不要在本文件中复制、改写或补充 AGENTS.md 的内容**——
需要调整规范时改 `AGENTS.md`，本文件只保留指针。

@AGENTS.md

## 会话启动

若上面的导入未生效，先手动读取 [`AGENTS.md`](AGENTS.md)，再按其中的项目知识协议读取本仓库的
知识层入口文件，然后说明本次会话的单一主目标。

协作流水（`journal/`）由 hook 自动注入未读条目；机制和写入方式见
[`journal/README.md`](journal/README.md)。
