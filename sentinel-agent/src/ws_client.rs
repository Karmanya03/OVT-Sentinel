use crate::browser::{browse_url, take_screenshot};
use crate::executor::CommandExecutor;
use crate::loot_watcher::{list_loot, read_loot_file, start_loot_watcher};
use crate::monitor::SystemMonitor;
use crate::protocol::{AgentMessage, BotMessage};
use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::Message;

/// Connect to the bot's WebSocket server (reverse mode).
/// The agent connects outbound to the bot, authenticates, then
/// enters the command-processing loop.
pub async fn connect_to_bot(
    bot_ws_url: &str,
    token: &str,
    executor: Arc<CommandExecutor>,
    loot_dir: String,
) -> Result<()> {
    let (ws_stream, _) = connect_async(bot_ws_url).await?;
    tracing::info!("Connected to bot at {}", bot_ws_url);

    let (ws_tx, mut ws_rx) = ws_stream.split();
    let ws_tx = Arc::new(Mutex::new(ws_tx));

    // Send auth
    let auth = serde_json::json!({"type": "auth", "token": token});
    let s = serde_json::to_string(&auth)?;
    ws_tx.lock().await.send(Message::Text(s.into())).await?;

    // Wait for auth result
    match ws_rx.next().await {
        Some(Ok(Message::Text(txt))) => {
            let result: serde_json::Value = serde_json::from_str(&txt)?;
            if result.get("success").and_then(|v| v.as_bool()) != Some(true) {
                let reason = result
                    .get("reason")
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown");
                anyhow::bail!("auth failed: {}", reason);
            }
            tracing::info!("Authenticated with bot");
        }
        Some(Ok(_)) => anyhow::bail!("unexpected auth response (non-text)"),
        Some(Err(e)) => anyhow::bail!("auth response error: {}", e),
        None => anyhow::bail!("connection closed during auth"),
    }

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
