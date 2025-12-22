from sqlalchemy import text
from config import DB_CONNINFO

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
    

async def get_openai_history(thread_id: str) -> list[dict]:  
    data_layer = SQLAlchemyDataLayer(conninfo=DB_CONNINFO)  
    thread = await data_layer.get_thread(thread_id)  
      
    def flatten_messages(steps, cot_settings=None):
        
        # sort steps by createdAt to maintain order 
        steps = sorted([s for s in steps if s.get("createdAt")], key=lambda x: x["createdAt"])

        messages = []  
        for step in steps:  
            # 模拟前端的 Chainlit run 处理  
            if step.get("name") in ["on_chat_start", "on_message", "on_audio_end"]:  
                # 递归处理子步骤  
                if step.get("steps"):  
                    messages.extend(flatten_messages(step["steps"], cot_settings))  
                continue  
              
            # 模拟前端的 CoT 过滤  
            if cot_settings == "hidden" and not step.get("type", "").endswith("_message"):  
                continue  
              
            # 处理消息类型  
            step_type = step.get("type")  
            if step_type in ["system_message", "user_message", "assistant_message"]:  
                output_content = step.get("output", "")
                if step_type == "assistant_message" and output_content == '**Selected:** Continue':
                    continue
                messages.append({  
                    "role": step_type.replace("_message", ""),   
                    "content": output_content  
                })  
            elif step_type == "tool":  
                input_content = step.get("input", "")  
                output_content = step.get("output", "")  
                messages.append({"role": "assistant", "content": input_content})  
                messages.append({"role": "tool", "content": output_content})  
              
            # 递归处理子步骤  
            if step.get("steps"):  
                messages.extend(flatten_messages(step["steps"], cot_settings))  
          
        return messages  
      
    return flatten_messages(thread.get("steps", []))