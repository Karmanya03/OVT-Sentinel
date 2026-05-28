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

### 3. Generate Token & Get Your Command

In any channel the bot can see, type `/agent register`:

```
/agent register tunnel:True label:Kali-VM
```

| Field | What it does |
|-------|-------------|
| `tunnel` | `True` for auto-tunnel via bore, `False` for direct connection |
| `label` | Friendly name for your VM (optional) |

The bot replies with your token and the exact command to run on Kali:

```
📝 Agent Token Generated

Install ngrok (one-time): curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | ...

Run on Kali:
sentinel-agent --token "f439a7b3..." --tunnel

Token: f439a7b3...
Keep this secret!
```
🚇 TUNNEL ACTIVE: ws://bore.pub:22698
```

### 4. Run the Agent on Kali

Copy-paste the command into your Kali terminal:

```bash
# First-time ngrok setup (free account at https://dashboard.ngrok.com/signup)
ngrok config add-authtoken YOUR_TOKEN

./target/release/sentinel-agent --token "f439a7b3..." --tunnel
```

The agent prints a public tunnel URL:
```
🚇 TUNNEL ACTIVE: ws://0.tcp.ngrok.io:12345
```

### 5. Connect in Discord

Once the agent is running, connect to it with:

```
/agent connect ws_url:ws://0.tcp.ngrok.io:12345
```

The bot auto-detects it's a tunnel connection.

### 6. Start Chatting

```
/chat enumerate the domain
/run enum-all
/screenshot
```

Everything runs on **your** VM. You're done.

---

### Alternative: Direct Connection (no tunnel)

If your Kali has a public IP:

1. `/agent register tunnel:False label:Kali-VM`
2. On Kali: `./target/release/sentinel-agent --token "..." --bind 0.0.0.0:7331`
3. `/agent connect ws_url:ws://YOUR_PUBLIC_IP:7331`

### Alternative: WireGuard Mesh

For air-gapped Kali that connects via WireGuard to a relay VPS:

1. Set up WireGuard between Kali and a relay VPS
2. On the relay VPS, forward port 7331 to Kali's WireGuard IP:
   `iptables -t nat -A PREROUTING -p tcp --dport 7331 -j DNAT --to-destination 10.0.0.2:7331`
3. `/agent register tunnel:False label:Kali-VM`
4. On Kali: `./target/release/sentinel-agent --token "..." --wireguard /etc/wireguard/ad_lab.conf`
5. `/agent connect ws_url:ws://RELAY_VPS_IP:7331`
/agent connect tunnel:True label:Kali-VM
```

| Field | What it does |
|-------|-------------|
| `tunnel` | `True` for auto-tunnel via bore, `False` for direct connection |
| `label` | Friendly name for your VM (optional) |
| `ws_url` | Only needed for direct connection (when `tunnel: False`) |
| `token` | Leave blank — bot generates one automatically |

The bot replies with the exact command to run on your Kali VM:

```
📝 Agent Registered (Offline)

Quick start (auto-tunnel):
```
# Install bore (one-time)
cargo install bore-cli

sentinel-agent --token "f439a7b3..." --tunnel --bot-register-url "https://your-app.koyeb.app/register"
```
No /agent connect needed — the bot will receive the tunnel URL automatically.
```

### 4. Run the Command on Kali

Copy-paste the command from Discord into your Kali terminal:

```bash
# Install bore (one-time only)
cargo install bore-cli

# Run the agent (copy from Discord)
./target/release/sentinel-agent --token "f439a7b3..." --tunnel
```

The agent creates a tunnel, POSTs its URL to the bot, and you're connected.

### 5. Start Chatting

```
/chat enumerate the domain
/run enum-all
/screenshot
```

Everything runs on **your** VM. You're done.

---

### Alternative: Direct Connection (no tunnel)

If your Kali has a public IP:

```
/agent connect ws_url:ws://YOUR_PUBLIC_IP:7331 tunnel:False label:Kali-VM
```

Bot replies with a plain command to start the agent directly.

### Alternative: WireGuard Mesh

For air-gapped Kali that connects via WireGuard to a relay VPS:

1. Set up WireGuard between Kali and a cheap VPS
2. On the VPS, forward port 7331 to Kali's WireGuard IP:
   `iptables -t nat -A PREROUTING -p tcp --dport 7331 -j DNAT --to-destination 10.0.0.2:7331`
3. On the relay VPS, set `BOT_PUBLIC_URL=https://relay-vps-ip:7331`
4. In Discord: `/agent connect tunnel:False ws_url:ws://relay-vps-ip:7331 label:Kali-VM`

The agent command from Discord:
```
sentinel-agent --token "..." --wireguard /etc/wireguard/ad_lab.conf
```

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
