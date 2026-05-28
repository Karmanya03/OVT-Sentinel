# OVT-Sentinel

OVT-Sentinel is an AI-powered Discord bot built for Overthrone (OVT) Active Directory penetration testing. Instead of having to SSH into your Kali VM every time you want to run a command, you just invite the bot to your server, register your VM with a single command, and control everything from Discord. The AI mentor sitting behind the bot knows AD attacks, web pentesting, bug bounty hunting, cloud security, mobile testing, and CTFs inside out — it will suggest the next move, analyze your output, catch your mistakes, and even look at your VM screen.

The whole setup is designed so you never have to mess with IP addresses, open inbound ports, or configure tunnels manually. Your Kali VM lives behind NAT on an isolated lab network, but it reaches out to the bot on its own, and everything just works.

---

## How the Pieces Fit Together

There are two main components. The bot runs on Koyeb's free tier — it's the Discord-facing part that handles slash commands, talks to the AI models, and routes commands to your VM. The agent is a Rust binary that runs on your Kali machine. It's the muscle — it executes OVT commands, takes screenshots, monitors system health, and reports back.

The bot used to run separate servers for healthchecks and WebSocket connections, but we merged everything onto a single port 8000. One port handles Koyeb's liveness probes, agent tunnel registration, and the WebSocket endpoint where agents connect. It makes deployment simpler and avoids the headache of Koyeb only exposing one port externally.

For connectivity, the recommended approach is reverse-connect mode. The agent reaches out to the bot over WSS (port 443), so it works even when Kali is behind strict NAT or a corporate firewall. No tunnel binary needed, no DNS trickery. If the reverse connection fails, there's an automatic fallback that spins up a cloudflared tunnel instead. You can also go pure tunnel mode, direct WebSocket if Kali has a public IP, or WireGuard for air-gapped labs with a relay VPS.

The agent itself is written in Rust and bundles a command executor that spawns OVT commands with safe argument arrays (no shell injection), a system monitor for CPU/RAM/disk/network stats, a loot watcher to browse collected files, and a browser controller for screenshots and URL navigation.

---

## The AI Stack

For text generation, the priority chain is NVIDIA NIM (Mistral Large 3 675B) first, then Cerebras (Qwen-3-235B), then Groq (Llama 4 Scout), then Gemini (2.5 Flash), then MiniMax, OpenAI, SambaNova, and finally Ollama for local inference. For image analysis, the same OpenAI-compatible providers are tried in order, with Gemini as the last resort.

NVIDIA NIM is the star here — it's completely free, no credit card required, roughly 40 requests per minute with no token caps, and the Mistral Large 3 model handles both text and vision. You sign up at build.nvidia.com, get an `nvapi-...` key, and that single key unlocks both NVIDIA and MiniMax providers in the fallback chain. Groq with Llama 4 Scout handles vision tasks as a secondary option. Gemini sits behind both as a fallback.

The system prompt that powers the AI mentor is around 379 lines and covers Active Directory enumeration and attacks (kerberoasting, AS-REP roasting, ACL abuse, DCSync, delegation, ADCS ESC1-ESC13, Group Policy, trusts, forest attacks), web and application pentesting (OWASP Top 10, SQLi, XSS, SSRF, deserialization, JWT, OAuth, SSTI, GraphQL), bug bounty methodology (recon pipeline, subdomain enumeration, platform-specific triage, report writing for max payout), cloud pentesting (AWS IAM, S3, Azure AD, GCP), mobile testing (Android Frida, iOS Objection), CTF categories (RE, crypto, stego, forensics, PWN, Z3), and a comprehensive tool ecosystem reference.

---

## What You Can Do From Discord

The bot has commands organized into a few categories. Agent commands let you register your Kali VM and generate a per-agent token, connect or disconnect it, and check its status. Session commands start a dedicated thread where all your command output appears, let you chat with the AI, and save everything for later review.

Attack commands run OVT operations directly on your VM — full AD enumeration, kerberoasting, password spraying with automatic lockout policy checks, ADCS vulnerability scanning, DCSync, hash cracking, and attack path graphing from BloodHound data. There's a live streaming mode that shows output line by line as it comes in.

Monitoring commands check VM health stats, browse and read loot files, take screenshots with optional AI vision analysis, and open URLs in the VM browser. AI and analysis commands let you ask questions about AD pentesting, paste command output for automatic review, get the next best move suggested, review your session for mistakes, analyze attack paths, and run BloodHound JSON analysis. Utility commands search the web for vulnerabilities, look up CVEs by Windows Server version, fetch web pages, and review event logs.

---

## Security

Connections between the agent and bot use WSS with TLS encryption end to end. Each agent authenticates with a per-agent token generated by `/agent register` and validated against the database on connection. All agent interactions are ephemeral — only you see them. Destructive operations like DCSync, kerberoasting, and password spraying require an explicit button click confirmation before they execute. Process spawning uses argument arrays instead of shell strings, so there's no shell injection risk. A rate limiter caps requests at ten per second per user by default. Loot file reads block path traversal attempts. System-destructive shell commands like `rm -rf /` and `dd` are filtered behind a second confirmation layer. Surrogate characters in AI output are sanitized before they reach Discord to prevent JSON encoding crashes.

---

## Kali VM Setup

The Kali VM typically has three network adapters. Eth0 runs on NAT with DHCP for internet access. Eth1 connects to the GOAD-Lab target network. Eth2 uses a static IP for the AD lab network where the domain controller lives. There's a `switch-network.sh` script that toggles between NAT-only, lab-only, and both modes simultaneously using `nmcli` for persistent profile changes.

To install the agent, you run the standard Rust setup, clone the repo, and build with cargo. Then you register your VM through Discord with `/agent register`, pick reverse mode, and the bot gives you a token and the exact command to run on Kali. The recommended startup command includes the reverse-connect flag, the fallback tunnel flag in case the bot is unreachable, and the register URL for automatic tunnel registration.

---

## Deployment

The bot deploys on Koyeb as a worker service with a single port 8000 exposed. A PostgreSQL 16 database handles sessions, chat history, agent registrations, and findings. The required environment variables are the Discord token, database URL, Groq API key for vision, NVIDIA API key for text, and the Sentinel token for bootstrap agent registration.

A bunch of fixes went into making this work reliably. The healthcheck, registration, and WebSocket server were merged onto one port. The reverse-connect handler uses `asyncio.Future()` to keep the WebSocket connection alive after authentication instead of closing it immediately. The system prompt now uses a `SystemMessage` object instead of an f-string template so that literal curly braces in the prompt text don't crash LangChain's parser. The `/chat` handler calls `interaction.response.defer()` upfront to prevent Discord's three-second interaction timeout. The websockets server logger is silenced to stop Koyeb's healthcheck probe errors from flooding the logs. Cloudflared's stderr is continuously drained to prevent SIGPIPE from killing the tunnel. Long AI responses use embed pagination with navigation buttons instead of hard truncation.
