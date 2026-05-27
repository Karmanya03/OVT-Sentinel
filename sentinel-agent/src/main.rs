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

    ws_server::run(args, shutdown).await
}
