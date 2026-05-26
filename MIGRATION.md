# Migration Note — `ai-companion-eval-tool` 起源

> 本 repo 由 mono-repo `e:\提效工具` 的子目录 `长文模式生成/` 在 2026-05-27 通过 `git filter-branch --subdirectory-filter` 拆分而来。

## 速查

| 项 | 值 |
|:--|:--|
| 拆分日期 | 2026-05-27 |
| 拆分方法 | `git filter-branch --subdirectory-filter`（`git subtree` 在 Windows 中文路径上有 bug，已绕过） |
| 拆分基点 | mono-repo `c7038871` (tag: `pre-split-backup-20260527`) |
| 历史长度 | 5 commits（因 mono-repo 的 `github-snapshot` 分支本身是浅历史快照） |
| 当前 HEAD | `98d1e3a` (main) |

## Commit 映射

| 本 repo | ← mono-repo |
|:--|:--|
| `98d1e3a` | `123432fb` (WIP snapshot — 前端 overhaul + 新模型) |
| `e4edd8b` | `930a44ab` (review bug fixes) |
| `c95ce39` | `c7038871` (目录重组) |
| `b01b697` | `db781a31` (Fix batch scoring timeout handling) |
| `41b1740` | `37d4cb4c` (Initial snapshot from test/long-short-fusion-v52) |

## 完整迁移说明

详见 mono-repo 根目录的 `MIGRATION.md` —— 含拆分动机、分阶段命令、回滚方法、submodule 日常操作。

## 项目入口

- 启动：`python server/main.py`
- 回归测试：`pytest tests/ -v`（基线 378 通过）
- CLI：`python longform_multi_turn.py <config.json> [--turns N]`
- 详见 `README.md` 与 `ARCHITECTURE.md`
