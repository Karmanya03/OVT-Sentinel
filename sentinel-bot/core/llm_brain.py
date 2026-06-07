import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from config import Settings
from core.cache import cached
from core.memory import SessionMemory

log = logging.getLogger("sentinel.llm")

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system_prompt.txt"
OVT_REFERENCE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "ovt_reference.txt"

TOOL_SAFETY_GUIDE = """
## TOOL SAFETY RULES (YOU MUST FOLLOW THESE)

You have tools to interact with the attack VM. Follow these rules strictly:

### SAFE TOOLS — You may call these freely without asking:
- `get_vm_status` — Check VM health
- `list_loot_files` / `read_loot_file` — Interact with loot
- `web_search` / `web_fetch` / `search_vulnerabilities` — Research
- `doctor_check` — Run health check
- `enum_all` — AD enumeration (read-only)
- `adcs_scan` — ADCS scanning (read-only)
- `bloodhound_analysis` — Analyze BloodHound data
- `analyze_command_output` — Parse command results
- `graph` — Generate attack path graphs
- `run_bash_command` — Runs any bash command. System-destructive commands return a confirmation prompt.

### DESTRUCTIVE TOOLS — You MUST ask the user for explicit confirmation BEFORE calling:
- `run_ovt_command` / `run_ovt_command_confirmed`
- `run_bash_command` / `run_bash_command_confirmed` (for system-destructive commands)
- `dump`, `kerberoast`, `spray`, `crack`

### CONFIRMATION PROTOCOL:
1. When you need to run a destructive tool, first ASK the user clearly
2. Wait for their explicit "yes" or "confirm" response
3. Only then call the tool
4. If they say no, acknowledge and suggest alternatives

### BASH COMMAND GUIDELINES:
- `run_bash_command` runs directly on the Kali VM terminal
- Supports pipes (|), chaining (&&, ;), redirects (>), and all standard Linux tools
- Non-interactive commands only

### OUTPUT HANDLING:
- When you get output from a tool, always analyze it for the user
- Extract meaningful findings (hashes, users, open ports, misconfigs)
- Suggest the exact next command with all flags filled in
- Keep responses focused and actionable
"""


def _load_prompts() -> tuple[str, str]:
    system = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8") if SYSTEM_PROMPT_PATH.exists() else ""
    ovt_ref = OVT_REFERENCE_PATH.read_text(encoding="utf-8") if OVT_REFERENCE_PATH.exists() else ""
    return system, ovt_ref


def _message_content_to_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
                continue
            text = getattr(item, "text", None) or getattr(item, "content", None)
            if text:
                parts.append(str(text))
        return "".join(parts)
    return str(content)


