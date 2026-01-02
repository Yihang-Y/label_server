from sqlalchemy import text
from config import DB_CONNINFO
from typing import Any, Dict, List, Optional

from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
 
async def fetch_step(data_layer, thread_id: str, step_id: str):
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
    # data_layer = SQLAlchemyDataLayer(conninfo=DB_CONNINFO)

    async with data_layer.async_session() as session:
        result = await session.execute(sql, {"thread_id": thread_id, "step_id": step_id})
        row = result.mappings().first()
        return row

RUN_STEP_NAMES = {"run"}  # 按你的系统改

def _is_run_step(name: str | None) -> bool:
    if not name:
        return False
    return name in RUN_STEP_NAMES

async def fetch_last_agent_turn(data_layer, thread_id: str):
    sql = text("""
        SELECT
        s."id",
        s."name",
        s."parentId",
        s."createdAt",
        s."type"
        FROM steps s
        WHERE s."threadId" = :thread_id
        AND s."type" = 'run'
        ORDER BY s."createdAt" DESC
        LIMIT 1
    """)

    async with data_layer.async_session() as session:
        rows = (await session.execute(sql, {"thread_id": thread_id})).mappings().all()
        if not rows:
            return None

        # rows[0] 是最新 step，往后是一路向上的 parent 链
        for r in rows:
            print(r.get("name"))
            print(r.get("step_id"))
            print(r)
            print("-----")
            if _is_run_step(r.get("name")):
                return r

        return rows[-1]
    
async def fetch_childs(data_layer, thread_id: str, parent_step_id: str):
    sql = text("""
        SELECT
            s."id"       AS step_id,
            s."name"     AS step_name,
            s."parentId" AS step_parentid,
            s."input"    AS step_input,
            s."output"   AS step_output
        FROM steps s
        WHERE s."threadId" = :thread_id
          AND s."parentId" = :parent_step_id
    """)

    async with data_layer.async_session() as session:
        result = await session.execute(sql, {"thread_id": thread_id, "parent_step_id": parent_step_id})
        rows = result.mappings().all()
        return rows


async def get_openai_history(data_layer, thread_id: str, branch_id: Optional[str] = None, compressed: bool = False, cot_settings: Optional[str] = None) -> List[Dict[str, str]]:
    import json
    
    # Thread may not exist yet if this is called before the first user message is persisted
    # In Chainlit, threads are created lazily when the first user message is sent
    thread = await data_layer.get_thread(thread_id)
    if not thread:
        # Thread not found - this can happen if:
        # 1. Thread hasn't been created yet (first message not persisted)
        # 2. Thread was deleted
        # 3. Thread ID is invalid
        print(f"Warning: Thread {thread_id} not found in database. This may be normal if called before first message is persisted. Returning empty history.")
        return []
    
    thread_metadata = thread.get("metadata", {})
    if not thread_metadata:
        thread_metadata = {}
    elif isinstance(thread_metadata, str):
        try:
            thread_metadata = json.loads(thread_metadata)
        except:
            thread_metadata = {}
    
    if not isinstance(thread_metadata, dict):
        thread_metadata = {}
    
    # Use current_branch_id from thread metadata if branch_id not provided
    current_branch_id = branch_id or thread_metadata.get("current_branch_id", "main")

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
    
    # Find fork point for current branch (if it's a forked branch)
    fork_point_step_id = None
    if current_branch_id != "main":
        branches = thread_metadata.get("branches", [])
        for branch_info in branches:
            if branch_info.get("branch_id") == current_branch_id:
                fork_point_step_id = branch_info.get("fork_point")
                break
    
    # Filter steps: include fork point and earlier steps (from any branch), 
    # plus current branch steps after fork point (non-inactive)
    filtered_steps = []
    fork_point_reached = False
    
    for s in flat_sorted:
        step_metadata = s.get("metadata", {})
        if isinstance(step_metadata, str):
            try:
                step_metadata = json.loads(step_metadata)
            except:
                step_metadata = {}
        
        step_branch_id = step_metadata.get("branch_id", "main")
        step_status = step_metadata.get("branch_status")
        step_id = s.get("id")
        
        # Check if we've reached the fork point
        if fork_point_step_id and step_id == fork_point_step_id:
            fork_point_reached = True
        
        # Include if:
        # 1. Before fork point (from any branch, not inactive) OR
        # 2. After fork point AND belongs to current branch AND not inactive
        if not fork_point_reached:
            # Before fork point: include from any branch (not inactive)
            if step_status != "inactive":
                filtered_steps.append(s)
        else:
            # After fork point: only include from current branch (not inactive)
            if step_branch_id == current_branch_id and step_status != "inactive":
                filtered_steps.append(s)
    
    # If no fork point found (main branch or branch not in branches list), 
    # just filter by current branch
    if not fork_point_reached:
        filtered_steps = []
        for s in flat_sorted:
            step_metadata = s.get("metadata", {})
            if isinstance(step_metadata, str):
                try:
                    step_metadata = json.loads(step_metadata)
                except:
                    step_metadata = {}
            
            step_branch_id = step_metadata.get("branch_id", "main")
            step_status = step_metadata.get("branch_status")
            
            if step_branch_id == current_branch_id and step_status != "inactive":
                filtered_steps.append(s)
    
    flat_sorted = filtered_steps

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
