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
    let mut paths: Vec<_> = fs::read_dir(dir)?
        .filter_map(|e| e.ok())
        .filter_map(|e| {
            let name = e.file_name();
            let keep = name.to_str().map(|n| n.starts_with(stem)).unwrap_or(false);
            if keep { Some(e.path()) } else { None }
        })
        .collect();

    paths.sort_by_key(|p| fs::metadata(p).and_then(|m| m.modified()).ok());
    paths.reverse();

    let keep_recent = policy.keep_recent;
    let keep_hist = policy.keep_historical;
    if paths.len() <= keep_recent + keep_hist {
        return Ok(());
    }

    let recent: Vec<_> = paths.iter().take(keep_recent).cloned().collect();
    let rest: Vec<_> = paths.into_iter().skip(keep_recent).collect();
    let hist = pick_historical(rest, keep_hist);

    let mut keep_paths = recent
        .into_iter()
        .chain(hist.into_iter())
        .collect::<Vec<_>>();
    keep_paths.sort();

    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        let name_matches_stem = path
            .file_name()
            .and_then(|n| n.to_str())
            .map(|n| n.starts_with(stem))
            .unwrap_or(false);
        if name_matches_stem && path.is_file() && !keep_paths.contains(&path) {
            let _ = fs::remove_file(path);
        }
    }
    Ok(())
}

fn pick_historical(paths: Vec<std::path::PathBuf>, count: usize) -> Vec<std::path::PathBuf> {
    if count == 0 || paths.is_empty() {
        return Vec::new();
    }
    let step = std::cmp::max(1, paths.len() / count);
    paths.into_iter().step_by(step).take(count).collect()
}
