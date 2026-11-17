# sessions — 模块设计

## 边界与目标

会话查询、命名与标题生成，是 Agno `SqliteDb` 的薄封装。不拥有会话内容（Agno 写库），只回答两件事：哪个会话是本目录最近的、「-c/-r」该续接哪个；会话标题怎么来。

## 拥有者与不变量

- 会话 id 由 `new_session_id(settings)` 生成：uuid hex 前 `sessions.id_length` 位，短且可读。
- 「本目录最近会话」由库内索引表 `aaa_cwd_session(cwd PK, session_id, seq)` 维护，与 Agno 的会话表同库。`seq` 单调递增，用来在 `updated_at` 只有秒级精度时仍能定序；主键查询走 B-tree，等价于按键取值的索引。
- 会话名称格式 `"{title_prefix} {TAG: summary}"`：`TAG` 为 3–5 位大写 ASCII，摘要不超过 12 词；标题截断长度取 `sessions.title_length`；生成失败返回空串，不报错、不改名。
- 已命名的会话不重复生成（进程内 `named` 集合 + `get_session_name` 双重判断）。
- 会话内容与排序完全复用 Agno 的数据库接口；本模块只额外拥有索引表 `aaa_cwd_session` 这一小块数据，不缓存会话列表。

## 对外接口

- `new_session_id(settings)`、`remember_session(cwd, session_id)`、`list_sessions(agent, limit)`。
- `latest_session_for_cwd(agent, cwd, settings)`：索引表命中且会话仍存在则用它，否则回落到 `metadata.cwd` 匹配的最近 `sessions.search_limit` 条记录。索引实现见 `sessions/index.py`。
- `find_session(agent, prefix, settings)`：完整 id 优先，其次前缀；多个前缀命中取最近的一个。
- `session_label(session)`：标题 · id · 更新时间。
- `generate_title(channel, model, text, max_length)`：经 `model.build_title_model` 构造不带重试的模型，一次非流式 `response`；输出清洗为 ASCII 起始、按配置截断。
- `ensure_session_name(..., settings)`：首次发言后命名，所有失败静默返回。

## 已否决做法

- 单用 `updated_at` 推断「本目录最近会话」：秒级精度且跨目录会话混在一起 → 自建索引表并用单调 `seq` 定序，命中失败再回落到 metadata。
- 用文件系统指针（曾用 `data/last-session/<hash>.txt`）：索引与库分离，可能不同步 → 索引进同一个库，成为普通表。
- 前缀多命中时报错要求用户补全：`-r` 的典型用法就是贴前缀 → 取最近的即可。
- 标题失败时提示用户：命名是附属行为，失败不该打断对话 → 返回空串跳过。
