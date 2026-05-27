use serde::{Deserialize, Serialize};

/// Messages FROM the bot TO the agent
#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum BotMessage {
    RunCommand {
        request_id: String,
        command: String,
        timeout_secs: Option<u64>,
    },
    KillCommand {
        request_id: String,
    },
    GetStatus,
    GetLoot,
    ReadLootFile {
        path: String,
    },
    TakeScreenshot,
    BrowseUrl {
        url: String,
    },
    Auth {
        token: String,
    },
}

/// Messages FROM the agent TO the bot
#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum AgentMessage {
    AuthResult {
        success: bool,
        reason: Option<String>,
    },
    CommandOutput {
        request_id: String,
        stream: OutputStream,
        data: String,
        sequence: u64,
    },
    CommandComplete {
        request_id: String,
        exit_code: i32,
        duration_ms: u64,
    },
    CommandKilled {
        request_id: String,
    },
    StatusSnapshot {
        cpu_percent: f32,
        ram_used_mb: u64,
        ram_total_mb: u64,
        network_connections: Vec<NetworkConn>,
        running_processes: Vec<ProcessInfo>,
        ovt_version: Option<String>,
        disk_free_gb: f64,
    },
    LootListing {
        files: Vec<LootFile>,
    },
    LootFileContent {
        path: String,
        content: String,
    },
    LootFileCreated {
        path: String,
        size_bytes: u64,
    },
    Screenshot {
        data_base64: String,
    },
    Error {
        message: String,
        request_id: Option<String>,
    },
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "snake_case")]
pub enum OutputStream {
    Stdout,
    Stderr,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct NetworkConn {
    pub local_addr: String,
    pub remote_addr: Option<String>,
    pub state: String,
    pub pid: Option<u32>,
    pub process_name: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ProcessInfo {
    pub pid: u32,
    pub name: String,
    pub cpu_percent: f32,
    pub ram_mb: u64,
    pub command: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LootFile {
    pub path: String,
    pub name: String,
    pub size_bytes: u64,
    pub modified_secs: u64,
    pub file_type: LootFileType,
}

#[derive(Debug, PartialEq, Serialize, Deserialize, Clone)]
#[serde(rename_all = "snake_case")]
pub enum LootFileType {
    BloodHoundJson,
    Hashes,
    Tickets,
    Report,
    Credentials,
    Other,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bot_run_command_round_trip() {
        let msg = BotMessage::RunCommand {
            request_id: "req-123".into(),
            command: "whoami".into(),
            timeout_secs: Some(60),
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains("run_command"));
        let back: BotMessage = serde_json::from_str(&json).unwrap();
        match back {
            BotMessage::RunCommand {
                request_id,
                command,
                timeout_secs,
            } => {
                assert_eq!(request_id, "req-123");
                assert_eq!(command, "whoami");
                assert_eq!(timeout_secs, Some(60));
            }
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn test_bot_get_status() {
        let json = serde_json::to_string(&BotMessage::GetStatus).unwrap();
        assert!(json.contains("get_status"));
    }

    #[test]
    fn test_bot_auth() {
        let json = serde_json::to_string(&BotMessage::Auth {
            token: "t0k3n".into(),
        })
        .unwrap();
        assert!(json.contains("auth"));
        assert!(json.contains("t0k3n"));
    }

    #[test]
    fn test_agent_command_output() {
        let msg = AgentMessage::CommandOutput {
            request_id: "req-1".into(),
            stream: OutputStream::Stdout,
            data: "hello".into(),
            sequence: 1,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains("command_output"), "json: {json}");
        assert!(json.contains("\"stdout\""), "json: {json}");
    }

    #[test]
    fn test_agent_auth_result() {
        let msg = AgentMessage::AuthResult {
            success: true,
            reason: None,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains("auth_result"));
        assert!(json.contains("true"));
        let back: AgentMessage = serde_json::from_str(&json).unwrap();
        match back {
            AgentMessage::AuthResult { success, .. } => assert!(success),
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn test_agent_error_with_request_id() {
        let msg = AgentMessage::Error {
            message: "fail".into(),
            request_id: Some("req-1".into()),
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains("req-1"));
    }

    #[test]
    fn test_loot_file_type_names() {
        let cases = [
            (LootFileType::BloodHoundJson, "blood_hound_json"),
            (LootFileType::Hashes, "hashes"),
            (LootFileType::Credentials, "credentials"),
            (LootFileType::Other, "other"),
        ];
        for (ft, expected) in cases {
            let s: String = serde_json::to_string(&ft).unwrap();
            assert_eq!(s.trim_matches('"'), expected);
        }
    }

    #[test]
    fn test_loot_file_round_trip() {
        let f = LootFile {
            path: "/loot/hashes.txt".into(),
            name: "hashes.txt".into(),
            size_bytes: 1024,
            modified_secs: 1700000000,
            file_type: LootFileType::Hashes,
        };
        let json = serde_json::to_string(&f).unwrap();
        let back: LootFile = serde_json::from_str(&json).unwrap();
        assert_eq!(f.path, back.path);
        assert_eq!(f.size_bytes, back.size_bytes);
    }

    #[test]
    fn test_bot_message_kill() {
        let msg = BotMessage::KillCommand {
            request_id: "req-42".into(),
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains("kill_command"));
    }

    #[test]
    fn test_agent_message_screenshot() {
        let msg = AgentMessage::Screenshot {
            data_base64: "aW1hZ2U=".into(),
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains("screenshot"));
        assert!(json.contains("aW1hZ2U="));
    }

    #[test]
    fn test_bot_browse_url() {
        let msg = BotMessage::BrowseUrl {
            url: "https://example.com".into(),
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains("browse_url"));
        assert!(json.contains("example.com"));
        let back: BotMessage = serde_json::from_str(&json).unwrap();
        match back {
            BotMessage::BrowseUrl { url } => assert_eq!(url, "https://example.com"),
            _ => panic!("wrong variant"),
        }
    }
}
