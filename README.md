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

<p align="center">AI-powered Discord bot for Overthrone (OVT) Active Directory testing. It connects to your attack VM over WebSocket, streams OVT commands, watches system resources and loot, and brings an AI red team brain that does not spill coffee on your keyboard. Mostly.</p>

<p align="center">
   <a href="#why-this-exists-short-version">What is this</a>
   · <a href="#quick-start">Install</a>
   · <a href="#">Wordlists</a>
   · <a href="#discord-commands">Commands</a>
   · <a href="#">Auto-Pwn Usage</a>
   · <a href="#architecture-neat-with-arrows">Architecture</a>
   · <a href="#what-it-does-without-the-hype">Features</a>
   · <a href="#">Examples</a>
   · <a href="#faq-funnier-helpful-slightly-unhinged">FAQ</a>
</p>

## Why This Exists (Short Version)

- You want to run OVT from Discord like a very calm villain.
- You want logs, loot, and live status without 17 terminals.
- You want an AI helper that is fast, cheap, and only a little sarcastic.

## Architecture (Neat, With Arrows)

```text
                +---------------------+
                |    Discord Client   |
                +---------------------+
                          |
                          | Slash Commands
                          v
                +---------------------+
                |    sentinel-bot     |
                |      (Python)       |
                +---------------------+
                   |        |        |
                   |        |        +---------------------+
                   |        |                              |
                   |        v                              v
                   |  +---------------------+     +---------------------+
                   |  | SQLite Session      |     | LLM Brain            |
                   |  | Memory              |     | (Gemini/Groq/etc.)   |
                   |  +---------------------+     +---------------------+
                   |
                   | WebSocket
                   v
                +---------------------+
                |   sentinel-agent    |
                |       (Rust)        |
                +---------------------+
                   |              |
                   |              +---------------------+
                   v                                    v
         +---------------------+              +---------------------+
         |   System Monitor    |              |    Loot Watcher     |
         +---------------------+              +---------------------+
                   |
                   v
         +---------------------+
         |   Overthrone (OVT)   |
         +---------------------+
```

## Quick Start

### 1) sentinel-agent (Attack VM)

```bash
cd sentinel-agent
cargo build --release
sudo cp target/release/sentinel-agent /usr/local/bin/

# Run (plain WebSocket)
sentinel-agent --bind 0.0.0.0:7331 --token "your-secure-token-here"

# Run (with TLS)
sentinel-agent --bind 0.0.0.0:7331 --tls --tls-cert cert.pem --tls-key key.pem --token "..."
```

### 2) sentinel-bot (Your Machine)

```bash
cd sentinel-bot
pip install -r requirements.txt

# Edit .env with your API keys
cp .env.example .env
# Set: DISCORD_TOKEN, GEMINI_API_KEY (or GROQ_API_KEY), AGENT_WS, SENTINEL_TOKEN
# (If .env is missing, it is auto-created from .env.example on first run)

python main.py
```

### 3) Docker (Because Buttons)

```bash
cd sentinel-bot
docker build -t sentinel-bot .
docker run --env-file ../.env sentinel-bot
```

## What It Does (Without the Hype)

- Streams OVT commands and output line by line.
- Keeps a session memory so you do not forget the chaos you created.
- Monitors VM health (CPU/RAM/disk/network) so your laptop does not cosplay a toaster.
- Watches loot folders and lets you browse or read files from Discord.
- Adds AI guidance for analysis, next steps, and mistakes.

## Discord Commands

| Command | Description |
|---------|-------------|
| `/info` | Show bot information, version, credits & quick links |
| `/help [category]` | Show detailed help for all commands |
| `/run <command>` | Run any OVT command with auto-AI analysis |
| `/stream <command>` | Live line-by-line output streaming |
| `/doctor` | Run `ovt doctor` health check |
| `/kill <id>` | Kill a running command |
| `/status` | VM CPU/RAM/disk/network status |
| `/loot` | Browse loot directory (paginated) |
| `/readloot <path>` | Read a loot file |
| `/session` | Show current session summary |
| `/log` | Show recent events |
| `/history` | Show command history |
| `/ask <question>` | Chat with the AD expert AI |
| `/analyze <command> <output>` | Paste OVT output for AI review |
| `/path <source> <target>` | Find attack path in graph |
| `/suggest` | Ask AI for the best next move |
| `/mistakes` | Review session mistakes |
| `/bloodhound <file>` | Analyze BloodHound JSON with AI |
| `/screenshot [analyze]` | VM screenshot with optional AI vision analysis |
| `/search <query>` | Search the web for vulnerabilities/exploits |
| `/kerberoast` | Kerberoasting shortcut |
| `/spray <password>` | Password spray with lockout check |
| `/adcs-scan` | ADCS vulnerability scan shortcut |
| `/crack <hashfile>` | Crack hashes from loot dir |

