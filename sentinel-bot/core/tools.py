from typing import Optional

from .bloodhound_parser import analyze_bloodhound_json
from .output_parser import parse_output

_agent_manager = None
_memory_store = None
_use_web_search = True

DESTRUCTIVE_KEYWORDS = [
    "forge", "skeleton-key", "dsrm", "relay", "dump", "exec",
    "golden", "silver", "diamond", "sapphire", "shadow-creds",
    "backdoor", "cleanup", "ntlm relay",
]

DANGEROUS_SYSTEM_COMMANDS = [
    "rm -rf /", "rm -rf --no-preserve-root", "mkfs", "dd if=", "format",
    "shutdown", "reboot", "poweroff", "halt", "> /dev/sd", "fdisk",
    "parted", "mkswap", "iptables -F", "ufw disable",
    "systemctl stop networking", "kill -9 -1", "chmod 0 /",
    "chown -R 0:", "mv /* ", "cp /* ", "wget -O /", "curl -o /",
    "dd of=", "> /dev/null", "init 0", "init 6", "telinit",
    "pvcreate", "vgremove", "lvremove", "mdadm --stop",
    "iwconfig", "ifconfig down", "ip link set down", "modprobe -r",
    "echo > /etc/", "systemctl disable", "update-rc.d",
]


def init_tools(agent_manager, memory, use_web_search: bool = True):
    global _agent_manager, _memory_store, _use_web_search
    _agent_manager = agent_manager
    _memory_store = memory
    _use_web_search = use_web_search


def _is_destructive(cmd: str) -> bool:
    return any(kw in cmd.lower() for kw in DESTRUCTIVE_KEYWORDS)


def _is_destructive_system(cmd: str) -> bool:
    lower = cmd.lower()
    for pattern in DANGEROUS_SYSTEM_COMMANDS:
        if pattern in lower:
            return True
    return False


def _sanitize_command(cmd: str) -> Optional[str]:
    stripped = cmd.strip()
    dangerous = (";", "|", "&&", "`", "$(", "${", "||", "& ", ">", "<")
    if any(d in stripped for d in dangerous):
        return "Error: Shell metacharacters are not allowed in commands."
    if len(stripped) > 2000:
        return "Error: Command exceeds maximum length of 2000 characters."
    return None


def _sanitize_shell(cmd: str) -> Optional[str]:
    stripped = cmd.strip()
    if not stripped:
        return "Error: Empty command."
    if len(stripped) > 4000:
        return "Error: Command exceeds maximum length of 4000 characters."
    blocked = ("`", "$(", "${")
    if any(b in stripped for b in blocked):
        return "Error: Command substitution is not allowed for security reasons."
    return None


async def _run_ovt_command_raw(command: str) -> str:
    sanitize_err = _sanitize_command(command)
    if sanitize_err:
        return sanitize_err
    if not _agent_manager:
        return "Agent client not initialized."
    try:
        client = _agent_manager.get_active()
    except RuntimeError as e:
        return str(e)
    output_lines = []
    try:
        async for msg in client.run_command(command):
            if hasattr(msg, "type"):
                if msg.type == "command_output":
                    output_lines.append(msg.payload.get("data", ""))
                elif msg.type == "command_complete":
                    break
                elif msg.type == "error":
                    return f"Agent error: {msg.payload.get('message')}"
    except Exception as e:
        return f"Error running command: {e}"
    return "\n".join(output_lines[-100:])


def _build_session_target() -> dict:
    return {"dc": "", "domain": "", "username": "", "password": ""}


def _build_cmd(base: str, target: dict, extra: list[str] = None) -> str:
    parts = [base]
    h = target.get("dc", "")
    d = target.get("domain", "")
    u = target.get("username", "")
    p = target.get("password", "")
    if h: parts.extend(["-H", h])
    if d: parts.extend(["-d", d])
    if u: parts.extend(["-u", u])
    if p: parts.extend(["-p", p])
    if extra: parts.extend(extra)
    return " ".join(parts)


