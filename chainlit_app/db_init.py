import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DB_CONNINFO = "postgresql+asyncpg://chainlit:chainlit@localhost:5432/chainlit"


async def init_database():
    engine = create_async_engine(DB_CONNINFO)

    async with engine.begin() as conn:
        # users
        await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            "id" UUID PRIMARY KEY,
            "identifier" TEXT NOT NULL UNIQUE,
            "metadata" JSONB NOT NULL,
            "createdAt" TEXT
        );
        """))

        # threads
        await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS threads (
            "id" UUID PRIMARY KEY,
            "createdAt" TEXT,
            "name" TEXT,
            "userId" UUID,
            "userIdentifier" TEXT,
            "tags" TEXT[],
            "metadata" JSONB,
            FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
        );
        """))

        # steps（⚠️ 已对齐当前 Chainlit）
        await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS steps (
            "id" UUID PRIMARY KEY,
            "name" TEXT NOT NULL,
            "type" TEXT NOT NULL,
            "threadId" UUID NOT NULL,
            "parentId" UUID,

            "streaming" BOOLEAN NOT NULL,
            "waitForAnswer" BOOLEAN,
            "isError" BOOLEAN,

            "disableFeedback" BOOLEAN DEFAULT false,

            "metadata" JSONB,
            "tags" TEXT[],
            "input" TEXT,
            "output" TEXT,
            "createdAt" TEXT,
            "command" TEXT,
            "start" TEXT,
            "end" TEXT,
            "generation" JSONB,
            "showInput" TEXT,
            "language" TEXT,
            "indent" INT,
            "defaultOpen" BOOLEAN DEFAULT false,

            FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
        );
        """))

        # elements
        await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS elements (
            "id" UUID PRIMARY KEY,
            "threadId" UUID,
            "type" TEXT,
            "url" TEXT,
            "chainlitKey" TEXT,
            "name" TEXT NOT NULL,
            "display" TEXT,
            "objectKey" TEXT,
            "size" TEXT,
            "page" INT,
            "language" TEXT,
            "forId" UUID,
            "mime" TEXT,
            "props" JSONB,
            FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
        );
        """))

        # feedbacks
        await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS feedbacks (
            "id" UUID PRIMARY KEY,
            "forId" UUID NOT NULL,
            "threadId" UUID NOT NULL,
            "value" INT NOT NULL,
            "comment" TEXT,
            FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
        );
        """))

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(init_database())