class LLMBrain:
    def __init__(self, config: Settings, memory: Optional[SessionMemory] = None):
        self.config = config
        self.memory = memory
        system_prompt, ovt_ref = _load_prompts()
        self.system_prompt = f"{system_prompt}\n\n{TOOL_SAFETY_GUIDE}\n\n{ovt_ref}" if ovt_ref else f"{system_prompt}\n\n{TOOL_SAFETY_GUIDE}"
        self._providers: list[tuple[str, any, any]] = []
        self._current_provider: Optional[str] = None

    def _init_all_providers(self) -> list[tuple[str, any, any]]:
        if self._providers:
            return self._providers

        configured = self.config.configured_providers()
        for provider in configured:
            try:
                result = self._init_single(provider)
                if result:
                    self._providers.append((provider, *result))
                    log.info("LLM provider initialized: %s", provider)
            except Exception as e:
                log.warning("Failed to init provider %s: %s", provider, e, exc_info=True)

        if not self._providers:
            raise RuntimeError(
                f"No LLM provider could be initialized. Configured: {configured}"
            )

        self._current_provider = self._providers[0][0]
        return self._providers

    def _truncate_text(self, text: str, limit: int) -> str:
        text = text or ""
        if len(text) <= limit:
            return text
        return text[: limit - 24] + "\n...[truncated]..."

    def _trim_chat_history(self, chat_history: list, max_messages: int = 6):
        if len(chat_history) <= max_messages:
            return chat_history
        return chat_history[-max_messages:]

    def _init_single(self, provider: str) -> Optional[tuple]:
        if provider == "mistral" and os.getenv("MISTRAL_API_KEY"):
            return self._init_mistral()

        if provider == "groq" and self.config.groq_api_key:
            return self._init_groq()
        elif provider == "openai" and self.config.openai_api_key:
            return self._init_openai_compat(
                base_url=None,
                api_key=self.config.openai_api_key,
                model=self.config.openai_model,
                label="OpenAI",
            )
        elif provider == "sambanova" and self.config.sambanova_api_key:
            return self._init_openai_compat(
                base_url="https://api.sambanova.ai/v1",
                api_key=self.config.sambanova_api_key,
                model=self.config.sambanova_model,
                label="SambaNova",
            )
        elif provider == "nvidia" and self.config.nvidia_api_key:
            return self._init_openai_compat(
                base_url=self.config.nvidia_base_url,
                api_key=self.config.nvidia_api_key,
                model=self.config.nvidia_model,
                label="NVIDIA",
            )
        elif provider == "nvidia-uncensored" and self.config.nvidia_api_key:
            return self._init_openai_compat(
                base_url=self.config.nvidia_base_url,
                api_key=self.config.nvidia_api_key,
                model=self.config.nvidia_uncensored_model,
                label="NVIDIA Uncensored",
            )
        elif provider == "minimax" and self.config.nvidia_api_key:
            return self._init_openai_compat(
                base_url=self.config.nvidia_base_url,
                api_key=self.config.nvidia_api_key,
                model=self.config.minimax_model,
                label="MiniMax",
            )
        elif provider == "cerebras" and self.config.cerebras_api_key:
            return self._init_openai_compat(
                base_url="https://api.cerebras.ai/v1",
                api_key=self.config.cerebras_api_key,
                model=self.config.cerebras_model,
                label="Cerebras",
            )
        elif provider == "ollama":
            return self._init_ollama()
        return None

    def _init_mistral(self):
        try:
            from mistralai.client import Mistral
        except Exception as e:
            raise RuntimeError("Install mistralai SDK to use the 'mistral' provider: pip install mistralai") from e

        api_key = os.getenv("MISTRAL_API_KEY")
        client = Mistral(api_key=api_key)

        tools_bundle = None
        if self.config.use_agent_tools:
            from core.tools import build_langchain_tools
            langchain_tools = build_langchain_tools()
            tool_defs = []
            for t in langchain_tools:
                try:
                    schema = t.args_schema.schema() if hasattr(t, "args_schema") and t.args_schema else {}
                except Exception:
                    schema = {}
                params = {"type": "object", "properties": {}, "required": []}
                for pname, pinfo in (schema.get("properties") or {}).items():
                    params["properties"][pname] = {"type": pinfo.get("type", "string"), "description": pinfo.get("description", "")}
                    if pname in schema.get("required", []):
                        params["required"].append(pname)
                tool_defs.append({"type": "function", "function": {"name": t.name, "description": getattr(t, "description", ""), "parameters": params}})
            if tool_defs:
                tools_bundle = tool_defs

        return client, tools_bundle

    def _init_groq(self):
        try:
            from langchain_groq import ChatGroq
        except ImportError:
            log.warning("langchain-groq not installed, install with: pip install langchain-groq")
            return None
        llm = ChatGroq(
            model=self.config.groq_model,
            temperature=0.2,
            max_tokens=8192,
            api_key=self.config.groq_api_key,
        )
        return llm, None

    def _init_openai_compat(self, base_url, api_key, model, label):
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise RuntimeError(f"Install langchain-openai for {label} support: pip install langchain-openai")
        kwargs = {"model": model, "temperature": 0.2, "max_tokens": 8192, "api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        llm = ChatOpenAI(**kwargs)
        return llm, None

    def _init_ollama(self):
        from langchain_ollama import ChatOllama
        llm = ChatOllama(
            model=self.config.ollama_model,
            base_url=self.config.ollama_base_url,
            temperature=0.2,
            num_predict=8192,
        )
        return llm, None

    def _build_langchain_agent(self, llm):
        if self.config.use_agent_tools:
            from langchain.agents import create_agent
            from core.tools import build_langchain_tools
            tools = build_langchain_tools()
            try:
                agent = create_agent(model=llm, tools=tools, system_prompt=self.system_prompt)
                return agent, tools
            except Exception as e:
                log.warning("LangChain create_agent failed: %s", e, exc_info=True)
                return llm, None
        return llm, None

    async def _call_with_retry(self, coro_factory, max_retries: int = 2, timeout: float = 60.0):
        last_err = None
        for attempt in range(max_retries):
            try:
                return await asyncio.wait_for(coro_factory(), timeout=timeout)
            except asyncio.TimeoutError:
                log.warning("LLM call timed out (attempt %d/%d)", attempt + 1, max_retries)
                last_err = "LLM call timed out"
            except Exception as e:
                err_str = str(e).lower()
                if attempt < max_retries - 1 and any(k in err_str for k in ("rate", "429", "quota", "overloaded", "unavailable", "503", "500", "timeout", "retry")):
                    wait = 2 ** attempt
                    log.warning("LLM transient error (attempt %d/%d): %s — retrying in %ds", attempt + 1, max_retries, e, wait)
                    await asyncio.sleep(wait)
                    last_err = str(e)
                else:
                    raise
        raise RuntimeError(f"LLM call failed after {max_retries} retries: {last_err}")

    def _is_transient(self, e: Exception) -> bool:
        err_str = str(e).lower()
        return any(k in err_str for k in ("rate", "429", "quota", "overloaded", "unavailable", "503", "500", "timeout", "retry", "limit", "exhausted"))

    async def _chat_mistral(self, client, tools_bundle, messages, *, use_tools: bool = True) -> str:
        from core.tools import build_langchain_tools

        model = os.getenv("MISTRAL_MODEL", "mistral-large-latest")
        sdk_msgs = []
        for m in messages:
            role = getattr(m, "role", None) or ("user" if m.__class__.__name__ == "HumanMessage" else "assistant")
            content = _message_content_to_text(getattr(m, "content", None))
            sdk_msgs.append({"role": role, "content": content})

        tool_map = {t.name: t for t in build_langchain_tools()} if (use_tools and tools_bundle) else {}

        for _ in range(8):
            response = await self._call_with_retry(
                lambda: asyncio.to_thread(
                    client.chat.complete,
                    model=model,
                    messages=sdk_msgs,
                    tools=tools_bundle if use_tools else None,
                ),
                timeout=60.0,
            )

            choice = response.choices[0]
            msg = getattr(choice, "message", None) or choice
            tool_calls = list(getattr(msg, "tool_calls", None) or [])
            if not tool_calls:
                return _message_content_to_text(getattr(msg, "content", msg))

            assistant_tool_calls = []
            for tc in tool_calls:
                assistant_tool_calls.append(
                    {
                        "id": getattr(tc, "id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                )
            sdk_msgs.append(
                {
                    "role": "assistant",
                    "content": _message_content_to_text(getattr(msg, "content", "")),
                    "tool_calls": assistant_tool_calls,
                }
            )

            for tc in tool_calls:
                fname = tc.function.name
                try:
                    fargs = json.loads(tc.function.arguments) if getattr(tc.function, "arguments", None) else {}
                except Exception:
                    fargs = {}

                try:
                    if fname in tool_map:
                        result = await tool_map[fname].ainvoke(fargs)
                    else:
                        result = f"Unknown tool: {fname}"
                except Exception as e:
                    result = f"Tool error: {e}"

                sdk_msgs.append(
                    {
                        "role": "tool",
                        "name": fname,
                        "tool_call_id": getattr(tc, "id", None),
                        "content": self._truncate_text(str(result), 3000),
                    }
                )

        return "Mistral tool-calling did not converge after 8 turns."

    async def _chat_langchain(self, llm, tools_bundle, session_id: str, user_id: str, message: str, *, use_tools: bool = True) -> str:
        session_ctx = {}
        chat_history = []
        if self.memory:
            session_ctx = await self.memory.get_session_context(session_id)
            raw_history = await self.memory.get_chat_history(session_id, limit=15)
            from langchain_core.messages import AIMessage, HumanMessage
            for h in raw_history:
                if h["role"] == "user":
                    chat_history.append(HumanMessage(content=h["content"]))
                else:
                    chat_history.append(AIMessage(content=h["content"]))
            chat_history = self._trim_chat_history(chat_history, max_messages=6)

        context_block = self._build_context_block(session_ctx)
        context_block = self._truncate_text(context_block, 5000)
        message = self._truncate_text(message, 6000)
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = list(chat_history)
        if context_block:
            messages.append(SystemMessage(content=context_block))
        messages.append(HumanMessage(content=message))

        if use_tools and self.config.use_agent_tools:
            try:
                from mistralai.client import Mistral as _MistralClass
            except Exception:
                _MistralClass = None

            if _MistralClass and isinstance(llm, _MistralClass):
                reply = await self._chat_mistral(llm, tools_bundle, messages, use_tools=True)
            else:
                agent, _ = self._build_langchain_agent(llm)
                response = await self._call_with_retry(
                    lambda: agent.ainvoke({"messages": messages}),
                    timeout=60.0,
                )
                response_messages = response.get("messages", []) if isinstance(response, dict) else []
                reply_source = response_messages[-1].content if response_messages else response
                reply = _message_content_to_text(reply_source)
        else:
            result = await self._call_with_retry(lambda: llm.ainvoke(messages), timeout=60.0)
            reply = _message_content_to_text(getattr(result, "content", result))

        if self.memory:
            await self.memory.add_chat_message(session_id, "user", message)
            await self.memory.add_chat_message(session_id, "assistant", reply)
        return reply

    async def chat(self, session_id: str, user_id: str, message: str, context_override: dict = None, enable_tools: Optional[bool] = None) -> str:
        use_tools = enable_tools if enable_tools is not None else self.config.use_agent_tools
        if use_tools:
            try:
                from core.tools import set_tool_user_context
                set_tool_user_context(user_id)
            except Exception:
                pass

        providers = self._init_all_providers()
        last_error = None

        try:
            for i, (name, llm, tools) in enumerate(providers):
                try:
                    result = await self._chat_langchain(llm, tools, session_id, user_id, message, use_tools=use_tools)

                    if i > 0:
                        log.info("LLM fallback: switched from %s to %s", providers[i-1][0], name)
                        self._current_provider = name
                    return result

                except Exception as e:
                    last_error = e
                    if self._is_transient(e) and i < len(providers) - 1:
                        log.warning("LLM %s failed (%s), falling back to %s", name, e, providers[i+1][0])
                        continue
                    if i < len(providers) - 1:
                        log.warning("LLM %s failed (%s), falling back to %s", name, e, providers[i+1][0])
                        continue
                    raise
        finally:
            if self.config.use_agent_tools:
                try:
                    from core.tools import set_tool_user_context
                    set_tool_user_context(None)
                except Exception:
                    pass

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    async def chat_unsafe(self, session_id: str, user_id: str, message: str) -> str:
        use_tools = self.config.use_agent_tools
        if use_tools:
            try:
                from core.tools import set_tool_user_context
                set_tool_user_context(user_id)
            except Exception:
                pass
        try:
            result = self._init_single("nvidia-uncensored")
            if not result:
                raise RuntimeError("Uncensored provider not available. Set NVIDIA_API_KEY.")
            name, llm, tools = ("nvidia-uncensored", *result)
            return await self._chat_langchain(llm, tools, session_id, user_id, message, use_tools=use_tools)
        except Exception as e:
            raise RuntimeError(f"Uncensored provider failed: {e}") from e
        finally:
            if use_tools:
                try:
                    from core.tools import set_tool_user_context
                    set_tool_user_context(None)
                except Exception:
                    pass

    async def _try_vision_model(self, model: str, prompt: str, encoded: str) -> Optional[str]:
        if not model or not self.config.nvidia_api_key:
            return None
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage
            llm = ChatOpenAI(
                model=model,
                temperature=0.2,
                max_tokens=8192,
                api_key=self.config.nvidia_api_key,
                base_url=self.config.nvidia_base_url,
            )
            msg = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                ]
            )
            response = await self._call_with_retry(lambda: llm.ainvoke([msg]), timeout=60.0)
            return _message_content_to_text(getattr(response, "content", response))
        except Exception as e:
            log.warning("Vision model %s failed: %s", model, e)
            return None

    async def analyze_image(self, image_bytes: bytes, prompt: str = "Analyze this screenshot from a pentest VM. What do you see? Identify any tools, terminals, commands, or security-relevant information.") -> str:
        import base64
        encoded = base64.b64encode(image_bytes).decode("utf-8")

        # NVIDIA vision chain: primary -> fallback
        if self.config.nvidia_api_key:
            for model in [self.config.nvidia_vision_model, self.config.nvidia_vision_model_fallback]:
                result = await self._try_vision_model(model, prompt, encoded)
                if result:
                    return result

        # Fall back to other providers
        providers = self._init_all_providers()
        for name, llm, tools in providers:
            try:
                from langchain_core.messages import HumanMessage
                msg = HumanMessage(
                    content=[
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                    ]
                )
                response = await self._call_with_retry(lambda: llm.ainvoke([msg]), timeout=60.0)
                return _message_content_to_text(getattr(response, "content", response))
            except Exception as e:
                log.warning("%s image analysis failed (%s), trying next provider", name, e)
                continue
        return "Image analysis requires a vision-capable provider. Configure NVIDIA_API_KEY (with vision model) or GROQ_API_KEY."

    @cached(ttl_secs=300)
    async def analyze_output(self, session_id: str, command: str, output: str) -> str:
        prompt = f"""I just ran this Overthrone command:
```
{command}
```

Here is the output:
```
{output[:3000]}
```

Please:
1. Parse what was found (exact users, hashes, misconfigs, paths — be specific)
2. Identify any mistakes I made or things I should have done differently
3. Assess the severity and impact of each finding
4. Tell me the EXACT next ovt command(s) to run, with all flags filled in
5. Note any WS 2019/2022/2025 specific considerations for this situation
"""
        return await self.chat(session_id, "analyze", prompt)

    def _build_context_block(self, ctx: dict) -> str:
        parts = ["## CURRENT SESSION CONTEXT\n"]
        if ctx.get("session"):
            s = ctx["session"]
            parts.append(f"**Target:** DC={s.get('dc_host', '?')}, Domain={s.get('domain', '?')}, User={s.get('username', '?')}")
        if ctx.get("recent_commands"):
            parts.append("\n**Recent commands (newest first):**")
            for c in ctx["recent_commands"][:10]:
                status = "\u2713" if c["exit_code"] == 0 else "\u2717"
                parts.append(f"  {status} `{c['command'][:80]}` \u2014 {c['summary'][:100]}")
        if ctx.get("findings"):
            parts.append("\n**Session findings:**")
            for f in ctx["findings"]:
                parts.append(f"  [{f['severity'].upper()}] {f['type']}: {f['title']}")
        return "\n".join(parts)
