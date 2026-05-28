# OVT-Sentinel

**AI-powered Discord bot for Overthrone (OVT) Active Directory penetration testing.**  
Invite the bot once, run an agent on your Kali VM, and control everything from Discord — no manual IP updates, no open inbound ports, no tunnel configuration.

---

## 1. Core Architecture

### Bot (Python — Koyeb free tier)
- **Discord Gateway** — slash commands, ephemeral replies, embed builders, button/modals
- **Combined HTTP+WS Server (port 8000)** — single port handles all traffic:
  - `GET /` and `GET /health` — Koyeb healthcheck probes
  - `GET /register?token=...&url=...` — tunnel auto-registration
  - `WS /agent-ws` — agent reverse-connect WebSocket endpoint
- **Core Services** — LLMBrain (multi-provider), AgentManager (per-user), SessionMemory (PostgreSQL), RateLimiter, Web/Research Tools
- **Database** — PostgreSQL 16 for sessions, chat history, agent registrations, findings

### Agent (Rust — runs on Kali VM)
- **Reverse-connect client** (`--connect-to-bot`) — agent connects outbound to bot's WS server via WSS (port 443)
- **WS server** (`--bind 0.0.0.0:7331`) — for tunnel/direct mode agent accept connections
- **Cloudflared tunnel** (`--tunnel`) — spawns cloudflared, parses `*.trycloudflare.com` URL, converts `https://` to `wss://`
- **Fallback tunnel** (`--fallback-tunnel`) — tries reverse first, auto-falls back to cloudflared if reverse fails
- **WireGuard** (`--wireguard`) — for air-gapped labs with relay VPS
- **Command Executor** — spawns OVT commands with safe arg arrays (no shell injection)
- **System Monitor** — CPU, RAM, disk, network, running processes
- **Loot Watcher** — browse and read collected files from discords
- **Browser Controller** — screenshot and URL navigation via Playwright

### Connectivity Modes

| Mode | Flag | Direction | Ports | Use Case |
|------|------|-----------|-------|----------|
| **Reverse Connect** ⭐ | `--connect-to-bot` | Agent → Bot WS | TCP 443 outbound only | Kali behind NAT/firewall, no tunnel needed |
| **Reverse + Fallback** | `--connect-to-bot --fallback-tunnel` | Reverse first, cloudflared fallback | TCP 443 outbound only | Unreliable internet, best of both |
| **Cloudflare Tunnel** | `--tunnel` | cloudflared → trycloudflare.com | TCP 443 outbound only | Kali with full internet access |
| **Direct** | `--bind 0.0.0.0:7331` | Kali WS server | TCP 7331 inbound | Kali on same network as bot |
| **WireGuard** | `--wireguard` | wg-quick VPN | Configurable | Air-gapped labs with relay VPS |

### Bot → Agent Flow

```
Discord ──HTTPS/WSS──▶ sentinel-bot (Koyeb, port 8000)
                            │
                    ┌───────┼───────┐
                    │       │       │
              Agent A   Agent B   Agent C
              (Kali)    (Kali)    (Kali)
```

- Agent connects **outbound** via WSS → `wss://<app>.koyeb.app/agent-ws` (port 443)
- Bot validates token via database lookup
- Bot creates `AgentClient` and enters command-processing loop
- Connection stays alive via `asyncio.Future()` in the WS handler

---

## 2. LLM Providers

### Text Generation Priority Chain
**NVIDIA (Mistral Large 3)** → Cerebras (Qwen-3-235B) → Groq (Llama 4 Scout) → Gemini (2.5 Flash) → MiniMax (M2.7) → OpenAI (GPT-4o-mini) → SambaNova (Llama 3.1 70B) → Ollama

### Image Analysis Priority Chain
All OpenAI-compatible providers tried first (NVIDIA, Groq, Cerebras, etc.) → Gemini 2.5 Flash

### Provider Details

