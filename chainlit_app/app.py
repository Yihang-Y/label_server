import os
from typing import Optional
import chainlit as cl
from chainlit.user import User
from chainlit.types import ThreadDict
from chainlit import Step  
import json
from dotenv import load_dotenv

import asyncio

load_dotenv()

import persistence  # noqa: F401
import auth         # noqa: F401

from config import SYSTEM_PROMPT
from utils.llm_api import ChatModel
from mcp_copliot_client import connect_mcp_copilot, fetch_mcp_tools
from agent import run_agent_turn, run_edit_step
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
        # 防止在 cancel 状态下直接中断 close
        await asyncio.shield(ts.close())
    except Exception as e:
        # 不要让异常冒泡到 event loop 关闭阶段
        print(f"[WARN] MCP session close failed: {e}")

@cl.on_message
async def on_message(message: cl.Message):
    
    tools = cl.user_session.get("mcp_tools") or []
    
    meta = getattr(message, "metadata", None) or {}
    edit = (meta.get("edited") if isinstance(meta, dict) else None)
    edit_step = (meta.get("edit_step") if isinstance(meta, dict) else None)
    # 需要修改历史消息
    if edit:
        if edit_step:
            # 修改 step 内部的消息
            step_id = meta.get("edited_step_id", "")
            if step_id:
                # 找到对应的 step
                step = await fetch_step(message.thread_id, step_id)
                assert step, f"Step {step_id} not found in thread {message.thread_id}"
                if step["step_output"] == "":
                    # 重新调用工具生成 output之后更新 step
                    await run_edit_step(step)
        else:
            # 修改的是 message 消息
            pass
            
    await run_agent_turn(client, tools, message.id)


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
        
    await cl.context.emitter.send_toast(  
        message=f"Resumed conversation: {thread.get('name','(no name)')}",  
        type="success"  
    )

