"""任务清单工具：状态存在 run_context.session_state，随会话写库。"""

from agno.run import RunContext


def _todos(run_context: RunContext) -> list:
    """取当前会话的任务清单；不存在则初始化。"""
    if run_context.session_state is None:
        run_context.session_state = {}
    return run_context.session_state.setdefault("todos", [])


def todo_add(run_context: RunContext, items: str) -> str:
    """向当前会话的任务清单追加条目。

    Args:
        items: 一条或多条任务，用换行或分号分隔。
    """
    todos = _todos(run_context)
    added = [part.strip() for part in items.replace(";", "\n").splitlines() if part.strip()]
    for text in added:
        todos.append({"text": text, "done": False})
    return f"已添加 {len(added)} 条，当前共 {len(todos)} 条。"


def todo_list(run_context: RunContext) -> str:
    """列出当前会话的任务清单。"""
    todos = _todos(run_context)
    if not todos:
        return "任务清单为空。"
    return "\n".join(
        f"{i}. [{'x' if item['done'] else ' '}] {item['text']}"
        for i, item in enumerate(todos, 1)
    )


def todo_done(run_context: RunContext, index: int) -> str:
    """把任务标记为完成。

    Args:
        index: 任务编号，从 1 开始。
    """
    todos = _todos(run_context)
    if not 1 <= index <= len(todos):
        return f"编号超出范围（1-{len(todos)}）。"
    todos[index - 1]["done"] = True
    return f"已完成：{todos[index - 1]['text']}"
