# 备忘录

暂不执行、但需要保持可见的计划。每条写清「触发条件 / 做法 / 为什么现在不做」，做完即删，不留变更痕迹。

## 依赖升级时才开的新版本隔离期

- 触发：第一次 bump 任何一个 `pyproject.toml` 里的直接依赖（最可能是 agno）。
- 做法：加 `[tool.uv] exclude-newer = "14 days"`，让发布不满 14 天的版本不进解析；需要抢安全修复的包用 `exclude-newer-package` 单列豁免。这是 Hermes 的做法，针对的是「上游刚被投毒的版本在隔离期内无人复核就被装进来」。
- 为什么现在不做：它与「锁文件以当前实测版本为准」直接冲突——开启后解析会拒绝当前基线里的新包，锁结果偏离已验证环境。
- 升级动作一并约定：改 `pyproject.toml` 的 `==` → `uv lock` → `uv sync --frozen` → 重跑 `tests/e2e.py` 全套；重点确认 agno 的 `MemoryManager(model=, db=)`、`CodingTools`、`RunPausedEvent`/`continue_run` 三个面没变。
