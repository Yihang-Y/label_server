import os
from typing import Optional
import chainlit as cl
from chainlit.data import get_data_layer
from chainlit.user import User
from chainlit.types import ThreadDict
from chainlit import Step  
import json
from dotenv import load_dotenv
from collections import defaultdict

import asyncio

load_dotenv()

import persistence  # noqa: F401
import auth         # noqa: F401

from config import SYSTEM_PROMPT
from utils.llm_api import ChatModel
from mcp_copliot_client import connect_mcp_copilot, fetch_mcp_tools
from agent import run_agent_turns, run_edit_tool_step, run_edit_cot_step
from db_utils import fetch_step

client = ChatModel(
    model_name=os.getenv("MODEL"),
    api_key=os.getenv("OPENAI_API_KEY"),
    model_url=os.getenv("BASE_URL"),
)

@cl.on_chat_start
async def start_chat():
    old_ts = cl.user_session.get("mcp_session")
    if old_ts:
        try:
            await asyncio.shield(old_ts.close())
        except Exception:
            pass
        
        
    user: Optional[User] = cl.user_session.get("user")
    if not user:
        # await cl.Message(content="Not authenticated.").send()
        user = User(
            identifier="Yihang-Y",
            metadata={
                "email": "yihangyin@hotmail.com",
                "name": "Yihang Yin",
                "role": "USER",
                "provider": "github",
                'image': 'https://avatars.githubusercontent.com/u/181572165?v=4'
            },
        )

    cl.user_session.set("profile", {
        "email": user.metadata.get("email"),
        "name": user.metadata.get("name"),
        "role": user.metadata.get("role"),
        "provider": user.metadata.get("provider"),
    })

    system_msg = Step(name="System Prompt", type="system_message")
    system_msg.output = SYSTEM_PROMPT
    await system_msg.send()

    ts = await connect_mcp_copilot()
    cl.user_session.set("mcp_session", ts)
    cl.user_session.set("mcp_tools", await fetch_mcp_tools(ts))
    

@cl.on_stop
async def on_stop():
    ts = cl.user_session.get("mcp_session")
    if not ts:
        return

    try:
        await asyncio.shield(ts.close())
    except Exception as e:
        print(f"[WARN] MCP session close failed: {e}")


thread_locks = defaultdict(asyncio.Lock)
thread_agent_tasks: dict[str, asyncio.Task] = {}

async def cancel_agent_task(thread_id: str):
    """
    取消并等待该 thread 当前运行的 agent 子任务退出。
    """
    task = thread_agent_tasks.get(thread_id)
    if task and not task.done() and task is not asyncio.current_task():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    else:
        print(f"[INFO] No running agent task for thread {thread_id} to cancel.")

@cl.on_message
async def on_message(message: cl.Message):
    thread_id = message.thread_id
    await cancel_agent_task(thread_id)
    lock = thread_locks[thread_id]
    try:
        async with lock:
            tools = cl.user_session.get("mcp_tools") or []
                    
            meta = getattr(message, "metadata", None) or {}
            edit = (meta.get("edited") if isinstance(meta, dict) else None)
            edit_step = (meta.get("edit_step") if isinstance(meta, dict) else None)
            # 需要修改历史消息
            if edit:
                if edit_step:
                    # 修改 step 内部的消息
                    step_id = meta.get("edited_step_id", "")
                    step_type = meta.get("type", "")
                    if step_id:
                        # 找到对应的 step
                        step = await fetch_step(get_data_layer(), thread_id, step_id)
                        print(step.keys())
                        assert step, f"Step {step_id} not found in thread {thread_id}"
                        if step_type == "tool":
                            if step["step_output"] == "":
                                print("Running edit tool output step...")
                                await run_edit_tool_step(step)
                            else:
                                print(f"Step {step_id} already has output, skipping tool re-execution. With {step['step_input']}")
                        elif step_type == "cot":
                            print("Running edit CoT step...")
                            # await run_edit_cot_step(step, client, tools)
                        else:
                            print(f"Unknown step type for edit: {step_type}")
                else:
                    pass
                    
            # task = asyncio.create_task(run_agent_turns(client, tools, message.id))
            thread_agent_tasks[thread_id] = asyncio.current_task()
            await run_agent_turns(client, tools, message.id)
            
    except asyncio.CancelledError:
        print(f"[INFO] Agent task for thread {thread_id} was cancelled.")
        await cancel_agent_task(thread_id)
        raise
    finally:
        if thread_agent_tasks.get(thread_id) is asyncio.current_task():
            thread_agent_tasks.pop(thread_id, None)

@cl.on_chat_resume
async def on_chat_resume(thread: ThreadDict):
    metadata = thread.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    profile = metadata.get("profile") or {}
    if profile:
        cl.user_session.set("profile", profile)
        
    ts = await connect_mcp_copilot()
    cl.user_session.set("mcp_session", ts)
    cl.user_session.set("mcp_tools", await fetch_mcp_tools(ts))
        
    await cl.context.emitter.send_toast(  
        message=f"Resumed conversation: {thread.get('name','(no name)')}",  
        type="success"  
    )

@cl.on_shared_thread_view
async def on_shared_thread_view(thread, viewer: cl.User | None):  
    """授权查看共享线程  
      
    返回 True 允许查看，返回 False 拒绝访问  
    """  
    return True
