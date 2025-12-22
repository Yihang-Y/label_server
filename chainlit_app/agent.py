import asyncio
import json
import chainlit as cl
from chainlit.context import context  

from config import MCP_TOOL_TIMEOUT
from llm_stream import stream_and_collect
from typing import Any, Mapping, Optional
from db_utils import get_openai_history

def _extract_tool_call(step_input_raw: Any) -> tuple[str, dict]:
    """
    支持两种常见输入结构：
    1) {"name": "...", "arguments": {...}}
    2) {"query": {"name": "...", "arguments": {...}}}
    step_input_raw 可以是 str / dict
    """
    payload = step_input_raw

    if isinstance(payload, str):
        payload = json.loads(payload) if payload else {}

    if isinstance(payload, dict) and "query" in payload and isinstance(payload["query"], dict):
        payload = payload["query"]

    func_name = (payload or {}).get("name", "unknown")
    args = (payload or {}).get("arguments") or {}
    if not isinstance(args, dict):
        args = {}

    return func_name, args

# def to_openai_messages(history):
#     return list(history)

async def ask_user():
    action = await cl.AskActionMessage(
            content=f"Continue ?",
            actions=[
                cl.Action(
                    name="continue",
                    payload={"value": "continue"},
                    label="Continue",
                ),
            ],
        ).send()


@cl.step(type="tool", name="tool_request")
async def tool_request(query: dict) -> str:
    step = cl.context.current_step
    func_name = query.get("name", "unknown")
    args = query.get("arguments", {})

    step.name = f"🛠 {func_name}"
    print("setting step parent id:", query.get("message_id"), "for step id:", step.id)
    if query.get("message_id"):
        step.parent_id = query["message_id"]
    await step.update()
    

    ts = cl.user_session.get("mcp_session")
    if not ts:
        return "MCP session not initialized."

    try:
        result = await asyncio.wait_for(ts.session.call_tool(func_name, args), timeout=MCP_TOOL_TIMEOUT)
    except asyncio.TimeoutError:
        return "MCP tool call timed out."
    except Exception as e:
        return f"MCP tool call failed: {e}"

    return str(result)

async def run_agent_turn(client, available_tools, last_message_id):
    rounds = 0
    await ask_user()
    while True:
        rounds += 1

        messages = await get_openai_history(context.session.thread_id)
        print("messages history:", messages)
        payload = {
            "messages": messages,
            "temperature": 0.7,
            "tools": available_tools,
        }
        
        msg = cl.Message(content="")
        # TODO: add reasoning step streaming
        # text, resoning, tool_calls_acc = await stream_and_collect(client=client, payload=payload, msg=msg)
        text, tool_calls_acc = await stream_and_collect(client=client, payload=payload, msg=msg)
        print("messages:", text, msg.id)
        
        if text and msg:
            last_message_id = msg.id
        if not tool_calls_acc:
            print("No tool calls detected, finishing agent turn.")
            break
        
        await ask_user()
        
        for _, acc in tool_calls_acc.items():
            raw_args = acc["function"]["arguments"]
            try:
                args_obj = json.loads(raw_args) if raw_args else {}
            except Exception:
                args_obj = {}
            
            res = await tool_request({"name": acc["function"]["name"], "arguments": args_obj, "message_id": last_message_id})
            

async def run_edit_step(step_row: Mapping[str, Any]) -> None:
    step_id = str(step_row.get("step_id"))
    step_name = step_row.get("step_name") or "tool_request"
    parent_id = step_row.get("step_parentid")
    step_input_raw = step_row.get("step_input")

    # 1) 构造要更新的 Step（注意：id/parent_id 必须是 str，避免 UUID 序列化问题）
    edited_step = cl.Step(id=step_id, name=str(step_name))
    edited_step.parent_id = str(parent_id) if parent_id else None
    edited_step.input = step_input_raw  # 可以是 str/dict；Chainlit 最终会 json 序列化，建议保持 JSON-safe
    edited_step.type = "tool"

    # 2) 获取 MCP session
    ts = cl.user_session.get("mcp_session")
    if not ts:
        edited_step.output = "MCP session not initialized."
        await edited_step.update()
        return

    # 3) 解析 tool call
    try:
        func_name, args = _extract_tool_call(step_input_raw)
    except Exception as e:
        edited_step.output = f"Invalid step input, cannot parse tool call: {e}"
        await edited_step.update()
        return

    # 4) 调用工具
    try:
        result = await asyncio.wait_for(
            ts.session.call_tool(func_name, args),
            timeout=MCP_TOOL_TIMEOUT,
        )
        # result 可能是复杂对象：这里用 str 最安全（UI 展示也友好）
        edited_step.output = str(result)
    except asyncio.TimeoutError:
        edited_step.output = "MCP tool call timed out."
    except Exception as e:
        edited_step.output = f"MCP tool call failed: {e}"

    # 5) 更新到前端/数据层
    await edited_step.update()