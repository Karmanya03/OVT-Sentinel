<div align="center">
   <img src="assets/OVT-Sentinel-Logo.png" alt="OVT-Sentinel Logo" width="420" />
</div>

<h1 align="center">OVT-Sentinel</h1>

<p align="center">
   <img src="https://img.shields.io/badge/release-v0.1.0-orange" alt="release" />
   <img src="https://img.shields.io/badge/license-MIT-blue" alt="license" />
   <img src="https://img.shields.io/badge/language-Rust-red" alt="rust" />
   <img src="https://img.shields.io/badge/component-Python-green" alt="python" />
   <img src="https://img.shields.io/badge/tests-pytest-yellow" alt="tests" />
</p>

<p align="center">AI-powered Discord bot for Overthrone (OVT) Active Directory testing. Invite the bot, run an agent on your Kali VM, and control everything from Discord.</p>

<p align="center">
   <a href="#get-started">Get Started</a>
   · <a href="#discord-commands">Commands</a>
   · <a href="#architecture">Architecture</a>
   · <a href="#what-it-does">Features</a>
   · <a href="#faq">FAQ</a>
</p>

## Get Started

### 1. Invite the Bot to Your Server

Click this link → pick your server → done:

```
https://discord.com/api/oauth2/authorize?client_id=1509111346824740964&permissions=1099858774022&scope=bot
```

No hosting, no config, no Discord Developer account needed.

### 2. Install the Agent on Your VM

Open a terminal on your Kali/attack VM and run:

```bash
curl -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
git clone https://github.com/Karmanya03/OVT-Sentinel
cd OVT-Sentinel/sentinel-agent
cargo build --release
```

### 3. Run the Agent — Pick Your Connection Mode

Choose the option that matches your Kali's network setup:

<details open>
<summary><b>🔄 A) Auto-tunnel (bore) — Kali has outbound internet</b></summary>

Works through NAT, host-only, VPNs — any setup where Kali can reach the internet.

```bash
# Install bore once
cargo install bore-cli

# Run with auto-tunnel + bot registration
./target/release/sentinel-agent \
  --token "your-secure-token" \
  --tunnel \
  --bot-register-url "https://your-app.koyeb.app/register"
```

Prints:
```
🚇 TUNNEL ACTIVE: ws://bore.pub:22698
[+] Registered tunnel URL with bot
```

**No `/agent connect` needed** — the bot already knows your address.
</details>

<details>
<summary><b>🔒 B) WireGuard mesh — Kali is isolated, connects via WireGuard to a relay</b></summary>

For truly air-gapped Kali that can only reach a WireGuard peer (e.g., a cheap VPS).

```bash
# On the VPS, forward port 7331 to Kali's WireGuard IP:
#   iptables -t nat -A PREROUTING -p tcp --dport 7331 -j DNAT --to-destination 10.0.0.2:7331

./target/release/sentinel-agent \
  --token "your-secure-token" \
  --wireguard /etc/wireguard/ad_lab.conf \
  --bot-register-url "https://your-app.koyeb.app/register" (Optional)
```

Prints:
```
🔒 WIREGUARD ACTIVE: 10.0.0.2
[+] Registered tunnel URL with bot
```

Agent auto-cleans up `wg-quick down` on shutdown.
</details>

<details>
<summary><b>🌐 C) Direct connection — Kali has a public IP</b></summary>

```bash
./target/release/sentinel-agent --token "your-secure-token"
```
</details>

### 4. Connect in Discord

**If you used `--bot-register-url`** (options A or B): skip this step — the bot already knows your URL.

**If you didn't** (option C or no `--bot-register-url`): type what the agent printed:

```
/agent connect ws://bore.pub:22698
```

The bot replies:
```
✅ Agent connected — Kali VM
```

### 5. Start Chatting

```
/chat enumerate the domain
/run enum-all
/screenshot
```

Everything runs on **your** VM. You're done.

---

## Discord Commands

| Category | Command | Description |
|----------|---------|-------------|
| **Agent** | `/agent connect <ws_url>` | Connect your attack VM to the bot |
| | `/agent disconnect` | Remove your VM from the bot |
| | `/agent status` | Check your agent connection status |
| | `/agent list` | Show your registered agents |
| **Info** | `/info` | Bot info, version & credits |
| | `/help [category]` | Detailed command reference |
| **Session** | `/session-start` | Start a session in a dedicated thread |
| | `/session-end` | End session & archive thread |
| | `/resume` | Resume session in current thread |
| | `/chat <message>` | Chat with the AI |
| | `/set <dc> <domain> <user> <pass>` | Set session targets (ephemeral) |
| | `/session` | Show session summary |
| **Attack** | `/run <command>` | Run any OVT command |
| | `/stream <command>` | Live streaming output |
| | `/doctor` | Run `ovt doctor` health check |
| | `/kill <id>` | Kill a running command |
| | `/enum-all` | Full AD enumeration |
| | `/kerberoast` | Kerberoasting |
| | `/spray <password>` | Password spray with lockout check |
| | `/adcs-scan` | ADCS vulnerability scan |
| | `/dump` | DCSync credential extraction |
| | `/crack <hashfile>` | Crack hashes from loot |
| **Monitor** | `/status` | VM CPU/RAM/disk/network status |
| | `/loot` | Browse loot files (paginated) |
| | `/readloot <path>` | Read a loot file |
| | `/screenshot [analyze]` | Screenshot with optional AI vision |
| | `/browse <url>` | Open URL in VM browser |
| **AI** | `/ask <question>` | Ask about AD pentesting |
| | `/analyze <cmd> <output>` | Paste OVT output for AI review |
| | `/suggest` | AI suggests the next best move |
| | `/mistakes` | AI critiques your session |
| | `/path <source> <target>` | Attack path analysis |
| | `/bloodhound <file>` | BloodHound JSON analysis |
| **Utilities** | `/search <query>` | Web search for vulns/exploits |
| | `/cve <product>` | CVE lookup for Windows Server |
| | `/log` | Recent Sentinel events |
| | `/history` | Session command history |

