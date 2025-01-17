from typing import Any, Dict, Iterator, List, Optional

from langchain_core.callbacks import (
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
)
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field
from ..fast_model import FastAutoModel

class LangChainFastLLM(BaseChatModel):
    model_name: str
    model_llm:FastAutoModel=None
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del kwargs["model_name"]
        kwargs_model=kwargs
        self.model_llm=FastAutoModel(model_name=self.model_name,**kwargs_model)
       
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        max_new_tokens=1024,
        **kwargs: Any,
    ) -> ChatResult:
        
        tokens = self.model_llm.generate(messages,history_save=False,max_new_tokens=max_new_tokens)
        ct_input_tokens = sum(len(message.content) for message in messages)
        ct_output_tokens = len(tokens)
        message = AIMessage(
            content=tokens,
            additional_kwargs={},
            response_metadata={
                "time_in_seconds": 3,
            },
            usage_metadata={
                "input_tokens": ct_input_tokens,
                "output_tokens": ct_output_tokens,
                "total_tokens": ct_input_tokens + ct_output_tokens,
            },
        )

        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        max_new_tokens=1024,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        ct_input_tokens = sum(len(message.content) for message in messages)

        for token in self.model_llm.generate(messages,stream=True,history_save=False,max_new_tokens=max_new_tokens):
            usage_metadata = UsageMetadata(
                {
                    "input_tokens": ct_input_tokens,
                    "output_tokens": 1,
                    "total_tokens": ct_input_tokens + 1,
                }
            )
            ct_input_tokens = 0
            chunk = ChatGenerationChunk(
                message=AIMessageChunk(content=token, usage_metadata=usage_metadata)
            )

            if run_manager:
                run_manager.on_llm_new_token(token, chunk=chunk)

            yield chunk

        chunk = ChatGenerationChunk(
            message=AIMessageChunk(content="", response_metadata={"time_in_sec": 3})
        )
        if run_manager:
            run_manager.on_llm_new_token(token, chunk=chunk)
        yield chunk

    @property
    def _llm_type(self) -> str:
        return "echoing-chat-model-advanced"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
        }
