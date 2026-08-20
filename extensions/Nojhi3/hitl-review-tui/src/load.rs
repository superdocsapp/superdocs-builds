use std::path::Path;

use serde::Deserialize;

use crate::diffengine;
use crate::model::{Change, Decision, Payload};

#[derive(Deserialize, Default)]
struct RawChange {
    change_id: Option<String>,
    document_id: Option<String>,
    old_html: Option<String>,
    new_html: Option<String>,
    old_text: Option<String>,
    new_text: Option<String>,
    ai_explanation: Option<String>,
    path: Option<String>,
}

pub fn load(
    path: &Path,
    workspace: Option<&Path>,
    maps: &[(String, String)],
) -> Result<Vec<Change>, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    let trimmed = text.trim_start();
    if trimmed.starts_with('[') || trimmed.starts_with('{') {
        load_json_batch(&text, workspace, maps)
    } else {
        load_diff(&text)
    }
}

fn load_json_batch(
    text: &str,
    workspace: Option<&Path>,
    maps: &[(String, String)],
) -> Result<Vec<Change>, String> {
    let raws: Vec<RawChange> =
        serde_json::from_str(text).map_err(|e| format!("invalid JSON batch: {e}"))?;
    let mut changes = Vec::new();
    for (i, r) in raws.into_iter().enumerate() {
        let (old_raw, new_raw, is_html) = if let (Some(o), Some(n)) = (r.old_html, r.new_html) {
            (o, n, true)
        } else if let (Some(o), Some(n)) = (r.old_text, r.new_text) {
            (o, n, false)
        } else {
            return Err(format!(
                "change #{} has neither old_html/new_html nor old_text/new_text",
                i + 1
            ));
        };
        let document_id = r.document_id.clone().unwrap_or_else(|| format!("doc_{i}"));
        let path = resolve_path(&document_id, r.path.as_deref(), workspace, maps);
        let explanation = r.ai_explanation.unwrap_or_default();
        changes.push(Change {
            id: r.change_id.unwrap_or_else(|| format!("{document_id}#{i}")),
            explanation,
            is_html,
            payload: Payload::Replace {
                path,
                old_raw,
                new_raw,
            },
            decision: Decision::Unreviewed,
            edited_text: None,
        });
    }
    Ok(changes)
}

fn resolve_path(
    doc_id: &str,
    entry_path: Option<&str>,
    workspace: Option<&Path>,
    maps: &[(String, String)],
) -> String {
    if let Some((_, p)) = maps.iter().find(|(k, _)| k == doc_id) {
        return p.clone();
    }
    if let Some(p) = entry_path {
        return p.to_string();
    }
    if let Some(ws) = workspace
        && ws.join(doc_id).exists()
    {
        return doc_id.to_string();
    }
    doc_id.to_string()
}

fn load_diff(text: &str) -> Result<Vec<Change>, String> {
    let files = diffengine::parse_unified(text)?;
    let mut changes = Vec::new();
    for f in files {
        changes.push(Change {
            id: format!("{}@file", f.path),
            explanation: String::new(),
            is_html: false,
            payload: Payload::Hunks {
                path: f.path.clone(),
                hunks: f.hunks,
            },
            decision: Decision::Unreviewed,
            edited_text: None,
        });
    }
    Ok(changes)
}

#[cfg(test)]
pub fn load_json_batch_for_test(text: &str) -> Vec<Change> {
    load_json_batch(text, None, &[]).expect("valid test batch")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_json_batch_with_html() {
        let text = r#"[{"change_id":"c1","document_id":"doc_primary","old_html":"<p>old</p>","new_html":"<p>new</p>","ai_explanation":"tone"}]"#;
        let changes = load_json_batch(text, None, &[]).unwrap();
        assert_eq!(changes.len(), 1);
        assert!(changes[0].is_html);
        assert_eq!(changes[0].explanation, "tone");
        if let Payload::Replace {
            path,
            old_raw,
            new_raw,
        } = &changes[0].payload
        {
            assert_eq!(path, "doc_primary");
            assert_eq!(old_raw, "<p>old</p>");
            assert_eq!(new_raw, "<p>new</p>");
        } else {
            panic!("expected Replace payload");
        }
    }

    #[test]
    fn missing_pair_is_an_error() {
        let text = r#"[{"change_id":"c1","old_html":"<p>x</p>"}]"#;
        assert!(load_json_batch(text, None, &[]).is_err());
    }

    #[test]
    fn map_overrides_entry_path() {
        let text =
            r#"[{"change_id":"c1","document_id":"doc_primary","old_text":"a","new_text":"b"}]"#;
        let changes =
            load_json_batch(text, None, &[("doc_primary".into(), "real.txt".into())]).unwrap();
        assert_eq!(changes[0].payload.path(), "real.txt");
    }
}
