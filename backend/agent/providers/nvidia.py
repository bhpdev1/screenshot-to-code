import os
import asyncio
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from agent.providers.base import (
    EventSink,
    ExecutedToolCall,
    ProviderSession,
    ProviderTurn,
    StreamEvent,
)
from fs_logging.agent_runs import AgentRunRecorder
from fs_logging.prompt_reports import PromptReportLogger
from llm import Llm
from config import NVIDIA_MODEL


class NvidiaProviderSession(ProviderSession):
    def __init__(
        self,
        api_key: str,
        model: Llm,
        prompt_messages: List[ChatCompletionMessageParam],
        base_url: str = "https://integrate.api.nvidia.com/v1",
        model_name: Optional[str] = None,
        recorder: Optional[AgentRunRecorder] = None,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._model_name = model_name or NVIDIA_MODEL or "meta/llama-3.2-90b-vision-instruct"
        self._prompt_messages = prompt_messages
        self._recorder = recorder
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=45.0)
        self._prompt_report_logger = PromptReportLogger(
            provider="nvidia",
            model=model,
            api_model_name=self._model_name,
        )

    async def stream_turn(self, on_event: EventSink) -> ProviderTurn:
        print(f"[NVIDIA] Sending request to {self._base_url} with model {self._model_name}...", flush=True)
        
        # Prepare messages
        formatted_messages: List[Dict[str, Any]] = []
        for msg in self._prompt_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_instruction = (
                    "You are an expert, meticulous frontend engineer specializing in cloning UI/UX designs with extreme fidelity using HTML and Tailwind CSS.\n\n"
                    "RULES:\n"
                    "1. CLONE THE ENTIRE INTERFACE: Recreate every single visual section present in the screenshot (headers, top navigation bars, search inputs, sidebars, icon menus, grids, cards, video/post listings, buttons, badges, chips).\n"
                    "2. NEVER output a simplified summary, landing page, 'welcome' screen, or placeholder card. If the screenshot is a dense app like YouTube, Twitter/X, or an admin dashboard, recreate the full layout with all cards and lists.\n"
                    "3. ACCURATE COLOR THEME: If the screenshot is DARK THEME (black or dark grey background), you MUST use a dark background (`bg-[#0f0f0f]`, `text-white`, `text-zinc-400`, `border-zinc-800`, etc.). If it is LIGHT THEME, use light colors.\n"
                    "4. ICONS & IMAGES: Include Tailwind CSS (<script src=\"https://cdn.tailwindcss.com\"></script>) and FontAwesome 6 icons (<link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css\">) in the <head>. For images/avatars/thumbnails, use realistic placeholder URLs (e.g. `https://picsum.photos/seed/1/320/180`).\n"
                    "5. RETURN ONLY CODE: Output ONLY the complete, standalone HTML document inside a ```html ... ``` block. Do not add conversational text or explanations before or after the code."
                )
                formatted_messages.append({"role": "system", "content": system_instruction})
            elif role == "user":
                if isinstance(content, list):
                    cleaned_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            cleaned_parts.append({
                                "type": "text",
                                "text": (
                                    "Reproduce this user interface from the screenshot with 100% visual fidelity in a single-file HTML page using Tailwind CSS.\n"
                                    "Recreate every navigation bar, sidebar, grid item, video/content card, search bar, and badge.\n"
                                    "Respect the exact color palette (dark mode if the screenshot is dark) and typography.\n"
                                    "Do NOT generate a generic welcome page or a simple card. Output the full UI code."
                                )
                            })
                        else:
                            cleaned_parts.append(part)
                    formatted_messages.append({"role": "user", "content": cleaned_parts})
                else:
                    formatted_messages.append({"role": role, "content": content})

        current_model = self._model_name
        request_params: Dict[str, Any] = {
            "model": current_model,
            "messages": formatted_messages,
            "stream": True,
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        self._prompt_report_logger.record_request(request_params)
        if self._recorder is not None:
            self._recorder.record_llm_request("nvidia", current_model, request_params)

        accumulated_text = ""
        stream = None

        try:
            print(f"[NVIDIA] Connecting to stream with model {current_model}...", flush=True)
            stream = await asyncio.wait_for(
                self._client.chat.completions.create(**request_params),
                timeout=35.0,
            )
        except (asyncio.TimeoutError, Exception) as e:
            if current_model != "meta/llama-3.2-11b-vision-instruct":
                print(f"[NVIDIA] Model {current_model} timed out/failed ({e}). Falling back immediately to meta/llama-3.2-11b-vision-instruct...", flush=True)
                current_model = "meta/llama-3.2-11b-vision-instruct"
                request_params["model"] = current_model
                stream = await asyncio.wait_for(
                    self._client.chat.completions.create(**request_params),
                    timeout=45.0,
                )
            else:
                raise

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = delta.content or ""
            if content:
                accumulated_text += content
                await on_event(StreamEvent(type="assistant_delta", text=content))

        turn = ProviderTurn(
            assistant_text=accumulated_text,
            tool_calls=[],
            assistant_turn=None,
        )

        if self._recorder is not None:
            self._recorder.record_llm_response(
                turn.assistant_text, turn.tool_calls, None
            )

        return turn

    async def append_tool_results(
        self,
        turn: ProviderTurn,
        executed_tool_calls: list[ExecutedToolCall],
    ) -> None:
        pass

    def total_cost_usd(self) -> Optional[float]:
        return 0.0

    async def close(self) -> None:
        await self._client.close()
