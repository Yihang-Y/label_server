from sqlalchemy import text
from config import DB_CONNINFO
from typing import Any, Dict, List, Optional

from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
 
async def fetch_step(thread_id: str, step_id: str):
    sql = text("""
        SELECT
            s."id"       AS step_id,
            s."name"     AS step_name,
            s."parentId" AS step_parentid,
            s."input"    AS step_input,
            s."output"   AS step_output
        FROM steps s
        WHERE s."threadId" = :thread_id
          AND s."id" = :step_id
        LIMIT 1
    """)
    data_layer = SQLAlchemyDataLayer(conninfo=DB_CONNINFO)

    async with data_layer.async_session() as session:
        result = await session.execute(sql, {"thread_id": thread_id, "step_id": step_id})
        row = result.mappings().first()
        return row
    

async def get_openai_history(thread_id: str, compressed: bool = False, cot_settings: Optional[str] = None) -> List[Dict[str, str]]:
    data_layer = SQLAlchemyDataLayer(conninfo=DB_CONNINFO)
    thread = await data_layer.get_thread(thread_id)

    # 1) 全量 flatten（先不排序）
    flat: List[Dict[str, Any]] = []

    def collect_steps(steps: List[Dict[str, Any]]):
        for s in steps or []:
            # 跳过 wrapper steps，但继续收集其 children
            if s.get("name") in ["on_chat_start", "on_message", "on_audio_end"]:
                collect_steps(s.get("steps") or [])
                continue

            flat.append(s)
            collect_steps(s.get("steps") or [])

    collect_steps(thread.get("steps", []))

    # 2) 全局按 createdAt 排序（保证跨层顺序稳定）
    flat_sorted = sorted(
        [s for s in flat if s.get("createdAt")],
        key=lambda x: x["createdAt"]
    )

    # 3) 找到“最后一个 cot step”
    last_cot = None
    for s in flat_sorted:
        if s.get("type") == "cot":
            last_cot = s

    messages: List[Dict[str, str]] = []

    for s in flat_sorted:
        stype = s.get("type") or ""

        if stype in ["system_message", "user_message", "assistant_message"]:
            content = (s.get("output") or "")
            if stype == "assistant_message" and content == '**Selected:** Continue':
                continue
            messages.append({"role": stype.replace("_message", ""), "content": content})

        elif stype == "tool":
            if compressed:
                continue
            input_content = (s.get("input") or "")
            output_content = (s.get("output") or "")
            # 简单回放（如果你们没有 tool_call_id）
            messages.append({"role": "assistant", "content": input_content})
            messages.append({"role": "tool", "content": output_content})

        elif stype == "cot":
            if not compressed or s is last_cot:
                output_content = str(s.get("output") or "").strip()
                messages.append({"role": "assistant", "content": f"<think>{output_content}</think>"})
            else:
                plan = str(s.get("input") or "").strip()
                messages.append({"role": "assistant", "content": f"<think>{plan}</think>"})

    return messages
