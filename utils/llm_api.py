import logging
from openai import OpenAI, AsyncOpenAI
from functools import partial
from backoff import on_exception, expo
import os

logger = logging.getLogger(__name__)


class ChatModel:
    def __init__(
        self,
        model_name=None,
        model_url=None,
        api_key=None,
        temperature=0.7,
        max_new_tokens=4096,
    ):
        self.model_name = model_name
        self.model_url = model_url
        self.temperature = temperature
        self.max_new_tokens = max_new_tokens
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=model_url,
        )
        self.extra_body = {}
        self.chat = partial(
            self.client.chat.completions.create,
            model=model_name,
            temperature=temperature,
            max_completion_tokens=max_new_tokens,
            extra_body=self.extra_body,
        )
    async def stream_completions(self, **args):
        try:
            stream = await self.chat(stream=True, **args)
            async for part in stream:
                yield part
        except Exception as e:
            logger.error(f"Stream completion failed: {e}")
            raise e
        
    async def client_completions(self, **args):
        try:
            return await self.chat(**args)
        except Exception as e:
            logger.error(f"Client completion failed: {e}")
            raise

    async def list_models(self):
        models = await self.client.models.list()
        return [m.id for m in models.data]