import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, BaseMessage
from app.config import settings
from app.core.skills import skill_registry
from app.core.mcp_client import mcp_manager

logger = logging.getLogger("maxi.agent")


class MaxiAgent:
    """Agent loop using OpenAI-compatible endpoints with dynamic skills, MCP tools, and 5-turn sliding context."""

    def __init__(self):
        self.settings = settings
        self._history: List[BaseMessage] = []
        self._max_history_turns: int = 5  # Keeps past 5 conversation pairs (10 messages max)

    def get_history(self) -> List[BaseMessage]:
        """Returns the past conversation messages (up to 5 turns)."""
        return list(self._history)

    def append_turn(self, prompt: str, output: str):
        """Saves a turn to short-term session history, keeping the last 5 turns."""
        if not prompt or not output:
            return
        self._history.append(HumanMessage(content=prompt))
        self._history.append(AIMessage(content=output))
        max_messages = self._max_history_turns * 2
        if len(self._history) > max_messages:
            self._history = self._history[-max_messages:]

    def clear_history(self):
        """Clears short-term conversational session history."""
        self._history.clear()
        logger.info("Cleared short-term conversational history buffer.")

    def _get_llm(self, streaming: bool = False) -> ChatOpenAI:
        return ChatOpenAI(
            base_url=self.settings.openai_base_url,
            api_key=self.settings.openai_api_key or "sk-dummy-key",
            model=self.settings.openai_model,
            streaming=streaming,
            temperature=0.3,
        )

    def _format_tool_output(self, output: Any) -> str:
        """Normalizes MCP tool outputs (strings, content blocks, lists, dicts) into clean text."""
        if isinstance(output, str):
            return output
        if isinstance(output, list):
            texts = []
            for item in output:
                if isinstance(item, dict) and "text" in item:
                    texts.append(str(item["text"]))
                else:
                    texts.append(str(item))
            return "\n".join(texts)
        if isinstance(output, dict):
            if "text" in output:
                return str(output["text"])
            return json.dumps(output, ensure_ascii=False)
        return str(output)

    def _build_system_prompt(self, prompt: str = "", source: str = "text") -> str:
        """Injects only the base persona and relevant markdown skills for this prompt."""
        base_prompt = self.settings.system_prompt
        skills_prompt = skill_registry.compile_instructions_for_prompt(prompt, source=source)
        if skills_prompt:
            return f"{base_prompt}\n\n## Dynamically Loaded Skills\n{skills_prompt}"
        return base_prompt

    def _record_turn(self, source: str, prompt: str, output: str, tools_used: List[str], status: str):
        try:
            history_path = self.settings.get_history_file()
            history_path.parent.mkdir(parents=True, exist_ok=True)
            
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "model": self.settings.openai_model,
                "prompt": prompt,
                "output": output,
                "tools_used": tools_used,
                "status": status,
            }
            with open(history_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to record turn to history log: {e}")

    async def run(self, prompt: str, source: str = "text") -> Dict[str, Any]:
        """Execute prompt against OpenAI-compatible endpoint with MCP tool execution and 5-turn history."""
        # Check for explicit session reset request
        clean_prompt = prompt.strip().lower()
        if clean_prompt in ("reset context", "reset conversation", "clear context", "clear history", "new topic", "new session"):
            self.clear_history()
            return {
                "source": source,
                "model": self.settings.openai_model,
                "endpoint": self.settings.openai_base_url,
                "input": prompt,
                "output": "Conversation context cleared. Starting fresh.",
                "tools_used": [],
                "status": "success"
            }

        await mcp_manager.ensure_connected()
        system_instruction = self._build_system_prompt(prompt=prompt, source=source)
        tools = mcp_manager.get_tools()
        tool_map = {t.name: t for t in tools}

        logger.info(f"Dispatching [{source}] prompt to {self.settings.openai_model} @ {self.settings.openai_base_url} ({len(tools)} tools loaded, {len(self._history)//2} turns in memory)")

        messages: List[BaseMessage] = [
            SystemMessage(content=system_instruction),
            *self.get_history(),
            HumanMessage(content=prompt)
        ]

        executed_tools: List[str] = []
        max_turns = 5
        output_text = ""

        try:
            llm = self._get_llm(streaming=False)
            if tools:
                llm = llm.bind_tools(tools)

            for turn in range(max_turns):
                response = await llm.ainvoke(messages)
                messages.append(response)

                tool_calls = getattr(response, "tool_calls", [])
                if not tool_calls:
                    output_text = response.content if isinstance(response.content, str) else str(response.content)
                    break

                for call in tool_calls:
                    call_name = call.get("name")
                    call_args = call.get("args", {})
                    call_id = call.get("id") or f"call_{call_name}"

                    logger.info(f"Turn {turn + 1}: Executing tool '{call_name}' with args {call_args}")
                    executed_tools.append(call_name)

                    tool = tool_map.get(call_name)
                    if tool:
                        try:
                            if hasattr(tool, "ainvoke"):
                                raw_res = await tool.ainvoke(call_args)
                            else:
                                raw_res = tool.invoke(call_args)
                            tool_result = self._format_tool_output(raw_res)
                        except Exception as e:
                            logger.error(f"Error executing '{call_name}': {e}")
                            tool_result = f"Error executing tool '{call_name}': {str(e)}"
                    else:
                        tool_result = f"Tool '{call_name}' not found."

                    messages.append(ToolMessage(
                        content=tool_result,
                        tool_call_id=call_id
                    ))
            else:
                last_msg = messages[-1]
                output_text = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)

            # Fallback confirmation if tools executed but no text returned
            if not output_text.strip() and executed_tools:
                output_text = f"Executed {', '.join(executed_tools)} successfully."

            # Persist to short-term sliding history
            if output_text.strip():
                self.append_turn(prompt, output_text)

            self._record_turn(
                source=source,
                prompt=prompt,
                output=output_text,
                tools_used=executed_tools,
                status="success"
            )

            return {
                "source": source,
                "model": self.settings.openai_model,
                "endpoint": self.settings.openai_base_url,
                "input": prompt,
                "output": output_text,
                "tools_used": executed_tools,
                "status": "success"
            }
        except Exception as e:
            err_msg = f"LLM Endpoint Error: {str(e)}"
            logger.error(f"Error communicating with LLM endpoint ({self.settings.openai_base_url}): {e}")
            self._record_turn(
                source=source,
                prompt=prompt,
                output=err_msg,
                tools_used=executed_tools,
                status="error"
            )
            return {
                "source": source,
                "model": self.settings.openai_model,
                "input": prompt,
                "output": err_msg,
                "tools_used": executed_tools,
                "status": "error"
            }

    async def run_stream(self, prompt: str, source: str = "text") -> AsyncGenerator[str, None]:
        """Stream token-by-token response over WebSockets, executing tool calls when requested."""
        await mcp_manager.ensure_connected()
        system_instruction = self._build_system_prompt(prompt=prompt, source=source)
        tools = mcp_manager.get_tools()
        tool_map = {t.name: t for t in tools}

        messages: List[BaseMessage] = [
            SystemMessage(content=system_instruction),
            *self.get_history(),
            HumanMessage(content=prompt)
        ]

        full_output: List[str] = []
        executed_tools: List[str] = []
        max_turns = 5

        try:
            llm = self._get_llm(streaming=False)
            if tools:
                llm = llm.bind_tools(tools)

            for turn in range(max_turns):
                response = await llm.ainvoke(messages)
                messages.append(response)

                tool_calls = getattr(response, "tool_calls", [])
                if not tool_calls:
                    text_chunk = response.content if isinstance(response.content, str) else str(response.content)
                    if text_chunk:
                        full_output.append(text_chunk)
                        yield text_chunk
                    break

                for call in tool_calls:
                    call_name = call.get("name")
                    call_args = call.get("args", {})
                    call_id = call.get("id") or f"call_{call_name}"

                    logger.info(f"Stream turn {turn + 1}: Executing tool '{call_name}' with args {call_args}")
                    executed_tools.append(call_name)

                    tool = tool_map.get(call_name)
                    if tool:
                        try:
                            if hasattr(tool, "ainvoke"):
                                raw_res = await tool.ainvoke(call_args)
                            else:
                                raw_res = tool.invoke(call_args)
                            tool_result = self._format_tool_output(raw_res)
                        except Exception as e:
                            logger.error(f"Error executing '{call_name}': {e}")
                            tool_result = f"Error executing tool '{call_name}': {str(e)}"
                    else:
                        tool_result = f"Tool '{call_name}' not found."

                    messages.append(ToolMessage(
                        content=tool_result,
                        tool_call_id=call_id
                    ))
            else:
                last_msg = messages[-1]
                text_chunk = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
                if text_chunk:
                    full_output.append(text_chunk)
                    yield text_chunk

            final_text = "".join(full_output).strip()
            if not final_text and executed_tools:
                fallback = f"Executed {', '.join(executed_tools)} successfully."
                full_output.append(fallback)
                yield fallback
                final_text = fallback

            if final_text:
                self.append_turn(prompt, final_text)

            self._record_turn(
                source=source,
                prompt=prompt,
                output="".join(full_output),
                tools_used=executed_tools,
                status="success"
            )
        except Exception as e:
            err_chunk = f"\n[Error streaming from {self.settings.openai_base_url}: {str(e)}]"
            logger.error(f"Streaming error from {self.settings.openai_base_url}: {e}")
            yield err_chunk
            self._record_turn(
                source=source,
                prompt=prompt,
                output="".join(full_output) + err_chunk,
                tools_used=executed_tools,
                status="error"
            )


agent = MaxiAgent()