## LLM Providers (Free Tier)

Set `LLM_PROVIDER` in `.env` to choose:

| Provider | API Key Env Var | Model | Free Tier |
|----------|----------------|-------|-----------|
| **Gemini** (default) | `GEMINI_API_KEY` | `models/gemini-2.0-flash` | 60 req/min, 1500/day |
| **Groq** | `GROQ_API_KEY` | `llama-3.3-70b-versatile` | 30 req/min (70B) |
| **SambaNova** | `SAMBANOVA_API_KEY` | `Meta-Llama-3.1-70B-Instruct` | Free, rate-limited |
| **Cerebras** | `CEREBRAS_API_KEY` | `llama3.1-70b` | Free, rate-limited |
| **OpenAI** | `OPENAI_API_KEY` | `gpt-4o-mini` | Paid |
| **Ollama** (local) | — | `llama3.1:70b` | Free, local |

## Security (Yes, It Has That)

- Token-authenticated WebSocket between bot and agent.
- TLS support for encrypted connections (`wss://`).
- Discord user/guild/channel allowlists.
- Destructive command confirmation buttons.
- No shell injection (process spawning uses argument arrays).
- Config validation on startup with fast, loud errors.
- Token bucket rate limiter per user (10 req/sec default).
- Automatic findings logging (Krb hashes, NTLM hashes, ADCS vulns, delegation).
- Web search + fetch for live vulnerability research.
- AI vision screenshot analysis (Gemini).
- Built-in CVE database for WS 2019/2022/2025.
- Traditional tool knowledge (Mimikatz, Impacket, BloodHound, Certipy, etc.).

## Testing

```bash
cd sentinel-bot
pip install -r requirements.txt
python -m pytest tests/ -v
```

## FAQ (Funnier, Helpful, Slightly Unhinged)

**Q: Is this a bot, an agent, or a tiny gremlin?**
A: Yes. The bot handles Discord, the agent lives on the VM, and the gremlin is the thing that renames your log files when you're not looking.

**Q: Do I need paid LLMs?**
A: Not at all. Free tiers work fine. Paid LLMs = better jokes and fewer 'are you sure?' moments.

**Q: Why are there two components?**
A: Division of labor. `sentinel-bot` talks to Discord and humans. `sentinel-agent` runs on the VM and whispers to OVT. Keeps responsibilities tidy and blame traceable.

**Q: Will this run random shell commands and fry my box?**
A: No randomness. Commands are spawned with safe arg arrays. It will not summon a dragon unless you explicitly type `/run dragon --force`.

**Q: Can I run this on Windows or my toaster?**
A: `sentinel-bot` is Python — it runs on Windows, macOS, Linux. `sentinel-agent` is Rust — target your VM OS. Toaster support is experimental.

**Q: Is this legal?**
A: This tool is for authorized testing only. Use responsibly. If you're unsure, ask your lawyer or the nearest ethics committee (or both).

**Q: Where are logs and loot stored?**
A: Loot and logs live on the agent's `loot/` and `logs/` directories by default. Check the agent config or `/readloot` if you prefer Discord drama over file browsing.

**Q: Can the AI take actions on its own?**
A: No. The AI suggests and explains. You click the buttons. You remain the decision-maker and the person to blame.

**Q: How do I contribute?**
A: Fork, make a PR, add tests, and write clever commit messages. Bonus points for ASCII art and unit tests that include bad puns.

**Q: I broke something—real panic level.**
A: Step 1: breathe. Step 2: run `/doctor`. Step 3: check `sentinel-agent` logs. Step 4: blame the gremlin, then fix it.

**Q: Any tips for keeping my VM alive?**
A: Don't run multiple `/enum-all` commands in a row. Give your VM water, CPU breaks, and dignity.