| Provider | API Key Env | Model | Free Tier | Supports |
|----------|-------------|-------|-----------|----------|
| **NVIDIA NIM** | `NVIDIA_API_KEY` | `mistralai/mistral-large-3-675b-instruct-2512` | ~40 RPM, no token caps, no CC | Text + Vision |
| **Cerebras** | `CEREBRAS_API_KEY` | `Qwen-3-235B-Instruct` | Free, rate-limited | Text |
| **Groq** | `GROQ_API_KEY` | `meta-llama/llama-4-scout-17b-16e-instruct` | 30 req/min | Text + Vision |
| **Gemini** | `GEMINI_API_KEY` | `models/gemini-2.5-flash` | 60 req/min, 1500/day | Text + Vision |
| **MiniMax** | `NVIDIA_API_KEY` | `minimaxai/minimax-m2.7` | Same as NVIDIA, auto-chained | Text |
| **OpenAI** | `OPENAI_API_KEY` | `gpt-4o-mini` | Paid | Text |
| **SambaNova** | `SAMBANOVA_API_KEY` | `Meta-Llama-3.1-70B-Instruct` | Free, rate-limited | Text |
| **Ollama** | (local) | `llama3.1:70b` | Free, local | Text |

- `NVIDIA_API_KEY` single key unlocks two providers: NVIDIA (Mistral Large 3) + MiniMax (M2.7)
- Sign up at build.nvidia.com (no credit card), get `nvapi-...` key
- Fallback chain auto-selects working provider — no `LLM_PROVIDER` env var needed

---

## 3. Discord Commands

### Agent Management
| Command | Description |
|---------|-------------|
| `/agent register [mode]` | Generate token + agent command (mode: reverse/tunnel/direct) |
| `/agent connect <ws_url>` | Connect VM to bot (tunnel/direct mode) |
| `/agent disconnect` | Remove VM from bot |
| `/agent status` | Check agent connection status |
| `/agent list` | Show registered agents |

### Session Management
| Command | Description |
|---------|-------------|
| `/session-start` | Start session in dedicated thread |
| `/session-end` | End session and archive thread |
| `/resume` | Resume session in current thread |
| `/chat <message>` | Chat with AI mentor |
| `/set <dc> <domain> <user> <pass>` | Set session targets (ephemeral) |
| `/session` | Show session summary |

### Attack Commands
| Command | Description |
|---------|-------------|
| `/run <command>` | Run any OVT command on VM |
| `/stream <command>` | Live streaming output |
| `/doctor` | Run `ovt doctor` health check |
| `/kill <id>` | Kill running command |
| `/enum-all` | Full AD enumeration |
| `/kerberoast` | Kerberoasting attack |
| `/spray <password>` | Password spray with lockout check |
| `/adcs-scan` | ADCS vulnerability scan (ESC1-ESC13) |
| `/dump` | DCSync credential extraction |
| `/crack <hashfile>` | Crack hashes from loot |
| `/graph [query] [depth]` | Attack path graph from BloodHound |

### Monitoring
| Command | Description |
|---------|-------------|
| `/status` | VM CPU/RAM/disk/network/processes |
| `/loot` | Browse loot files (paginated) |
| `/readloot <path>` | Read loot file content |
| `/screenshot [analyze]` | Screenshot with optional AI vision |
| `/browse <url>` | Open URL in VM browser |

### AI & Analysis
| Command | Description |
|---------|-------------|
| `/ask <question>` | Ask about AD pentesting |
| `/analyze <cmd> <output>` | Paste OVT output for AI review |
| `/suggest` | AI suggests next best attack step |
| `/mistakes` | AI critiques your session |
| `/path <source> <target>` | Attack path analysis |
| `/bloodhound <file>` | BloodHound JSON analysis |
| `/search <query>` | Web search for vulns/exploits |
| `/cve <product>` | CVE lookup for Windows Server |
| `/fetch <url>` | Fetch and read a web page |

### Utilities
| Command | Description |
|---------|-------------|
| `/log` | Recent Sentinel events |
| `/history` | Session command history |
| `/info` | Bot info, version, credits |
| `/help [category]` | Detailed command reference |

---

## 4. Security

- **Token-authenticated WebSocket** — per-agent tokens generated by `/agent register`, validated via database lookup
- **WSS/TLS** — `wss://` end-to-end encryption for reverse and tunnel modes
- **Ephemeral responses** — agent interactions visible only to the user
- **Destructive confirmation** — dangerous commands (dump, spray, kerberoast) require button click confirmation
- **No shell injection** — process spawning uses argument arrays, not shell strings
- **Rate limiter** — 10 req/sec per user default
- **Path traversal protection** — loot file reads blocked on `..` or absolute paths
- **System-destructive command filtering** — `rm -rf /`, `dd`, `mkfs`, shutdown, etc. blocked behind confirmation
- **Surrogate character sanitization** — Discord JSON crash protection in embed builders

---

