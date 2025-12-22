import os

SYSTEM_PROMPT = "You are a helpful assistant. When calling any tool, briefly explain in one short sentence why the tool is being used and what it will do."

MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "180"))
MCP_TOOL_TIMEOUT = int(os.getenv("MCP_TOOL_TIMEOUT", "300"))

DB_CONNINFO = os.getenv("CHAINLIT_DB", "postgresql+asyncpg://chainlit:chainlit@localhost:5432/chainlit")

# ALLOWED_EMAILS = {
#     e.strip().lower()
#     for e in os.getenv("ALLOWED_EMAILS", "").split(",")
#     if e.strip()
# }

ALLOWED_EMAILS = {
    "yihangyin@hotmail.com"
}

ALLOWED_DOMAINS = {
    d.strip().lower().lstrip("@")
    for d in os.getenv("ALLOWED_DOMAINS", "").split(",")
    if d.strip()
}
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

CHAINLIT_AUTH_SECRET="umci/%XrgHheA=I.jXk2:.6*P^chked.u0@i6MRY:9GTn8^x44=L/txhE,nxIZ*O"
