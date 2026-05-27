import asyncio
import logging
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


def _resolve_tool_calling_agent_factory():
    try:
        from langchain.agents import create_tool_calling_agent
        return create_tool_calling_agent
    except Exception:
        pass
    try:
        from langchain.agents.tool_calling_agent import create_tool_calling_agent
        return create_tool_calling_agent
    except Exception:
        pass
    try:
        from langchain.agents import create_openai_tools_agent
        return create_openai_tools_agent
    except Exception as exc:
        raise RuntimeError(
            "No tool-calling agent factory found. "
            "Update langchain to a newer version (e.g., >=0.3.10)."
        ) from exc


def _load_prompts() -> tuple[str, str]:
    system = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8") if SYSTEM_PROMPT_PATH.exists() else ""
    ovt_ref = OVT_REFERENCE_PATH.read_text(encoding="utf-8") if OVT_REFERENCE_PATH.exists() else ""
    return system, ovt_ref


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
                log.warning("Failed to init provider %s: %s", provider, e)

        if not self._providers:
            raise RuntimeError(
                f"No LLM provider could be initialized. Configured: {configured}"
            )

        self._current_provider = self._providers[0][0]
        return self._providers

    def _init_single(self, provider: str) -> Optional[tuple]:
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

    def _init_groq(self):
        from langchain_groq import ChatGroq
        llm = ChatGroq(
            model=self.config.groq_model,
            temperature=0.2,
            max_tokens=8192,
            api_key=self.config.groq_api_key,
        )
        return self._build_agent_executor(llm)

    def _init_openai_compat(self, base_url, api_key, model, label):
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise RuntimeError(f"Install langchain-openai for {label} support: pip install langchain-openai")
        kwargs = {"model": model, "temperature": 0.2, "max_tokens": 8192, "api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        llm = ChatOpenAI(**kwargs)
        return self._build_agent_executor(llm)

    def _init_ollama(self):
        from langchain_ollama import ChatOllama
        llm = ChatOllama(
            model=self.config.ollama_model,
            base_url=self.config.ollama_base_url,
            temperature=0.2,
            num_predict=8192,
        )
        return self._build_agent_executor(llm)

    def _build_agent_executor(self, llm):
        if self.config.use_agent_tools:
            from core.tools import build_langchain_tools
            tools = build_langchain_tools()
            from langchain.agents import AgentExecutor
            from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
            prompt = ChatPromptTemplate.from_messages([
                ("system", self.system_prompt),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ])
            agent_factory = _resolve_tool_calling_agent_factory()
            agent = agent_factory(llm, tools, prompt)
            executor = AgentExecutor(agent=agent, tools=tools, verbose=False, max_iterations=8, max_execution_time=180)
            return executor, tools
        return llm, None

    async def _call_with_retry(self, coro_factory, max_retries: int = 3, timeout: float = 120.0):
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

    async def _chat_langchain(self, executor, session_id: str, user_id: str, message: str) -> str:
        session_ctx = {}
        chat_history = []
        if self.memory:
            session_ctx = await self.memory.get_session_context(session_id)
            raw_history = await self.memory.get_chat_history(session_id, limit=15)
            from langchain_core.messages import HumanMessage, AIMessage
            for h in raw_history:
                if h["role"] == "user":
                    chat_history.append(HumanMessage(content=h["content"]))
                else:
                    chat_history.append(AIMessage(content=h["content"]))

        context_block = self._build_context_block(session_ctx)
        context_msg = f"{context_block}\n\n{message}" if context_block else message

        is_executor = hasattr(executor, "ainvoke") and hasattr(executor, "agent")
        if is_executor:
            response = await self._call_with_retry(
                lambda: executor.ainvoke({"input": context_msg, "chat_history": chat_history}),
                timeout=180.0,
            )
            reply = response.get("output", str(response))
        else:
            full_prompt = f"{self.system_prompt}\n\n{context_block}\n\nUser: {message}"
            result = await self._call_with_retry(lambda: executor.ainvoke(full_prompt), timeout=120.0)
            reply = result.content if hasattr(result, "content") else str(result)

        if self.memory:
            await self.memory.add_chat_message(session_id, "user", message)
            await self.memory.add_chat_message(session_id, "assistant", reply)
        return reply

    async def chat(self, session_id: str, user_id: str, message: str, context_override: dict = None) -> str:
        providers = self._init_all_providers()
        last_error = None

        for i, (name, llm, tools) in enumerate(providers):
            try:
                result = await self._chat_langchain(llm, session_id, user_id, message)

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

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    async def analyze_image(self, image_bytes: bytes, prompt: str = "Analyze this screenshot from a pentest VM. What do you see? Identify any tools, terminals, commands, or security-relevant information.") -> str:
        return "Image analysis is not supported with the current LLM providers."

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
