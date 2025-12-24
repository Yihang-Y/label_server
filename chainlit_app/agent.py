import asyncio
import json
import chainlit as cl
from chainlit.context import context  

from config import MCP_TOOL_TIMEOUT
from llm_stream import stream_and_yield_events, summarize_reasoning, request
from typing import Any, Mapping, Optional, Dict
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


async def ask_user():
    print("Asking user to continue...")
    try:
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
        print(f"User action: {action}")
    except Exception as e:
        print(f"User action failed: {e}")
        return


async def tool_request(query: dict) -> str:
    func_name = query.get("name", "unknown")
    args = query.get("arguments", {})
    parent_step_id = query.get("parent_step_id")

    step = cl.Step(name=f"🛠 {func_name}", type="tool")
    if parent_step_id:
        step.parent_id = parent_step_id

    step.input = {
        "name": func_name,
        "arguments": args,
    }
    await step.send()

    ts = cl.user_session.get("mcp_session")
    if not ts:
        step.output = "MCP session not initialized."
        await step.update()
        return step.output

    try:
        result = await asyncio.wait_for(
            ts.session.call_tool(func_name, args),
            timeout=MCP_TOOL_TIMEOUT
        )
        step.output = str(result)
        await step.update()
        return step.output

    except asyncio.TimeoutError:
        step.output = "MCP tool call timed out."
        await step.update()
        return step.output

    except Exception as e:
        step.output = f"MCP tool call failed: {e}"
        await step.update()
        return step.output


async def run_agent_turn(client: Any, payload: Dict[str, Any]):
    print("[INFO] Running agent turn with payload:", payload["messages"])
    content, reasoning, tool_calls = await request(client, payload)
    
    if content == "" and reasoning == "" and not tool_calls:
        print("[WARN] Empty response from agent.")
        return
    else:
        print("[INFO] content:", content)
        print("[INFO] reasoning:", reasoning)
        print("[INFO] tool_calls:", tool_calls)
    
    if reasoning:
        print("Agent Reasoning not used:", reasoning)
    if len(tool_calls) > 0:
        for tc in tool_calls.values():
            tool_request_payload = {
                "name": tc["function"]["name"],
                "arguments": json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {},
            }
            tool_result = await tool_request(tool_request_payload)
            return
    if content:
        msg = cl.Message(content="")
        msg.content = content
        await msg.send()
    


async def run_agent_turn_with_steps_streaming(client: Any, payload: Dict[str, Any]):
    async with cl.Step(name="Agent Turn", type="run") as turn_step:        
        reasoning_step = cl.Step(name="Reasoning", type="cot")
        reasoning_step.parent_id = turn_step.id
        await reasoning_step.send()
        
        async for ev in stream_and_yield_events(client=client, payload=payload):
            if ev["type"] == "reasoning_delta":
                await reasoning_step.stream_token(ev["delta"])
            elif ev["type"] == "done":
                if ev["content"]:
                    msg = cl.Message(content="")
                    msg.content = ev["content"]
                    await reasoning_step.update()
                    await msg.send()
                    break
                
                reasoning = ev.get("reasoning") or ""
                if reasoning:
                    print("[INFO] Final reasoning:", reasoning)
                    reasoning_step.output = reasoning
                    await reasoning_step.update()
                    
                    summary_plan = await summarize_reasoning(client=client, reasoning=reasoning)
                    reasoning_step.input = f"{str(summary_plan)}"
                    print("[INFO] Final summarized plan:", summary_plan)           
                    await reasoning_step.update()
                
                tool_calls = ev.get("tool_calls") or {}
                if tool_calls:
                    for tc in tool_calls.values():
                        tool_request_payload = {
                            "name": tc["function"]["name"],
                            "arguments": json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {},
                            "parent_step_id": turn_step.id,
                        }
                        tool_result = await tool_request(tool_request_payload)
                        

async def run_agent_turns(client, available_tools, last_message_id):
    rounds = 0
    try:
        while True:
            rounds += 1

            messages = await get_openai_history(context.session.thread_id)
            # print("messages history:", messages)
            payload = {
                "messages": messages,
                "temperature": 0.7,
                "tools": available_tools,
            }
            print("running agent turn with payload")
            await ask_user()
            await run_agent_turn_with_steps_streaming(client, payload)
    except asyncio.CancelledError:
        print(f"[INFO] Agent turns cancelled after {rounds} rounds.")
        raise
            

async def run_edit_tool_step(step_row: Mapping[str, Any]) -> None:
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
        print("parse tool call from step input:", step_input_raw)
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
    
    
async def run_edit_cot_step(step_row: Mapping[str, Any], client: Any, available_tools) -> None:
    step_id = str(step_row.get("step_id"))
    step_name = step_row.get("step_name") or "tool_request"
    parent_id = step_row.get("step_parentid")
    step_input_raw = step_row.get("step_input")
    
    # 1) generate new Step
    edited_step = cl.Step(id=step_id, name=str(step_name))
    edited_step.parent_id = str(parent_id) if parent_id else None
    edited_step.type = "cot"
    
    # 2) generate new summary plan
    try:
        reasoning = step_row.get("step_output") or ""
        summary_plan = await summarize_reasoning(client=client, reasoning=reasoning)
        print("[INFO] Edited summarized plan:", summary_plan)
        edited_step.input = f"{str(summary_plan)}"
        edited_step.output = reasoning
    except Exception as e:
        edited_step.output = f"Failed to summarize reasoning: {e}"
            
    await edited_step.update()

    # 3) generate tool calls or content
    messages = await get_openai_history(context.session.thread_id, compressed=True)
    system_prompt = """You are an agent running inside an interactive app with editable intermediate steps.

IMPORTANT CONTEXT:
- The user has edited a previous "Reasoning / CoT" step. After this edit, any downstream steps that depended on the old CoT may be invalid.
- You MUST treat the updated conversation history (the provided messages) as the single source of truth.
- If tool use is available, you may call tools when it meaningfully improves correctness, completeness, or safety.
- When you decide to call a tool, you MUST use structured tool calling (tool_calls). Do NOT describe tool calls in plain text.
- If no tool is needed, respond with normal assistant text.

GOAL:
Given the updated history, determine the best next action:
1) Call one tool, OR
2) Produce a user-facing response.

OUTPUT RULES:
- If calling tools: produce only valid tool_calls and no tool-call JSON in the assistant content.
- If not calling tools: produce only normal assistant content suitable for the end user.
- Keep outputs concise and aligned with the user's latest intent.
"""
    user_prompt = f"""Based on the updated conversation history, determine the next best action.
Here is the updated conversation history:
{json.dumps(messages, indent=2)}
Please either call a tool using structured tool_calls, or provide a user-facing response."""
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "tools": available_tools,
    }
    await run_agent_turn(client, payload)
    
    
    
    