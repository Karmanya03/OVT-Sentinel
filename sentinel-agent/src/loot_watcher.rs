use crate::protocol::{AgentMessage, LootFile, LootFileType};
use anyhow::Result;
use notify::{Config, Event, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::mpsc as std_mpsc;
use std::time::UNIX_EPOCH;
use tokio::sync::mpsc;

pub fn start_loot_watcher(loot_dir: String) -> Result<mpsc::UnboundedReceiver<AgentMessage>> {
    let (tx, rx) = mpsc::unbounded_channel();
    let watch_path = PathBuf::from(loot_dir.clone());

    std::thread::spawn(move || {
        let tx = tx.clone();
        let (fs_tx, fs_rx): (
            std_mpsc::Sender<Result<Event, notify::Error>>,
            std_mpsc::Receiver<Result<Event, notify::Error>>,
        ) = std_mpsc::channel();

        let mut watcher: RecommendedWatcher =
            RecommendedWatcher::new(fs_tx, Config::default()).expect("failed to create watcher");

        let _ = watcher.watch(&watch_path, RecursiveMode::NonRecursive);

        for res in fs_rx {
            if let Ok(event) = res {
                if matches!(event.kind, EventKind::Create(_)) {
                    for path in event.paths {
                        if let Ok(meta) = fs::metadata(&path) {
                            if meta.is_file() {
                                let size = meta.len();
                                let msg = AgentMessage::LootFileCreated {
                                    path: path.to_string_lossy().to_string(),
                                    size_bytes: size,
                                };
                                let _ = tx.send(msg);
                            }
                        }
                    }
                }
            }
        }
    });

    Ok(rx)
}

pub fn list_loot(loot_dir: &str) -> Result<Vec<LootFile>> {
    let mut files = Vec::new();
    let dir = Path::new(loot_dir);
    if !dir.exists() {
        return Ok(files);
    }

    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        let meta = entry.metadata()?;
        if !meta.is_file() {
            continue;
        }

        let name = path
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();
        let modified_secs = meta
            .modified()
            .ok()
            .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
            .map(|d| d.as_secs())
            .unwrap_or(0);

        let name_clone = name.clone();
        files.push(LootFile {
            path: path.to_string_lossy().to_string(),
            name,
            size_bytes: meta.len(),
            modified_secs,
            file_type: detect_loot_type(&name_clone),
        });
    }

    Ok(files)
}

pub fn read_loot_file(path: &str) -> Result<String> {
    let content = fs::read_to_string(path)?;
    Ok(content)
}

fn detect_loot_type(name: &str) -> LootFileType {
    let lower = name.to_ascii_lowercase();
    if lower.ends_with(".json") {
        return LootFileType::BloodHoundJson;
    }
    if lower.ends_with(".kirbi") || lower.ends_with(".ccache") {
        return LootFileType::Tickets;
    }
    if lower.contains("hash") || lower.contains("krb5") {
        return LootFileType::Hashes;
    }
    if lower.ends_with(".pdf") || lower.ends_with(".md") {
        return LootFileType::Report;
    }
    if lower.contains("creds") || lower.contains("password") {
        return LootFileType::Credentials;
    }
    LootFileType::Other
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detect_loot_type_bloodhound() {
        assert_eq!(
            detect_loot_type("bloodhound.json"),
            LootFileType::BloodHoundJson
        );
        assert_eq!(detect_loot_type("users.json"), LootFileType::BloodHoundJson);
    }

    #[test]
    fn test_detect_loot_type_tickets() {
        assert_eq!(detect_loot_type("ticket.kirbi"), LootFileType::Tickets);
        assert_eq!(detect_loot_type("krb5.ccache"), LootFileType::Tickets);
    }

    #[test]
    fn test_detect_loot_type_hashes() {
        assert_eq!(detect_loot_type("hashes.txt"), LootFileType::Hashes);
        assert_eq!(detect_loot_type("krb5_users.txt"), LootFileType::Hashes);
    }

    #[test]
    fn test_detect_loot_type_report() {
        assert_eq!(detect_loot_type("report.pdf"), LootFileType::Report);
        assert_eq!(detect_loot_type("findings.md"), LootFileType::Report);
    }

    #[test]
    fn test_detect_loot_type_credentials() {
        assert_eq!(detect_loot_type("creds.txt"), LootFileType::Credentials);
        assert_eq!(detect_loot_type("passwords.txt"), LootFileType::Credentials);
    }

    #[test]
    fn test_detect_loot_type_other() {
        assert_eq!(detect_loot_type("random.txt"), LootFileType::Other);
        assert_eq!(detect_loot_type("output.csv"), LootFileType::Other);
    }

    #[test]
    fn test_detect_loot_type_case_insensitive() {
        assert_eq!(detect_loot_type("HASHES.TXT"), LootFileType::Hashes);
        assert_eq!(
            detect_loot_type("BloodHound.JSON"),
            LootFileType::BloodHoundJson
        );
    }

    #[test]
    fn test_detect_loot_type_empty() {
        assert_eq!(detect_loot_type(""), LootFileType::Other);
    }

    #[test]
    fn test_list_loot_nonexistent_dir() {
        let result = list_loot("/nonexistent/path/xyz").unwrap();
        assert!(result.is_empty());
    }
}
