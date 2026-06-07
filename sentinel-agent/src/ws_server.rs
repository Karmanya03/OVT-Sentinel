use crate::auth::verify_token;
use crate::browser::{browse_url, take_screenshot};
use crate::executor::CommandExecutor;
use crate::loot_watcher::{list_loot, read_loot_file, start_loot_watcher};
use crate::monitor::SystemMonitor;
use crate::protocol::{AgentMessage, BotMessage};
use anyhow::{Context, Result};
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use tokio::net::TcpListener;
use tokio::sync::{Mutex, Notify};
use tokio_native_tls::TlsAcceptor;
use tokio_tungstenite::accept_async;
use tokio_tungstenite::tungstenite::Message;

pub async fn run(args: crate::Args, shutdown: Arc<Mutex<bool>>, tunnel_url: Option<String>) -> Result<()> {
    let listener = TcpListener::bind(&args.bind).await?;
    let shutdown_notify = Arc::new(Notify::new());

    let tls_acceptor = if args.tls {
        let cert_pem = std::fs::read(
            args.tls_cert
                .as_ref()
                .context("--tls-cert required when --tls is set")?,
        )
        .context("failed to read TLS cert")?;
        let key_pem = std::fs::read(
            args.tls_key
                .as_ref()
                .context("--tls-key required when --tls is set")?,
        )
        .context("failed to read TLS key")?;

        let identity = native_tls::Identity::from_pkcs8(&cert_pem, &key_pem)
            .context(
                "failed to create TLS identity from PKCS#8 PEM. \
                 Ensure your key is in PKCS#8 format (use `openssl pkcs8 -topk8 -in key.pem -out key_pkcs8.pem -nocrypt`)"
            )?;
        let acceptor =
            native_tls::TlsAcceptor::new(identity).context("failed to create TLS acceptor")?;
        let acceptor = TlsAcceptor::from(acceptor);
        tracing::info!("TLS enabled on wss://{}", args.bind);
        Some(acceptor)
    } else {
        tracing::info!("Listening on ws://{}", args.bind);
        None
    };

    let executor = Arc::new(CommandExecutor::new(args.ovt_path.clone()));
    let loot_dir = args.loot_dir.clone();

    // Shutdown monitor
    let shutdown_clone = shutdown.clone();
    let notify_clone = shutdown_notify.clone();
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;
            if *shutdown_clone.lock().await {
                tracing::info!("Shutdown requested, stopping accept loop...");
                notify_clone.notify_one();
                break;
            }
        }
    });

    loop {
        tokio::select! {
            accept_result = listener.accept() => {
                let (stream, addr) = match accept_result {
                    Ok(v) => v,
                    Err(e) => {
                        tracing::error!("Accept failed: {}", e);
                        continue;
                    }
                };
                tracing::info!("New connection from {}", addr);
                let token = args.token.clone();
                let executor = executor.clone();
                let loot_dir = loot_dir.clone();
                let tls_acceptor = tls_acceptor.clone();
                let shutdown = shutdown.clone();
                let tunnel = tunnel_url.clone();

                tokio::spawn(async move {
                    let result = if let Some(acceptor) = tls_acceptor {
                        match acceptor.accept(stream).await {
                            Ok(tls_stream) => {
                                match accept_async(tls_stream).await {
                                    Ok(ws) => handle_connection(ws, token, executor, loot_dir, shutdown, tunnel).await,
                                    Err(e) => Err(anyhow::anyhow!("WebSocket handshake over TLS failed: {}", e)),
                                }
                            }
                            Err(e) => Err(anyhow::anyhow!("TLS handshake failed: {}", e)),
                        }
                    } else {
                        match accept_async(stream).await {
                            Ok(ws) => handle_connection(ws, token, executor, loot_dir, shutdown, tunnel).await,
                            Err(e) => Err(anyhow::anyhow!("WebSocket handshake failed: {}", e)),
                        }
                    };
                    if let Err(e) = result {
                        tracing::error!("Connection error from {}: {}", addr, e);
                    }
                });
            }
            _ = shutdown_notify.notified() => {
                tracing::info!("Shutting down TCP listener, killing {} running processes...", executor.active_count().await);
                executor.kill_all().await;
                break;
            }
        }
    }

    tracing::info!("Agent shut down complete.");
    Ok(())
}

