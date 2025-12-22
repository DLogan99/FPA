use anyhow::Result;
use chrono::Local;
use std::fs;
use std::path::Path;

use crate::config::BackupConfig;

pub fn create_backup(
    source: &Path,
    backup_dir: &Path,
    policy: &BackupConfig,
) -> Result<Option<std::path::PathBuf>> {
    if !source.exists() {
        return Ok(None);
    }
    fs::create_dir_all(backup_dir)?;
    let stem = source
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("file");
    let ext = source.extension().and_then(|e| e.to_str()).unwrap_or("bak");
    let ts = Local::now().format("%Y%m%d%H%M%S");
    let dest = backup_dir.join(format!("{}_{}.{}", stem, ts, ext));
    fs::copy(source, &dest)?;
    enforce_retention(backup_dir, stem, policy)?;
    Ok(Some(dest))
}

fn enforce_retention(dir: &Path, stem: &str, policy: &BackupConfig) -> Result<()> {
    let mut entries: Vec<_> = fs::read_dir(dir)?
        .filter_map(|e| e.ok())
        .filter(|e| {
            e.file_name()
                .to_str()
                .map(|name| name.starts_with(stem))
                .unwrap_or(false)
        })
        .collect();
    entries.sort_by_key(|e| e.metadata().and_then(|m| m.modified()).ok());
    entries.reverse();

    let keep_recent = policy.keep_recent;
    let keep_hist = policy.keep_historical;
    if entries.len() <= keep_recent + keep_hist {
        return Ok(());
    }

    let recent = entries
        .iter()
        .take(keep_recent)
        .cloned()
        .collect::<Vec<_>>();
    let rest = entries.into_iter().skip(keep_recent).collect::<Vec<_>>();
    let hist = pick_historical(rest, keep_hist);

    let mut keep_paths = recent
        .into_iter()
        .map(|e| e.path())
        .chain(hist.into_iter().map(|e| e.path()))
        .collect::<Vec<_>>();
    keep_paths.sort();

    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_file() && !keep_paths.contains(&path) {
            let _ = fs::remove_file(path);
        }
    }
    Ok(())
}

fn pick_historical(entries: Vec<std::fs::DirEntry>, count: usize) -> Vec<std::fs::DirEntry> {
    if count == 0 || entries.is_empty() {
        return Vec::new();
    }
    let step = std::cmp::max(1, entries.len() / count);
    entries.into_iter().step_by(step).take(count).collect()
}
