import chainlit as cl
import uuid
import re
import json
from typing import Any, AsyncIterator, Dict, Tuple, Optional, List


def _get(obj: Any, key: str, default=None):
    """兼容 attr / dict 的读取"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _ensure_tool_acc(tool_calls_acc: Dict[int, Dict[str, Any]], idx: int, tc_id: str):
    if idx not in tool_calls_acc:
        tool_calls_acc[idx] = {
            "id": tc_id,
            "type": "function",
            "function": {"name": "", "arguments": ""},
        }
    return tool_calls_acc[idx]

def _normalize_tool_calls(tool_calls: Any):
    """
    Normalize tool_calls into {index: {id, type, function:{name, arguments}}}
    Compatible with common OpenAI-like shapes.
    """
    if not tool_calls:
        return {}

    # tool_calls might be list[dict] or list[obj]
    out: Dict = {}

    for i, tc in enumerate(tool_calls):
        idx = _get(tc, "index", None)
        if idx is None:
            idx = i

        tc_id = _get(tc, "id", None)
        tc_type = _get(tc, "type", None) or "function"

        fn = _get(tc, "function", None) or {}
        fn_name = _get(fn, "name", None) or ""
        fn_args = _get(fn, "arguments", None) or ""

        out[int(idx)] = {
            "id": tc_id,
            "type": tc_type,
            "function": {
                "name": fn_name,
                "arguments": fn_args,
            },
        }

    return out

TOOL_CALL_JSON_RE = re.compile(
    r"""
    \{
        \s*"name"\s*:\s*"(?P<name>[^"]+)"\s*,
        \s*"arguments"\s*:\s*(?P<args>\{.*?\})
    \s*\}
    """,
    re.VERBOSE | re.DOTALL,
)

def _try_parse_tool_calls_from_content(content: str) -> List[Dict[str, Any]]:
    """
    尝试从 content 文本中提取 tool call（JSON 形式）
    返回标准 tool_calls list；失败则返回 []
    """
    if not content:
        return []

    # 1) 直接尝试整体 JSON
    try:
        obj = json.loads(content)
        if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
            return [{
                "type": "function",
                "function": {
                    "name": obj["name"],
                    "arguments": obj["arguments"],
                },
            }]
    except Exception:
        pass

    # 2) 正则提取嵌入式 JSON（最常见）
    matches = TOOL_CALL_JSON_RE.finditer(content)
    calls = []

    for m in matches:
        try:
            args = json.loads(m.group("args"))
        except Exception:
            continue

        calls.append({
            "type": "function",
            "function": {
                "name": m.group("name"),
                "arguments": args,
            },
        })

    return calls


async def stream_and_yield_events(
    *,
    client: Any,
    payload: Dict[str, Any],
) -> AsyncIterator[Dict[str, Any]]:
    """
    事件类型：
      - {"type": "content_delta", "delta": str}
      - {"type": "reasoning_delta", "delta": str}
      - {"type": "tool_calls_partial", "tool_calls": Dict[int, {...}]}
      - {"type": "done", "content": str, "reasoning": str, "tool_calls": Dict[int, {...}]}

    注意：这个函数不直接操作 cl.Message/Step（更通用），调用方决定怎么显示/落盘。
    """

    tool_calls_accumulator: Dict[int, Dict[str, Any]] = {}
    content_acc: str = ""
    reasoning_acc: str = ""

    async for part in client.stream_completions(**payload):
        # 兼容 openai-like 响应结构
        choices = _get(part, "choices", [])
        if not choices:
            continue
        delta = _get(choices[0], "delta", None)
        if delta is None:
            continue

        # 1) 普通内容 token
        token = _get(delta, "content", "") or ""
        if token:
            content_acc += token
            yield {"type": "content_delta", "delta": token}

        # 2) reasoning token（不同模型字段可能叫 reasoning / reasoning_content 等）
        # 你这里原来用 getattr(delta, "reasoning", None)，我保留并做一点兼容
        reasoning = _get(delta, "reasoning", None)
        if reasoning is None:
            reasoning = _get(delta, "reasoning_content", "")  # 可选兼容
        reasoning = reasoning or ""
        if reasoning:
            reasoning_acc += reasoning
            yield {"type": "reasoning_delta", "delta": reasoning}

        # 3) tool_calls 增量
        tool_calls_delta = _get(delta, "tool_calls", None)
        if not tool_calls_delta:
            continue

        updated = False
        for tc in tool_calls_delta:
            idx = _get(tc, "index", None)
            if idx is None:
                idx = _get(tc, "index", 0)  # dict fallback
            idx = idx or 0

            tc_id = _get(tc, "id", None) or str(uuid.uuid4())

            acc = _ensure_tool_acc(tool_calls_accumulator, idx, tc_id)

            fn = _get(tc, "function", None)
            if fn is None and isinstance(tc, dict):
                fn = tc.get("function") or {}

            fn_name = _get(fn, "name", None)
            fn_args = _get(fn, "arguments", None)

            if fn_name:
                acc["function"]["name"] = fn_name
                updated = True
            if fn_args:
                # arguments 是增量拼接
                acc["function"]["arguments"] += fn_args
                updated = True

        if updated:
            # 把当前快照 yield 出去，调用方可在此决定“开始执行工具”
            yield {"type": "tool_calls_partial", "tool_calls": tool_calls_accumulator}

    if content_acc and not tool_calls_accumulator:
        # 如果最终没有 tool_calls，则尝试从 content 中恢复
        recovered = _try_parse_tool_calls_from_content(content_acc)
        if recovered:
            tool_calls_accumulator = _normalize_tool_calls(recovered)
            content_acc = ""  

    # streaming 结束
    yield {
        "type": "done",
        "content": content_acc,
        "reasoning": reasoning_acc,
        "tool_calls": tool_calls_accumulator,
    }
    
async def request(client: Any, payload: Dict[str, Any]) -> str:
    response = await client.client_completions(**payload)

    choices = _get(response, "choices", []) or []
    if not choices:
        return {"content": "", "reasoning": "", "tool_calls": {}}

    msg = _get(choices[0], "message", None) or {}

    content = _get(msg, "content", "") or ""
    # reasoning 字段兼容：reasoning / reasoning_content
    reasoning = _get(msg, "reasoning", None)
    if reasoning is None:
        reasoning = _get(msg, "reasoning_content", "") or ""
    reasoning = reasoning or ""

    tool_calls =_normalize_tool_calls(_get(msg, "tool_calls", None))
    if not tool_calls and content:
        recovered = _try_parse_tool_calls_from_content(content)
        if recovered:
            tool_calls = recovered
            content = ""

    return content, reasoning, tool_calls
    
async def summarize_reasoning(client: Any, reasoning: str) -> str:
    prompt = f"Summarize the following reasoning into a concise plan:\n\n{reasoning}\n\nPlan:"
    messages = [
        {"role": "system", "content": "You are a helpful assistant that summarizes reasoning."},
        {"role": "user", "content": prompt},
    ]
    
    try:
        response = await client.client_completions(
            messages=messages,
            temperature=0.5,
            max_tokens=10000,
        )
        summary = response.choices[0].message.content.strip()
        
        if summary == "":
            summary = "No plan could be summarized."
        return summary
    
    except Exception as e:
        print(f"[ERROR] Summarize reasoning failed: {e}")
        return "Error in summarizing reasoning: " + str(e)
