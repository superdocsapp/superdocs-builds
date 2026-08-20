use std::collections::BTreeMap;
use std::path::Path;
use std::process::Command;

use crate::model::{Change, Decision, Payload};

pub struct ApplyOutcome {
    pub applied: Vec<String>,
    pub failed: Vec<String>,
    pub rejected: Vec<String>,
}

pub fn apply_changes(
    changes: &[Change],
    workspace: &Path,
    dry_run: bool,
) -> Result<ApplyOutcome, String> {
    let mut outcome = ApplyOutcome {
        applied: Vec::new(),
        failed: Vec::new(),
        rejected: Vec::new(),
    };
    let mut by_path: BTreeMap<String, Vec<&Change>> = BTreeMap::new();
    for c in changes {
        match c.decision {
            Decision::Accepted | Decision::Edited => {
                by_path
                    .entry(c.payload.path().to_string())
                    .or_default()
                    .push(c);
            }
            Decision::Rejected => outcome.rejected.push(c.payload.path().to_string()),
            Decision::Unreviewed => outcome.failed.push(format!("{} unreviewed", c.id)),
        }
    }
    for (path, group) in by_path {
        let full = workspace.join(&path);
        if group
            .iter()
            .all(|c| matches!(c.payload, Payload::Hunks { .. }))
        {
            let content = std::fs::read_to_string(&full)
                .map_err(|e| format!("cannot read {}: {e}", full.display()))?;
            let mut hunks = Vec::new();
            for c in &group {
                if let Payload::Hunks { hunks: hs, .. } = &c.payload {
                    hunks.extend(hs.iter().cloned());
                }
            }
            let updated = crate::diffengine::apply_unified(&content, &hunks)
                .map_err(|e| format!("{path}: {e}"))?;
            if !dry_run {
                write_if_changed(&full, &updated)?;
            }
            outcome.applied.push(path);
        } else {
            for c in &group {
                if let Payload::Replace { old_raw, .. } = &c.payload {
                    let target = c
                        .applied_raw()
                        .ok_or_else(|| format!("{}: missing applied content", c.id))?;
                    match std::fs::read_to_string(&full) {
                        Ok(content) => {
                            if let Some(pos) = content.find(old_raw) {
                                let updated = format!(
                                    "{}{}{}",
                                    &content[..pos],
                                    target,
                                    &content[pos + old_raw.len()..]
                                );
                                if !dry_run {
                                    write_if_changed(&full, &updated)?;
                                }
                                outcome.applied.push(path.clone());
                            } else {
                                outcome
                                    .failed
                                    .push(format!("{path}: old content not found in file"));
                            }
                        }
                        Err(_) => {
                            if !dry_run {
                                write_if_changed(&full, &target)?;
                            }
                            outcome.applied.push(path.clone());
                        }
                    }
                }
            }
        }
    }
    outcome.applied.sort();
    outcome.applied.dedup();
    outcome.rejected.sort();
    outcome.rejected.dedup();
    Ok(outcome)
}

fn write_if_changed(path: &Path, content: &str) -> Result<(), String> {
    let changed = match std::fs::read_to_string(path) {
        Ok(c) => c != content,
        Err(_) => true,
    };
    if changed {
        if let Some(parent) = path.parent()
            && !parent.as_os_str().is_empty()
        {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
        }
        std::fs::write(path, content).map_err(|e| format!("write {}: {e}", path.display()))?;
    }
    Ok(())
}

pub struct CommitResult {
    pub hash: Option<String>,
}

pub fn commit_batch(
    workspace: &Path,
    files: &[String],
    message: &str,
    dry_run: bool,
) -> Result<CommitResult, String> {
    if files.is_empty() {
        return Ok(CommitResult { hash: None });
    }
    if dry_run {
        return Ok(CommitResult {
            hash: Some("(dry-run)".to_string()),
        });
    }
    ensure_repo(workspace)?;
    let mut add_args = vec!["add".to_string(), "--".to_string()];
    add_args.extend(files.iter().cloned());
    git(workspace, &add_args)?;
    let msg_path = std::env::temp_dir().join(format!("hitl_commit_msg_{}.txt", std::process::id()));
    std::fs::write(&msg_path, message).map_err(|e| format!("cannot write commit message: {e}"))?;
    let commit_args = vec![
        "commit".to_string(),
        "-F".to_string(),
        msg_path.to_string_lossy().into_owned(),
    ];
    let commit_res = git(workspace, &commit_args);
    let _ = std::fs::remove_file(&msg_path);
    commit_res?;
    let hash = git(
        workspace,
        &[
            "rev-parse".to_string(),
            "--short".to_string(),
            "HEAD".to_string(),
        ],
    )
    .ok();
    Ok(CommitResult { hash })
}