## 5. Kali VM Setup

### Network Configuration
| Adapter | Mode | Subnet | Purpose |
|---------|------|--------|---------|
| eth0 | NAT | 192.168.5.x (DHCP) | Internet access (tool downloads, bot connection) |
| eth1 | Host-only | 192.168.57.x | GOAD-Lab target network |
| eth2 | Host-only | 192.168.6.20/24 (static) | AD lab target network (DC at 192.168.6.10) |

### switch-network.sh
- `both` — NAT + AD lab simultaneously (recommended)
- `nat` — Internet only (download tools)
- `lab` — Lab only (full isolation)
- `status` — Show current network state
- Uses `nmcli` profile modification for persistent changes

### Agent Installation
```bash
curl -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
git clone https://github.com/Karmanya03/OVT-Sentinel
cd OVT-Sentinel/sentinel-agent
cargo build --release
```

### Agent Startup (Recommended)
```bash
sudo ./target/release/sentinel-agent \
  --token "<token>" \
  --connect-to-bot "wss://<app>.koyeb.app/agent-ws" \
  --fallback-tunnel \
  --bot-register-url "https://<app>.koyeb.app/register"
```

---

## 6. Deployment (Koyeb)

### koyeb.yaml
```yaml
name: ovt-sentinel
services:
  - name: sentinel-bot
    type: worker
    instance: micro
    dockerfile: sentinel-bot/Dockerfile
    ports:
      - port: 8000
        protocols: [http]
    envs:
      - key: SERVER_PORT
        value: "8000"
      - key: BOT_PUBLIC_URL
        value: https://<app>.koyeb.app/
      - key: USE_AGENT_TOOLS
        value: "true"
      - key: USE_WEB_SEARCH
        value: "true"
      - key: REQUIRE_CONFIRM_DESTRUCTIVE
        value: "true"
      - key: LAZY_AGENT_CONNECT
        value: "true"
      - key: LOG_LEVEL
        value: INFO

  - name: sentinel-db
    type: postgres
    version: "16"
```

### Required Environment Variables (Koyeb Dashboard)
- `DISCORD_TOKEN` — Discord bot token
- `DATABASE_URL` — PostgreSQL connection string
- `GROQ_API_KEY` — Groq API key (vision)
- `NVIDIA_API_KEY` — NVIDIA NIM API key (text)
- `SENTINEL_TOKEN` — Default bootstrap agent token

### Key Fixes Implemented
1. **Single port 8000** — merged healthcheck + registration + WS server onto one port
2. **Reverse-connect WS handler** — `asyncio.Future()` keeps connection alive after auth
3. **`process_request` returns `Response` namedtuple** — compatible with websockets 13+
4. **System prompt uses `SystemMessage`** — avoids f-string template parsing crash on literal `{}`
5. **Provider fallback chain** — all configured providers tried in priority order
6. **`/chat` handler has `defer()`** — prevents Discord 3-second interaction timeout
7. **`websockets.server` logger silenced** — suppresses noisy Koyeb healthcheck probe errors
8. **cloudflared SIGPIPE fix** — stderr continuously drained to prevent tunnel death
9. **Paginator** — replaces hard truncation with embed pagination + navigation buttons
10. **System prompt expanded 3x** — covers Web/App pentesting, Bug Bounty, CTF, Cloud, Mobile, OSS tools

---

## 7. System Prompt Scope

The AI mentor system prompt (~379 lines) covers:

- **Active Directory** — enumeration, kerberoasting, AS-REP roasting, ACL abuse, DCSync, delegation, ADCS ESC1-ESC13, Group Policy, trusts, forest attacks
- **Web/App Pentesting** — OWASP Top 10, SQLi, XSS, SSRF, deserialization, JWT, OAuth, SSTI, GraphQL, API testing
- **Bug Bounty** — recon pipeline, subdomain enumeration, platform-specific triage (HackerOne, Bugcrowd), report writing for max payout
- **Cloud Pentesting** — AWS IAM enumeration, S3 bucket attacks, Azure AD, GCP enumeration
- **Mobile Testing** — Android Frida setup, iOS Objection, API interception
- **CTF** — Reverse Engineering, Cryptography, Steganography, Forensics, PWN, Z3 constraint solving
- **Tool Ecosystem** — nmap, rustscan, bloodhound, certipy, impacket, responder, crackmapexec, chisel, ligolo-ng, evil-winrm, john, hashcat, hydra
