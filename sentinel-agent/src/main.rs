use anyhow::Result;
use clap::Parser;
use std::sync::Arc;
use tokio::sync::Mutex;

mod auth;
mod browser;
mod executor;
mod loot_watcher;
mod monitor;
mod protocol;
mod tunnel;
use crate::tunnel::register_tunnel;
mod wireguard;
mod ws_client;
mod ws_server;

#[derive(Parser, Debug)]
#[command(name = "sentinel-agent", about = "OVT-Sentinel VM monitoring agent")]
pub struct Args {
    /// WebSocket bind address
    #[arg(long, default_value = "0.0.0.0:7331")]
    pub bind: String,

    /// Authentication token (use a long random string)
    #[arg(long, env = "SENTINEL_TOKEN")]
    pub token: String,

    /// Path to the OVT binary
    #[arg(long, default_value = "/usr/local/bin/ovt")]
    pub ovt_path: String,

    /// Directory to watch for new loot files
    #[arg(long, default_value = "./loot")]
    pub loot_dir: String,

    /// Enable TLS (requires --tls-cert and --tls-key)
    #[arg(long)]
    pub tls: bool,

    /// Path to TLS certificate file (PEM)
    #[arg(long, requires = "tls")]
    pub tls_cert: Option<String>,

    /// Path to TLS private key file (PEM)
    #[arg(long, requires = "tls")]
    pub tls_key: Option<String>,

    /// Auto-create a public tunnel via Cloudflare (requires `cloudflared` installed)
    /// Uses Cloudflare Quick Tunnel — no account needed, just install cloudflared.
    #[arg(long)]
    pub tunnel: bool,

    /// Bot HTTP registration URL (e.g. https://app.koyeb.app/register)
    /// Agent will POST its tunnel URL here on startup for auto-discovery
    #[arg(long, env = "BOT_REGISTER_URL")]
    pub bot_register_url: Option<String>,

    /// WireGuard config file path (e.g. /etc/wireguard/ad_lab.conf)
    /// Brings up the interface on start, tears down on shutdown
    #[arg(long)]
    pub wireguard: Option<String>,

    /// Reverse-connect mode: connect to the bot's WebSocket server as a client
    /// (e.g. wss://my-bot.koyeb.app:8002/agent-ws).
    /// No tunnel needed — agent reaches out to the bot.
    #[arg(long, env = "CONNECT_TO_BOT")]
    pub connect_to_bot: Option<String>,

    /// If reverse connect fails, fall back to cloudflared tunnel + WS server.
    /// Requires `--connect-to-bot` and `cloudflared` installed.
    #[arg(long)]
    pub fallback_tunnel: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

    let args = Args::parse();
    tracing::info!("OVT-Sentinel agent starting on {}", args.bind);

    let shutdown = Arc::new(Mutex::new(false));

    // Signal handler for graceful shutdown
    #[cfg(unix)]
    {
        let shutdown_handle = shutdown.clone();
        tokio::spawn(async move {
            let mut term =
                tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                    .expect("failed to create SIGTERM handler");
            let mut int = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::interrupt())
                .expect("failed to create SIGINT handler");

            tokio::select! {
                _ = term.recv() => tracing::info!("Received SIGTERM, shutting down..."),
                _ = int.recv() => tracing::info!("Received SIGINT, shutting down..."),
            }

            let mut guard = shutdown_handle.lock().await;
            *guard = true;
        });
    }
    #[cfg(windows)]
    {
        let shutdown_handle = shutdown.clone();
        tokio::spawn(async move {
            tokio::select! {
                _ = tokio::signal::ctrl_c() => tracing::info!("Received Ctrl+C, shutting down..."),
            }

            let mut guard = shutdown_handle.lock().await;
            *guard = true;
        });
    }

    if let Some(wg_config) = &args.wireguard {
        let wg = std::sync::Arc::new(wireguard::WireGuard::new(wg_config));
        match wg.up().await {
            Ok(ip) => {
                tracing::info!("🔒 WireGuard mesh active — interface IP: {}", ip);
                println!("\n🔒 WIREGUARD ACTIVE: {}\n", ip);
            }
            Err(e) => {
                tracing::error!("WireGuard failed: {}", e);
                println!("\n❌ WireGuard failed: {}\n", e);
            }
        }
        let wg_clone = wg.clone();
        let shutdown_wg = shutdown.clone();
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(std::time::Duration::from_millis(500)).await;
                if *shutdown_wg.lock().await {
                    let _ = wg_clone.down().await;
                    break;
                }
            }
        });
    }

    // ── Try reverse-connect mode first (--connect-to-bot) ──
    let mut needs_tunnel = args.tunnel;
    if let Some(bot_ws_url) = &args.connect_to_bot {
        tracing::info!("Reverse-connect mode: connecting to bot at {}", bot_ws_url);
        println!("\n🔗 Connecting to bot: {}\n", bot_ws_url);
        let reverse_executor = Arc::new(executor::CommandExecutor::new(args.ovt_path.clone()));
        let result = ws_client::connect_to_bot(
            bot_ws_url,
            &args.token,
            reverse_executor,
            args.loot_dir.clone(),
        )
        .await;
        match &result {
            Ok(()) => {
                tracing::info!("Disconnected from bot");
                return Ok(());
            }
            Err(e) => {
                if args.fallback_tunnel {
                    tracing::warn!(
                        "Reverse connect failed ({}), falling back to tunnel mode",
                        e
                    );
                    println!("\n⚠️ Reverse connect failed. Starting fallback tunnel...\n");
                    needs_tunnel = true;
                } else {
                    tracing::error!("Connection error: {}", e);
                    return result;
                }
            }
        }
    }

    // ── Start tunnel if needed (explicit --tunnel or fallback from reverse) ──
    let tunnel_url = if needs_tunnel {
        let port: u16 = args
            .bind
            .rsplit(':')
            .next()
            .unwrap_or("7331")
            .parse()
            .unwrap_or(7331);
        match tunnel::start_cloudflared_tunnel(port).await {
            Ok(tunnel) => {
                let url = tunnel.public_url().to_string();
                tracing::info!("🌐 Public tunnel: {} → ws://{}", url, args.bind);
                println!("\n🚇 TUNNEL ACTIVE: {}\n   Use this URL with /agent connect.\n", url);
                if let Some(register_url) = &args.bot_register_url {
                    match register_tunnel(register_url, &url, &args.token).await {
                        Ok(_) => tracing::info!("Registered tunnel URL with bot"),
                        Err(e) => tracing::warn!("Failed to register tunnel URL: {}", e),
                    }
                } else {
                    tracing::info!("No --bot-register-url set; skipping auto-registration.");
                    if args.fallback_tunnel {
                        println!("   Set BOT_PUBLIC_URL on the server for auto-registration,\n   or use /agent connect ws_url:<tunnel-url> to connect.\n");
                    } else {
                        println!("   Use /agent connect ws_url:<tunnel-url> to connect.\n");
                    }
                }
                Some(url)
            }
            Err(e) => {
                tracing::error!("Failed to start tunnel: {}", e);
                println!("\n❌ Cloudflare tunnel failed: {}\n   Falling back to direct connection only.\n", e);
                None
            }
        }
    } else {
        None
    };

    ws_server::run(args, shutdown, tunnel_url).await
}
