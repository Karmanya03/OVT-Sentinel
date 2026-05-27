use crate::protocol::{AgentMessage, OutputStream};
use anyhow::Result;
use std::collections::HashMap;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Instant;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;
use tokio::sync::{Mutex, mpsc};

pub struct CommandExecutor {
    #[allow(dead_code)]
    pub ovt_path: String,
    processes: Arc<Mutex<HashMap<String, Arc<Mutex<tokio::process::Child>>>>>,
}

impl CommandExecutor {
    pub fn new(ovt_path: String) -> Self {
        Self {
            ovt_path,
            processes: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub async fn spawn_command(
        &self,
        request_id: String,
        command: String,
        timeout_secs: Option<u64>,
    ) -> Result<mpsc::UnboundedReceiver<AgentMessage>> {
        let (tx, rx) = mpsc::unbounded_channel();
        let start = Instant::now();

        let args_str = command
            .trim_start_matches("overthrone ")
            .trim_start_matches("ovt ")
            .to_string();

        let mut cmd = if cfg!(windows) {
            let mut c = Command::new("cmd");
            c.arg("/C").arg(&command);
            c
        } else {
            let mut c = Command::new("sh");
            c.arg("-c").arg(&args_str);
            c
        };
        cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

        let child = cmd.spawn()?;
        let child_arc = Arc::new(Mutex::new(child));

        self.processes
            .lock()
            .await
            .insert(request_id.clone(), child_arc.clone());

        let timeout_duration = timeout_secs.map(std::time::Duration::from_secs);

        // stdout reader
        let tx_out = tx.clone();
        let rid = request_id.clone();
        let out_clone = child_arc.clone();
        tokio::spawn(async move {
            let mut seq: u64 = 0;
            let mut guard = out_clone.lock().await;
            if let Some(stdout) = guard.stdout.take() {
                let mut reader = BufReader::new(stdout).lines();
                drop(guard);
                while let Ok(Some(line)) = reader.next_line().await {
                    seq = seq.wrapping_add(1);
                    let msg = AgentMessage::CommandOutput {
                        request_id: rid.clone(),
                        stream: OutputStream::Stdout,
                        data: line,
                        sequence: seq,
                    };
                    let _ = tx_out.send(msg);
                }
            }
        });

        // stderr reader
        let tx_err = tx.clone();
        let rid2 = request_id.clone();
        let err_clone = child_arc.clone();
        tokio::spawn(async move {
            let mut seq: u64 = 0;
            let mut guard = err_clone.lock().await;
            if let Some(stderr) = guard.stderr.take() {
                let mut reader = BufReader::new(stderr).lines();
                drop(guard);
                while let Ok(Some(line)) = reader.next_line().await {
                    seq = seq.wrapping_add(1);
                    let msg = AgentMessage::CommandOutput {
                        request_id: rid2.clone(),
                        stream: OutputStream::Stderr,
                        data: line,
                        sequence: seq,
                    };
                    let _ = tx_err.send(msg);
                }
            }
        });

        // Waiter with optional timeout
        let processes_map = self.processes.clone();
        let tx_done = tx.clone();
        let rid3 = request_id.clone();
        tokio::spawn(async move {
            let status_result = if let Some(dur) = timeout_duration {
                tokio::select! {
                    status = async {
                        let mut guard = child_arc.lock().await;
                        guard.wait().await
                    } => status,
                    _ = tokio::time::sleep(dur) => {
                        let mut guard = child_arc.lock().await;
                        let _ = guard.kill().await;
                        let _ = guard.wait().await;
                        let msg = AgentMessage::CommandKilled { request_id: rid3.clone() };
                        let _ = tx_done.send(msg);
                        let mut map = processes_map.lock().await;
                        map.remove(&rid3);
                        return;
                    }
                }
            } else {
                let mut guard = child_arc.lock().await;
                guard.wait().await
            };

            let duration_ms = start.elapsed().as_millis() as u64;

            match status_result {
                Ok(status) => {
                    let code = status.code().unwrap_or(-1);
                    let complete = AgentMessage::CommandComplete {
                        request_id: rid3.clone(),
                        exit_code: code as i32,
                        duration_ms,
                    };
                    let _ = tx_done.send(complete);
                }
                Err(e) => {
                    let err = AgentMessage::Error {
                        message: format!("wait error: {}", e),
                        request_id: Some(rid3.clone()),
                    };
                    let _ = tx_done.send(err);
                }
            }

            let mut map = processes_map.lock().await;
            map.remove(&rid3);
        });

        Ok(rx)
    }

    pub async fn kill(&self, request_id: &str) -> Result<bool> {
        let child_arc = {
            let mut map = self.processes.lock().await;
            map.remove(request_id)
        };

        if let Some(child_arc) = child_arc {
            let mut guard = child_arc.lock().await;
            match guard.kill().await {
                Ok(_) => {
                    let _ = guard.wait().await;
                    Ok(true)
                }
                Err(_) => Ok(false),
            }
        } else {
            Ok(false)
        }
    }

    pub async fn active_count(&self) -> usize {
        self.processes.lock().await.len()
    }

    pub async fn kill_all(&self) -> usize {
        let ids: Vec<String> = self.processes.lock().await.keys().cloned().collect();
        let count = ids.len();
        for id in &ids {
            let _ = self.kill(id).await;
        }
        count
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_executor() {
        let exec = CommandExecutor::new("/usr/bin/ovt".into());
        assert_eq!(exec.ovt_path, "/usr/bin/ovt");
    }

    #[tokio::test]
    async fn test_active_count_empty() {
        let exec = CommandExecutor::new("ovt".into());
        assert_eq!(exec.active_count().await, 0);
    }

    #[tokio::test]
    async fn test_kill_nonexistent() {
        let exec = CommandExecutor::new("ovt".into());
        let result = exec.kill("no-such-id").await.unwrap();
        assert!(!result);
    }

    #[tokio::test]
    async fn test_kill_all_empty() {
        let exec = CommandExecutor::new("ovt".into());
        assert_eq!(exec.kill_all().await, 0);
    }

    #[tokio::test]
    async fn test_spawn_and_kill() {
        let exec = CommandExecutor::new("ovt".into());
        let cmd = if cfg!(windows) {
            "ping -n 30 127.0.0.1" // ~30s, reliably killable
        } else {
            "sleep 30"
        };
        let mut rx = exec
            .spawn_command("req-1".into(), cmd.into(), Some(2))
            .await
            .unwrap();

        let mut killed = false;
        while let Some(msg) = rx.recv().await {
            if matches!(msg, AgentMessage::CommandKilled { .. }) {
                killed = true;
                break;
            }
        }
        assert!(killed, "expected command to be killed by timeout");
    }
}
