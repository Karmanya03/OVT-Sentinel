use anyhow::{Context, Result};
use std::process::Stdio;
use tokio::process::Command;
use tokio::sync::watch;

const TUNNEL_TIMEOUT_SECS: u64 = 30;

#[allow(dead_code)]
pub struct Tunnel {
    public_url: String,
    shutdown_tx: watch::Sender<bool>,
}

impl Tunnel {
    pub fn public_url(&self) -> &str {
        &self.public_url
    }
}

pub async fn start_ngrok_tunnel(local_port: u16, auth_token: Option<&str>) -> Result<Tunnel> {
    let port_str = local_port.to_string();
    let mut args = vec!["tcp", &port_str, "--log=stdout", "--log-level=info"];
    if let Some(token) = auth_token {
        args.push("--authtoken");
        args.push(token);
    }

    let mut child = Command::new("ngrok")
        .args(&args)
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()
        .context(
            "Failed to spawn 'ngrok'. Install it from https://ngrok.com/download",
        )?;

    let stdout = child
        .stdout
        .take()
        .context("failed to capture ngrok stdout")?;

    let mut reader = tokio::io::BufReader::new(stdout);
    use tokio::io::AsyncBufReadExt;

    let mut line_buf = String::new();
    let public_url;

    loop {
        let n = tokio::time::timeout(
            std::time::Duration::from_secs(TUNNEL_TIMEOUT_SECS),
            reader.read_line(&mut line_buf),
        )
        .await
        .context("ngrok did not establish a tunnel within 30s — check your auth token and network")?
        .context("failed to read ngrok output")?;

        if n == 0 {
            child.wait().await?;
            anyhow::bail!("ngrok exited without establishing a tunnel");
        }
        let trimmed = line_buf.trim();
        if let Some(url) = extract_ngrok_url(trimmed) {
            public_url = url;
            tracing::info!("Tunnel established: {}", public_url);
            break;
        }
    }

    let (shutdown_tx, mut shutdown_rx) = watch::channel(false);
    let mut child = child;

    tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = shutdown_rx.changed() => {
                    let _ = child.kill().await;
                    let _ = child.wait().await;
                    break;
                }
                status = child.wait() => {
                    match status {
                        Ok(s) => tracing::warn!("ngrok process exited unexpectedly: {}", s),
                        Err(e) => tracing::error!("ngrok process error: {}", e),
                    }
                    break;
                }
            }
        }
    });

    Ok(Tunnel {
        public_url,
        shutdown_tx,
    })
}

fn extract_ngrok_url(line: &str) -> Option<String> {
    // ngrok v3 JSON log: {"lvl":"info","msg":"started tunnel","url":"tcp://...","obj":{"url":"tcp://..."}}
    // Accept any line containing "tunnel" in msg and a tcp:// URL
    let parsed: serde_json::Value = serde_json::from_str(line).ok()?;

    // Only process lines about tunnel status
    let msg = parsed.get("msg")?.as_str()?;
    if !msg.contains("tunnel") && !msg.contains(" Tunnel") {
        return None;
    }

    // Try top-level "url" first, then nested "obj.url"
    let url = parsed
        .get("url")
        .or_else(|| parsed.get("obj")?.get("url"))?
        .as_str()?;

    // Only accept tcp:// tunnels (not http:// from other ngrok features)
    if !url.starts_with("tcp://") {
        return None;
    }

    Some(url.replacen("tcp://", "ws://", 1))
}

pub async fn register_tunnel(register_url: &str, tunnel_ws_url: &str, token: &str) -> Result<()> {
    let payload = serde_json::json!({
        "token": token,
        "url": tunnel_ws_url,
    });

    let client = reqwest::Client::new();
    let resp = client
        .post(register_url)
        .json(&payload)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await
        .context("failed to send registration request")?;

    if resp.status().is_success() {
        tracing::info!("Bot registration successful: {}", tunnel_ws_url);
        Ok(())
    } else {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("bot registration failed ({}): {}", status, body)
    }
}