def build_langchain_tools() -> list:
    from langchain.tools import tool
    from typing import Annotated

    # ── SAFE TOOLS (execute automatically) ──

    @tool
    async def get_vm_status() -> str:
        """Get current VM status: CPU, RAM, disk, network connections, running processes, OVT version."""
        if not _agent_manager:
            return "Agent client not initialized"
        try:
            client = _agent_manager.get_active()
        except RuntimeError as e:
            return str(e)
        try:
            msg = await client.get_status()
            if msg.type == "error":
                return f"Agent error: {msg.payload.get('message')}"
            cpu = msg.payload.get("cpu_percent", 0)
            ram_used = msg.payload.get("ram_used_mb", 0)
            ram_total = msg.payload.get("ram_total_mb", 0)
            disk_free = msg.payload.get("disk_free_gb", 0)
            conns = len(msg.payload.get("network_connections", []))
            procs = msg.payload.get("running_processes", [])
            ovt_ver = msg.payload.get("ovt_version", "unknown")
            return (f"CPU: {cpu:.1f}% | RAM: {ram_used}MB / {ram_total}MB | "
                    f"Disk free: {disk_free:.1f}GB | Connections: {conns} | "
                    f"Processes: {len(procs)} | OVT: {ovt_ver}")
        except Exception as e:
            return f"Error getting status: {e}"

    @tool
    async def run_ovt_command(command: Annotated[str, "Full OVT command to run on the VM"]) -> str:
        """Run an Overthrone (ovt) command on the attack VM and return its output.

        SAFE operations (run automatically): enum, scan, doctor, status, graph, bloodhound, read.
        RISKY operations (require user confirmation first): dump, spray, forge, kerberoast, exec, crack, adcs exploit.
        """
        check = _sanitize_command(command)
        if check:
            return check

        if _is_destructive(command):
            return (
                "⚠️ **CONFIRMATION REQUIRED**\n\n"
                f"This command is flagged as DESTRUCTIVE:\n"
                f"```\n{command[:500]}\n```\n\n"
                "Ask the user: \"I want to run this destructive command — do you confirm? Reply with yes or no.\"  \n"
                "Once they say yes, re-call this tool with the SAME command."
            )

        return await _run_ovt_command_raw(command)

    @tool
    async def run_ovt_command_confirmed(
        command: Annotated[str, "Full OVT command to run — user has confirmed"],
    ) -> str:
        """Run an OVT command that the user has ALREADY confirmed. Only use this after the user explicitly said yes to a destructive command."""
        check = _sanitize_command(command)
        if check:
            return check
        return await _run_ovt_command_raw(command)

    # ── BASH / SHELL COMMANDS (Kali VM terminal) ──

    @tool
    async def run_bash_command(
        command: Annotated[str, "Bash command to execute on the Kali VM terminal"],
    ) -> str:
        """Run any bash command on the Kali attack VM. Supports pipes (|), chaining (&&, ;), redirects (>), and all standard Linux tools.

        SAFE operations (run automatically): ls, cat, nmap, nc, ping, curl, dig, nslookup, whoami, id, ifconfig, ip, ps, top, netstat, ss, grep, find, locate, which, echo, cd, pwd, python3, perl, ruby, impacket commands, responder, bloodhound, certipy, enum4linux, smbclient, ldapsearch, rpcclient, evil-winrm, crackmapexec, nxc, hydra, john, hashcat, chisel, socat, proxychains.

        DESTRUCTIVE operations (require user confirmation first): rm -rf /, mkfs, dd, shutdown, reboot, fdisk, parted, any system-destructive command.
        """
        check = _sanitize_shell(command)
        if check:
            return check

        if _is_destructive_system(command):
            return (
                "⚠️ **SYSTEM-DESTRUCTIVE — CONFIRMATION REQUIRED**\n\n"
                f"This command is flagged as system-destructive:\n"
                f"```\n{command[:500]}\n```\n\n"
                "Ask the user: \"This could damage the VM's system — do you confirm? Reply with yes or no.\"\n"
                "Once confirmed, use run_bash_command_confirmed with the same command."
            )

        return await _run_ovt_command_raw(command)

    @tool
    async def run_bash_command_confirmed(
        command: Annotated[str, "Bash command to execute — user has confirmed"],
    ) -> str:
        """Run a bash command that the user has ALREADY confirmed. Only use after they explicitly said yes to a destructive system command."""
        check = _sanitize_shell(command)
        if check:
            return check
        return await _run_ovt_command_raw(command)

    @tool
    async def list_loot_files() -> str:
        """List all files in the loot directory (hashes, tickets, BloodHound JSON, reports)."""
        if not _agent_manager:
            return "Agent client not initialized"
        try:
            client = _agent_manager.get_active()
        except RuntimeError as e:
            return str(e)
        try:
            msg = await client.get_loot()
            if msg.type == "error":
                return f"Agent error: {msg.payload.get('message')}"
            files = msg.payload.get("files", [])
            if not files:
                return "Loot directory is empty."
            return "\n".join(
                f"[{f.get('file_type', 'Unknown')}] {f.get('name', '?')} "
                f"({f.get('size_bytes', 0) // 1024}KB)"
                for f in files
            )
        except Exception as e:
            return f"Error listing loot: {e}"

    @tool
    async def read_loot_file(path: Annotated[str, "Path to the loot file to read"]) -> str:
        """Read the content of a specific loot file (hashes, credentials, JSON, etc.)."""
        if not _agent_manager:
            return "Agent client not initialized"
        try:
            client = _agent_manager.get_active()
        except RuntimeError as e:
            return str(e)
        if ".." in path or path.startswith("/") or path.startswith("\\"):
            return "Error: Path traversal detected."
        try:
            msg = await client.read_loot_file(path)
            if msg.type == "error":
                return f"Agent error: {msg.payload.get('message')}"
            return (msg.payload.get("content", "") or "")[:3000]
        except Exception as e:
            return f"Error reading file: {e}"

    @tool
    async def doctor_check() -> str:
        """Run 'ovt doctor' health check on the VM. Always run this first on a new target to check LDAP signing, SMB signing, patch level indicators."""
        return await _run_ovt_command_raw("ovt doctor")

    # ── TARGETED ATTACK TOOLS (require session context) ──

    @tool
    async def enum_all(
        dc_host: Annotated[str, "Target DC hostname or IP (optional if set in session)"] = "",
        domain: Annotated[str, "Target domain (optional if set in session)"] = "",
    ) -> str:
        """Run full AD enumeration against the target domain: users, groups, computers, trusts, SPNs, delegation, GPOs, OUs."""
        target = _build_session_target()
        cmd = _build_cmd("ovt enum all", target, extra=[])
        if dc_host: cmd += f" -H {dc_host}"
        if domain: cmd += f" -d {domain}"
        return await _run_ovt_command_raw(cmd)

    @tool
    async def kerberoast(
        dc_host: Annotated[str, "Target DC hostname or IP (optional)"] = "",
        domain: Annotated[str, "Target domain (optional)"] = "",
        etype: Annotated[str, "Kerberos encryption type: 23 (RC4), 17/18 (AES), or all (default: 23)"] = "23",
    ) -> str:
        """Request Kerberos service tickets (SPN tickets) for offline cracking — Kerberoasting attack."""
        target = _build_session_target()
        extra = [f"--etype {etype}"]
        cmd = _build_cmd("ovt kerberos roast", target, extra)
        if dc_host: cmd += f" -H {dc_host}"
        if domain: cmd += f" -d {domain}"

        check = _sanitize_command(cmd)
        if check:
            return check
        return (
            "⚠️ **CONFIRMATION REQUIRED**\n\n"
            f"This will request Kerberos TGS tickets for all SPN accounts:\n"
            f"```\n{cmd[:500]}\n```\n\n"
            "Ask the user: \"This will generate Kerberos TGS requests for all service accounts — "
            "this is logged as event ID 4769 on the DC. Do you confirm?\"  \n"
            "Once they say yes, use run_ovt_command_confirmed with the exact command above."
        )

    @tool
    async def spray(
        password: Annotated[str, "Password to spray"],
        userlist: Annotated[str, "Userlist file path on the VM (default: users.txt)"] = "users.txt",
        dc_host: Annotated[str, "Target DC (optional)"] = "",
        domain: Annotated[str, "Target domain (optional)"] = "",
    ) -> str:
        """Password spray attack. Checks lockout policy first for safety, then sprays the given password against all users."""
        target = _build_session_target()
        dc = dc_host or target.get("dc", "")
        dom = domain or target.get("domain", "")

        policy_cmd = "ovt enum policy"
        if dc: policy_cmd += f" -H {dc}"
        if dom: policy_cmd += f" -d {dom}"
        policy_result = await _run_ovt_command_raw(policy_cmd)

        return (
            f"**Lockout Policy:**\n```\n{policy_result[:1000]}\n```\n\n"
            "⚠️ **CONFIRMATION REQUIRED**\n\n"
            f"Proposed spray command: `ovt spray --userlist {userlist} --password \"{password[:20]}...\"`\n\n"
            "Ask the user: \"Password spray will generate failed logon events (4625) for every user. "
            "Review the lockout policy above and confirm if you want to proceed.\"  \n"
            "Once confirmed, use run_ovt_command_confirmed with the actual spray command."
        )

    @tool
    async def adcs_scan(
        dc_host: Annotated[str, "Target DC hostname or IP (optional)"] = "",
        domain: Annotated[str, "Target domain (optional)"] = "",
    ) -> str:
        """Scan for ADCS (Active Directory Certificate Services) vulnerabilities: ESC1-ESC13."""
        target = _build_session_target()
        cmd = _build_cmd("ovt adcs enum", target)
        if dc_host: cmd += f" -H {dc_host}"
        if domain: cmd += f" -d {domain}"
        return await _run_ovt_command_raw(cmd)

    @tool
    async def dump(
        dc_host: Annotated[str, "Target DC hostname or IP (optional)"] = "",
    ) -> str:
        """DCSync attack — extract domain credentials via DRSUAPI protocol replication. Requires Domain Admin or equivalent."""
        target = _build_session_target()
        cmd = _build_cmd("ovt dump", target)
        if dc_host: cmd += f" -H {dc_host}"

        check = _sanitize_command(cmd)
        if check:
            return check
        return (
            "🚨 **DESTRUCTIVE — CONFIRMATION REQUIRED**\n\n"
            f"This will run a DCSync attack:\n"
            f"```\n{cmd[:500]}\n```\n\n"
            "This extracts ALL domain password hashes and is EXTREMELY LOUD (event ID 4662 on DC).\n\n"
            "Ask the user: \"DCSync will extract all domain credential hashes via DRSUAPI. "
            "This is detected by MDI, Defender for Identity, and most EDRs. Do you confirm?\"\n"
            "Once confirmed, use run_ovt_command_confirmed."
        )

    @tool
    async def crack(
        hash_file: Annotated[str, "Hash file to crack (default: hashes.txt)"] = "hashes.txt",
        wordlist: Annotated[str, "Wordlist path (default: /usr/share/wordlists/rockyou.txt)"] = "/usr/share/wordlists/rockyou.txt",
    ) -> str:
        """Crack extracted password hashes against a wordlist. Runs on the VM."""
        cmd = f"ovt crack --hashes {hash_file} --wordlist {wordlist}"

        check = _sanitize_command(cmd)
        if check:
            return check
        return (
            "⚠️ **CONFIRMATION REQUIRED**\n\n"
            f"This will run hash cracking:\n"
            f"```\n{cmd[:500]}\n```\n\n"
            "Ask the user: \"Hash cracking will use significant CPU on the VM. Do you confirm?\"\n"
            "Once confirmed, use run_ovt_command_confirmed."
        )

    @tool
    async def bloodhound_analysis(
        filename: Annotated[str, "BloodHound JSON filename in the loot directory"],
    ) -> str:
        """Analyze a BloodHound JSON file and return key findings: kerberoastable users, AS-REP roastable users, high-value groups, interesting ACLs, shortest paths to DA."""
        if not _agent_manager:
            return "Agent client not initialized"
        try:
            client = _agent_manager.get_active()
        except RuntimeError as e:
            return str(e)
        try:
            loot = await client.get_loot()
            if loot.type == "error":
                return f"Agent error: {loot.payload.get('message')}"
            files = loot.payload.get("files", [])
            target = None
            for f in files:
                if f.get("name") == filename or f.get("name", "").endswith(filename):
                    target = f
                    break
            if not target:
                return f"File '{filename}' not found in loot. Use list_loot_files() to see available files."
            content_msg = await client.read_loot_file(target["path"])
            if content_msg.type == "error":
                return f"Agent error: {content_msg.payload.get('message')}"
            raw = content_msg.payload.get("content", "")
            if not raw:
                return "File is empty."
            try:
                bh = analyze_bloodhound_json(raw)
            except Exception as e:
                return f"Local parsing failed: {e}. Raw data (first 1000 chars):\n{raw[:1000]}"
            lines = [
                f"**Stats:** Nodes: {bh['total_nodes']}, Edges: {bh['total_edges']}",
                f"Users: {len(bh['users'])}, Computers: {len(bh['computers'])}",
            ]
            if bh.get("kerberoastable"):
                users = ", ".join(u["name"] for u in bh["kerberoastable"][:10])
                lines.append(f"**Kerberoastable ({len(bh['kerberoastable'])}):** {users}")
            if bh.get("asrep_roastable"):
                users = ", ".join(u["name"] for u in bh["asrep_roastable"][:10])
                lines.append(f"**AS-REP Roastable ({len(bh['asrep_roastable'])}):** {users}")
            if bh.get("high_value_groups"):
                groups = ", ".join(g["name"] for g in bh["high_value_groups"][:5])
                lines.append(f"**High-value groups:** {groups}")
            if bh.get("interesting_acls"):
                for a in bh["interesting_acls"][:5]:
                    lines.append(f"- {a['type']}: {a['grantee']} → {a['target']}")
            if bh.get("sessions"):
                lines.append(f"**Active sessions:** {len(bh['sessions'])}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error analyzing BloodHound file: {e}"

    @tool
    async def analyze_command_output(
        command: Annotated[str, "The OVT command that was run"],
        output: Annotated[str, "The command output to analyze"],
    ) -> str:
        """Parse and analyze OVT command output. Extracts hashes, credentials, misconfigurations, delegation types, and ADCS vulnerabilities. Use this after running any command."""
        try:
            parsed = parse_output(output)
            parts = []
            if parsed.get("kerb_hashes"):
                parts.append(f"Kerberos hashes extracted: {len(parsed['kerb_hashes'])}")
            if parsed.get("ntlm_hashes"):
                parts.append(f"NTLM hashes extracted: {len(parsed['ntlm_hashes'])}")
            if parsed.get("adcs_findings"):
                parts.append(f"ADCS findings: {len(parsed['adcs_findings'])}")
            if parsed.get("delegation_types"):
                parts.append(f"Delegation types: {parsed['delegation_types']}")
            if not parts:
                parts.append("No structured findings extracted from the raw output.")
            return "\n".join(parts)
        except Exception as e:
            return f"Parse error: {e}"

    @tool
    async def graph(
        query: Annotated[str, "Cypher query (optional)"] = "",
        depth: Annotated[int, "Path depth for attack path generation (default: 5)"] = 5,
    ) -> str:
        """Generate an attack path graph from BloodHound data. Optionally specify a Cypher query and depth."""
        parts = ["ovt graph"]
        if query:
            parts.append(f"--query \"{query}\"")
        parts.append(f"--depth {depth}")
        cmd = " ".join(parts)
        return await _run_ovt_command_raw(cmd)

    # ── BUILD TOOL LIST ──

    tools = [
        get_vm_status,
        run_ovt_command,
        run_ovt_command_confirmed,
        run_bash_command,
        run_bash_command_confirmed,
        list_loot_files,
        read_loot_file,
        doctor_check,
        enum_all,
        kerberoast,
        spray,
        adcs_scan,
        dump,
        crack,
        bloodhound_analysis,
        analyze_command_output,
        graph,
    ]

    if _use_web_search:
        from .web_tools import web_search as _web_search_impl
        from .web_tools import web_fetch as _web_fetch_impl
        from .web_tools import search_vulnerabilities as _search_vulns_impl

        @tool
        async def web_search(query: Annotated[str, "Search query"]) -> str:
            """Search the web for current information. Returns titles, snippets, and URLs."""
            results = await _web_search_impl(query)
            lines = []
            for r in results:
                if "error" in r:
                    lines.append(f"Error: {r['error']}")
                elif "info" in r:
                    lines.append(r["info"])
                else:
                    lines.append(f"  {r.get('title', '?')}")
                    lines.append(f"  {r.get('snippet', '')[:300]}")
                    lines.append(f"  URL: {r.get('url', '')}")
                    lines.append("")
            return "\n".join(lines[:25])

        @tool
        async def web_fetch(url: Annotated[str, "URL to fetch and read"]) -> str:
            """Fetch a web page and extract its readable text content."""
            from .web_tools import validate_public_url
            err = validate_public_url(url)
            if err:
                return f"Error: {err}"
            return await _web_fetch_impl(url)

        @tool
        async def search_vulnerabilities(product: Annotated[str, "Windows Server version or product name to search CVEs for"]) -> str:
            """Search known vulnerabilities (CVEs) for a Windows Server version or AD product."""
            return await _search_vulns_impl(product)

        tools.extend([web_search, web_fetch, search_vulnerabilities])

    return tools
