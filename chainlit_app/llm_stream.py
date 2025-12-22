import uuid
from typing import Any, Dict, Tuple
import chainlit as cl

async def stream_and_collect(
    *,
    client: Any,
    payload: Dict[str, Any],
    msg: cl.Message,
) -> Tuple[str, Dict[int, Dict[str, Any]]]:
    tool_calls_accumulator: Dict[int, Dict[str, Any]] = {}
    
    # TODO: add reasoning step streaming
    # reasoning_step = cl.Step(  
    #     name="reasoning",  
    #     type="cot",  
    #     parent_id=msg.id  
    # )  
    await msg.send() 
    # await reasoning_step.send()  
    async for part in client.stream_completions(**payload):
        delta = part.choices[0].delta

        token = delta.content or ""
        if token:
            await msg.stream_token(token)
            
        # reasoning = getattr(delta, "reasoning", None) or ""
        # if reasoning:
        #     await reasoning_step.stream_token(reasoning)  

        tool_calls_delta = delta.tool_calls or None
        if not tool_calls_delta:
            continue

        for tc in tool_calls_delta:
            idx = getattr(tc, "index", None) or (tc.get("index") if isinstance(tc, dict) else None) or 0
            tc_id = getattr(tc, "id", None) or (tc.get("id") if isinstance(tc, dict) else None) or str(uuid.uuid4())

            if idx not in tool_calls_accumulator:
                tool_calls_accumulator[idx] = {
                    "id": tc_id,
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                }

            acc = tool_calls_accumulator[idx]

            fn = getattr(tc, "function", None)
            if fn is None and isinstance(tc, dict):
                fn = tc.get("function") or {}

            fn_name = getattr(fn, "name", None) if not isinstance(fn, dict) else fn.get("name")
            fn_args = getattr(fn, "arguments", None) if not isinstance(fn, dict) else fn.get("arguments")

            if fn_name:
                acc["function"]["name"] = fn_name
            if fn_args:
                acc["function"]["arguments"] += fn_args

    # if reasoning_step.output:
    #     await reasoning_step.update()  
    if msg.content:
        await msg.update()
    # return msg.content, reasoning_step.output, tool_calls_accumulator
    return msg.content, tool_calls_accumulator