## Architecture

```text
                     One bot, many agents

        +---------------------+
        |    Discord Client   |
        +---------------------+
                  |
                  | Slash Commands
                  v
        +---------------------+
        |    sentinel-bot     |
        |   (hosted once)     |
        +---------------------+
         |      |       |    
         |      |       +-- PostgreSQL
         |      |           (sessions, agents,
         |      |            chat history)
         |      |
         |      +-- LLM Brain (Gemini / Groq /
         |           OpenAI / SambaNova / Ollama)
         |
    ┌────┴────┬────┬────┐    WebSocket (per user)
   Agent A  Agent B  Agent C  ...
   (user1)  (user2)  (user3)
      |        |        |
   Kali VM  Kali VM  Kali VM
```

## What It Does

- **One bot, shared by everyone** — invite once, no app creation per user
- **Per-user agent** — each user registers their own Kali VM via `/agent connect`
- **OVT command execution** — run Overthrone attacks from Discord
- **Live streaming** — see command output in real-time
- **Thread-based sessions** — dedicated workspace per session
- **AI chat + analysis** — multi-provider LLM with agentic tool calling
- **VM monitoring** — CPU, RAM, disk, processes from Discord
- **Loot management** — browse, read, and analyze collected files
- **Screenshots + browser** — see what's on the VM screen

## LLM Providers (Free & Paid)

| Provider | API Key Env Var | Default Model | Free Tier / Limits |
|----------|----------------|---------------|-------------------|
| **Cerebras** | `CEREBRAS_API_KEY` | `Qwen-3-235B-Instruct` | Free, rate-limited |
| **Groq** | `GROQ_API_KEY` | `meta-llama/llama-4-scout-17b-16e-instruct` | 30 req/min (70B), **supports images** |
| **Gemini** | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `models/gemini-2.5-flash` | 60 req/min, 1500/day, **supports images** |
| **NVIDIA NIM** | `NVIDIA_API_KEY` | `mistralai/mistral-large-3-675b-instruct-2512` | ~40 RPM (no token limit), free, no CC |
| **MiniMax** (via NVIDIA) | `NVIDIA_API_KEY` | `minimaxai/minimax-m2.7` | Same, chained after NVIDIA |
| **OpenAI** | `OPENAI_API_KEY` | `gpt-4o-mini` | Paid |
| **SambaNova** | `SAMBANOVA_API_KEY` | `Meta-Llama-3.1-70B-Instruct` | Free, rate-limited |
| **Ollama** (local) | — | `llama3.1:70b` | Free, local |

Multiple providers auto-chain as fallback in priority order. No need to set `LLM_PROVIDER` — just add API keys.

**NVIDIA NIM details**: Sign up free at [build.nvidia.com](https://build.nvidia.com) (no credit card). Get an `nvapi-...` key. This single key unlocks two fallback providers: **NVIDIA** (Mistral Large 3 675B) and **MiniMax** (M2.7 230B) — both chain automatically. 100+ models available. **Only limit is ~40 requests/minute** — no token/credit caps. Can request 200 RPM upgrade. OpenAI-compatible API.

### Quick Koyeb Env Example

```text
DISCORD_TOKEN=...
DATABASE_URL=...
AGENT_WS=ws://bore.pub:22698
SENTINEL_TOKEN=...
GROQ_API_KEY=gsk_...
CEREBRAS_API_KEY=csk_...
NVIDIA_API_KEY=nvapi-...
```

No `LLM_PROVIDER` needed — fallback chain handles it.

## Security

- Token-authenticated WebSocket between bot and agent
- TLS support for encrypted connections (`wss://`)
- All agent commands are ephemeral (only you see them)
- Destructive command confirmation buttons
- No shell injection (process spawning uses argument arrays)
- Rate limiter per user (10 req/sec default)
- Web search + fetch for live vulnerability research
- AI vision screenshot analysis (Gemini or Groq Llama 4)
- Auto-tunnel with `--tunnel` flag (bore.pub) for zero-config remote access

## Testing

```bash
cd sentinel-bot
pip install -r requirements.txt
python -m pytest tests/ -v
```

```bash
cd sentinel-agent
cargo test
```

## FAQ

**Q: Do I need to host the bot?**
A: No. Someone already hosts it. Just invite it to your server and connect your VM with `/agent connect`.

**Q: Do I need a Discord Developer account?**
A: No. The bot is already created. You just need the invite link.

**Q: Do I need paid LLMs?**
A: No. Free tiers work fine (Gemini, Groq, SambaNova, Cerebras).

**Q: Is this a bot, an agent, or a tiny gremlin?**
A: Yes. The bot handles Discord, the agent lives on your VM, and the gremlin is the thing that renames your log files when you're not looking.

**Q: Will this run random shell commands and fry my box?**
A: No randomness. Commands are spawned with safe arg arrays. Destructive operations need your explicit confirmation.

**Q: Is this legal?**
A: This tool is for authorized testing only. Use responsibly.

**Q: How do I contribute?**
A: Fork, make a PR, add tests, and write clever commit messages. Bonus points for ASCII art and unit tests that include bad puns.

**Q: Any tips for keeping my VM alive?**
A: Don't run multiple `/enum-all` commands in a row. Give your VM water, CPU breaks, and dignity.