async fn handle_connection<S>(
    ws_stream: tokio_tungstenite::WebSocketStream<S>,
    token: String,
    executor: Arc<CommandExecutor>,
    loot_dir: String,
    _shutdown: Arc<Mutex<bool>>,
    tunnel_url: Option<String>,
) -> Result<()>
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin + Send + 'static,
{
    let (ws_tx, mut ws_rx) = ws_stream.split();
    let ws_tx = Arc::new(Mutex::new(ws_tx));

    if let Ok(mut loot_rx) = start_loot_watcher(loot_dir.clone()) {
        let tx = ws_tx.clone();
        tokio::spawn(async move {
            while let Some(msg) = loot_rx.recv().await {
                if let Ok(s) = serde_json::to_string(&msg) {
                    let _ = tx.lock().await.send(Message::Text(s.into())).await;
                }
            }
        });
    }

    // Require first message to be Auth
    if let Some(msg) = ws_rx.next().await {
        let msg = msg?;
        if let Message::Text(txt) = msg {
            match serde_json::from_str::<BotMessage>(&txt) {
                Ok(BotMessage::Auth { token: t }) => {
                    if verify_token(&token, &t) {
                        let auth = AgentMessage::AuthResult {
                            success: true,
                            reason: None,
                            tunnel_url: tunnel_url.clone(),
                        };
                        let s = serde_json::to_string(&auth)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    } else {
                        let auth = AgentMessage::AuthResult {
                            success: false,
                            reason: Some("invalid token".into()),
                            tunnel_url: None,
                        };
                        let s = serde_json::to_string(&auth)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                        return Ok(());
                    }
                }
                _ => {
                    let auth = AgentMessage::AuthResult {
                        success: false,
                        reason: Some("expected auth first".into()),
                        tunnel_url: None,
                    };
                    let s = serde_json::to_string(&auth)?;
                    ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    return Ok(());
                }
            }
        }
    } else {
        return Ok(());
    }

    let mut monitor = SystemMonitor::new();

    while let Some(msg) = ws_rx.next().await {
        let msg = msg?;
        if let Message::Text(txt) = msg {
            match serde_json::from_str::<BotMessage>(&txt) {
                Ok(BotMessage::RunCommand {
                    request_id,
                    command,
                    timeout_secs,
                }) => {
                    let tx = ws_tx.clone();
                    let req = request_id.clone();
                    let mut rx = match executor
                        .spawn_command(request_id.clone(), command, timeout_secs)
                        .await
                    {
                        Ok(r) => r,
                        Err(e) => {
                            let err = AgentMessage::Error {
                                message: format!("spawn error: {}", e),
                                request_id: Some(req),
                            };
                            let s = serde_json::to_string(&err)?;
                            tx.lock().await.send(Message::Text(s.into())).await?;
                            continue;
                        }
                    };

                    tokio::spawn(async move {
                        while let Some(msg) = rx.recv().await {
                            if let Ok(s) = serde_json::to_string(&msg) {
                                let _ = tx.lock().await.send(Message::Text(s.into())).await;
                            }
                        }
                    });
                }
                Ok(BotMessage::RunShellCommand {
                    request_id,
                    command,
                    timeout_secs,
                }) => {
                    let tx = ws_tx.clone();
                    let req = request_id.clone();
                    let mut rx = match executor
                        .spawn_shell_command(request_id.clone(), command, timeout_secs)
                        .await
                    {
                        Ok(r) => r,
                        Err(e) => {
                            let err = AgentMessage::Error {
                                message: format!("shell spawn error: {}", e),
                                request_id: Some(req),
                            };
                            let s = serde_json::to_string(&err)?;
                            tx.lock().await.send(Message::Text(s.into())).await?;
                            continue;
                        }
                    };

                    tokio::spawn(async move {
                        while let Some(msg) = rx.recv().await {
                            if let Ok(s) = serde_json::to_string(&msg) {
                                let _ = tx.lock().await.send(Message::Text(s.into())).await;
                            }
                        }
                    });
                }
                Ok(BotMessage::KillCommand { request_id }) => {
                    let killed = executor.kill(&request_id).await.unwrap_or(false);
                    if killed {
                        let k = AgentMessage::CommandKilled { request_id };
                        let s = serde_json::to_string(&k)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    } else {
                        let err = AgentMessage::Error {
                            message: "kill failed or not found".into(),
                            request_id: Some(request_id),
                        };
                        let s = serde_json::to_string(&err)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    }
                }
                Ok(BotMessage::GetStatus) => match monitor.snapshot() {
                    Ok(snapshot) => {
                        let msg = AgentMessage::StatusSnapshot {
                            cpu_percent: snapshot.cpu_percent,
                            ram_used_mb: snapshot.ram_used_mb,
                            ram_total_mb: snapshot.ram_total_mb,
                            network_connections: snapshot.network_connections,
                            running_processes: snapshot.running_processes,
                            ovt_version: snapshot.ovt_version,
                            disk_free_gb: snapshot.disk_free_gb,
                        };
                        let s = serde_json::to_string(&msg)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    }
                    Err(e) => {
                        let err = AgentMessage::Error {
                            message: format!("status error: {}", e),
                            request_id: None,
                        };
                        let s = serde_json::to_string(&err)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    }
                },
                Ok(BotMessage::GetLoot) => match list_loot(&loot_dir) {
                    Ok(files) => {
                        let msg = AgentMessage::LootListing { files };
                        let s = serde_json::to_string(&msg)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    }
                    Err(e) => {
                        let err = AgentMessage::Error {
                            message: format!("loot list error: {}", e),
                            request_id: None,
                        };
                        let s = serde_json::to_string(&err)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    }
                },
                Ok(BotMessage::ReadLootFile { path }) => match read_loot_file(&path) {
                    Ok(content) => {
                        let msg = AgentMessage::LootFileContent { path, content };
                        let s = serde_json::to_string(&msg)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    }
                    Err(e) => {
                        let err = AgentMessage::Error {
                            message: format!("read loot error: {}", e),
                            request_id: None,
                        };
                        let s = serde_json::to_string(&err)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    }
                },
                Ok(BotMessage::TakeScreenshot) => match take_screenshot() {
                    Ok(msg) => {
                        let s = serde_json::to_string(&msg)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    }
                    Err(e) => {
                        let err = AgentMessage::Error {
                            message: format!("screenshot error: {}", e),
                            request_id: None,
                        };
                        let s = serde_json::to_string(&err)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    }
                },
                Ok(BotMessage::BrowseUrl { url }) => match browse_url(&url) {
                    Ok(msg) => {
                        let s = serde_json::to_string(&msg)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    }
                    Err(e) => {
                        let err = AgentMessage::Error {
                            message: format!("browse error: {}", e),
                            request_id: None,
                        };
                        let s = serde_json::to_string(&err)?;
                        ws_tx.lock().await.send(Message::Text(s.into())).await?;
                    }
                },
                Ok(BotMessage::Auth { .. }) => {
                    // Already authenticated, ignore duplicate auth
                }
                Err(e) => {
                    tracing::warn!("failed to parse message: {}", e);
                }
            }
        }
    }

    Ok(())
}