pub fn build_message(accepted: usize, edited: usize, rejected: usize, files: &[String]) -> String {
    let mut msg = format!(
        "Apply {} approved change(s) via hitl-review-tui",
        accepted + edited
    );
    if edited > 0 {
        msg.push_str(&format!("\n({edited} edited by reviewer)"));
    }
    if rejected > 0 {
        msg.push_str(&format!("\n{rejected} change(s) rejected and not applied"));
    }
    if !files.is_empty() {
        msg.push_str(&format!(
            "\n\nfiles:\n{}",
            files
                .iter()
                .map(|f| format!("  {f}"))
                .collect::<Vec<_>>()
                .join("\n")
        ));
    }
    msg
}

fn ensure_repo(workspace: &Path) -> Result<(), String> {
    git(
        workspace,
        &["rev-parse".to_string(), "--is-inside-work-tree".to_string()],
    )
    .map_err(|e| format!("{} is not a git repository: {e}", workspace.display()))?;
    Ok(())
}

pub fn git(workspace: &Path, args: &[String]) -> Result<String, String> {
    let out = Command::new("git")
        .arg("-C")
        .arg(workspace)
        .args(args)
        .output()
        .map_err(|e| format!("git failed to start: {e}"))?;
    if !out.status.success() {
        return Err(format!(
            "git {} failed: {}",
            args.join(" "),
            String::from_utf8_lossy(&out.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Hunk, HunkLine, HunkLineKind, Payload};

    #[test]
    fn replace_payload_applies_substring() {
        let dir = std::env::temp_dir().join(format!("hitl_act_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("doc.txt"), "hello world\nfoo\n").unwrap();
        let change = Change {
            id: "c1".into(),
            explanation: String::new(),
            is_html: false,
            payload: Payload::Replace {
                path: "doc.txt".into(),
                old_raw: "hello world".into(),
                new_raw: "hello brave world".into(),
            },
            decision: Decision::Accepted,
            edited_text: None,
        };
        let out = apply_changes(&[change], &dir, false).unwrap();
        assert_eq!(out.applied, vec!["doc.txt".to_string()]);
        let content = std::fs::read_to_string(dir.join("doc.txt")).unwrap();
        assert_eq!(content, "hello brave world\nfoo\n");
    }

    #[test]
    fn hunk_payload_applies_via_diff_engine() {
        let dir = std::env::temp_dir().join(format!("hitl_act2_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("f.txt"), "a\nb\nc\n").unwrap();
        let change = Change {
            id: "c1".into(),
            explanation: String::new(),
            is_html: false,
            payload: Payload::Hunks {
                path: "f.txt".into(),
                hunks: vec![Hunk {
                    old_pos0: 1,
                    header: "@@ -2,1 +2,1 @@".into(),
                    lines: vec![
                        HunkLine {
                            kind: HunkLineKind::Context,
                            text: "a".into(),
                        },
                        HunkLine {
                            kind: HunkLineKind::Removed,
                            text: "b".into(),
                        },
                        HunkLine {
                            kind: HunkLineKind::Added,
                            text: "B!".into(),
                        },
                        HunkLine {
                            kind: HunkLineKind::Context,
                            text: "c".into(),
                        },
                    ],
                }],
            },
            decision: Decision::Accepted,
            edited_text: None,
        };
        let out = apply_changes(&[change], &dir, false).unwrap();
        assert_eq!(out.applied, vec!["f.txt".to_string()]);
        let content = std::fs::read_to_string(dir.join("f.txt")).unwrap();
        assert_eq!(content, "a\nB!\nc\n");
    }

    #[test]
    fn edited_decision_writes_edited_text() {
        let dir = std::env::temp_dir().join(format!("hitl_act3_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("doc.txt"), "hello world\n").unwrap();
        let change = Change {
            id: "c1".into(),
            explanation: String::new(),
            is_html: false,
            payload: Payload::Replace {
                path: "doc.txt".into(),
                old_raw: "hello world".into(),
                new_raw: "hello brave world".into(),
            },
            decision: Decision::Edited,
            edited_text: Some("hello giant world".into()),
        };
        apply_changes(&[change], &dir, false).unwrap();
        let content = std::fs::read_to_string(dir.join("doc.txt")).unwrap();
        assert_eq!(content, "hello giant world\n");
    }
}
