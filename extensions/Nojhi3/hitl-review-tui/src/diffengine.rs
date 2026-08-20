use similar::{ChangeTag, TextDiff};

use crate::model::{Change, Hunk, HunkLine, HunkLineKind, Payload};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ViewKind {
    Context,
    Removed,
    Added,
    Header,
}

#[derive(Clone, Debug)]
pub struct ViewLine {
    pub kind: ViewKind,
    pub text: String,
    pub segments: Option<Vec<(String, bool)>>,
}

pub fn render_change(change: &Change, show_raw: bool) -> Vec<ViewLine> {
    match &change.payload {
        Payload::Hunks { hunks, .. } => {
            let mut out = Vec::new();
            for h in hunks {
                out.push(ViewLine {
                    kind: ViewKind::Header,
                    text: h.header.clone(),
                    segments: None,
                });
                for l in &h.lines {
                    let kind = match l.kind {
                        HunkLineKind::Context => ViewKind::Context,
                        HunkLineKind::Added => ViewKind::Added,
                        HunkLineKind::Removed => ViewKind::Removed,
                    };
                    out.push(ViewLine {
                        kind,
                        text: l.text.clone(),
                        segments: None,
                    });
                }
            }
            out
        }
        Payload::Replace {
            old_raw, new_raw, ..
        } => {
            let (old_v, new_v) = if change.is_html {
                if show_raw {
                    (old_raw.clone(), new_raw.clone())
                } else {
                    (
                        crate::htmlext::html_to_text(old_raw),
                        crate::htmlext::html_to_text(new_raw),
                    )
                }
            } else {
                (old_raw.clone(), new_raw.clone())
            };
            let new_eff = match &change.edited_text {
                Some(t) if change.is_html && !show_raw => crate::htmlext::html_to_text(t),
                Some(t) => t.clone(),
                None => new_v,
            };
            diff_lines(&old_v, &new_eff)
        }
    }
}

pub fn diff_lines(old: &str, new: &str) -> Vec<ViewLine> {
    let diff = TextDiff::from_lines(old, new);
    let mut out = Vec::new();
    let mut pending: Vec<String> = Vec::new();
    for ch in diff.iter_all_changes() {
        match ch.tag() {
            ChangeTag::Equal => {
                flush_pending(&mut out, &mut pending);
                out.push(ViewLine {
                    kind: ViewKind::Context,
                    text: ch.value().to_string(),
                    segments: None,
                });
            }
            ChangeTag::Delete => pending.push(ch.value().to_string()),
            ChangeTag::Insert => {
                if let Some(removed) = pending.first() {
                    let (seg_old, seg_new) = word_diff(removed, ch.value());
                    out.push(ViewLine {
                        kind: ViewKind::Removed,
                        text: removed.clone(),
                        segments: Some(seg_old),
                    });
                    out.push(ViewLine {
                        kind: ViewKind::Added,
                        text: ch.value().to_string(),
                        segments: Some(seg_new),
                    });
                    pending.remove(0);
                } else {
                    out.push(ViewLine {
                        kind: ViewKind::Added,
                        text: ch.value().to_string(),
                        segments: None,
                    });
                }
            }
        }
    }
    flush_pending(&mut out, &mut pending);
    out
}

fn flush_pending(out: &mut Vec<ViewLine>, pending: &mut Vec<String>) {
    for p in pending.drain(..) {
        out.push(ViewLine {
            kind: ViewKind::Removed,
            text: p,
            segments: None,
        });
    }
}

pub type WordSegments = (Vec<(String, bool)>, Vec<(String, bool)>);

pub fn word_diff(old: &str, new: &str) -> WordSegments {
    let diff = TextDiff::from_words(old, new);
    let mut olds = Vec::new();
    let mut news = Vec::new();
    for ch in diff.iter_all_changes() {
        match ch.tag() {
            ChangeTag::Equal => {
                olds.push((ch.value().to_string(), false));
                news.push((ch.value().to_string(), false));
            }
            ChangeTag::Delete => olds.push((ch.value().to_string(), true)),
            ChangeTag::Insert => news.push((ch.value().to_string(), true)),
        }
    }
    (olds, news)
}

#[derive(Clone, Debug)]
pub struct FileDiff {
    pub path: String,
    pub hunks: Vec<Hunk>,
}

pub fn parse_unified(text: &str) -> Result<Vec<FileDiff>, String> {
    let mut files: Vec<FileDiff> = Vec::new();
    let mut current: Option<FileDiff> = None;
    let mut hunk: Option<Hunk> = None;
    for line in text.lines() {
        if line.starts_with("diff --git ") {
            flush(&mut files, &mut current, &mut hunk);
            current = Some(FileDiff {
                path: String::new(),
                hunks: Vec::new(),
            });
        } else if line.starts_with("+++ ") {
            if current.is_none() {
                current = Some(FileDiff {
                    path: String::new(),
                    hunks: Vec::new(),
                });
            }
            if let Some(c) = current.as_mut() {
                c.path = strip_a_b_prefix(line.strip_prefix("+++ ").unwrap_or(""));
            }
        } else if line.starts_with("--- ") {
            if current
                .as_ref()
                .map(|c| !c.hunks.is_empty())
                .unwrap_or(false)
            {
                flush(&mut files, &mut current, &mut hunk);
            }
        } else if line.starts_with("@@ ") {
            flush_hunk(&mut hunk, current.as_mut());
            hunk = Some(parse_hunk_header(line)?);
        } else if let Some(h) = hunk.as_mut() {
            let (kind, body) = if let Some(rest) = line.strip_prefix('+') {
                (HunkLineKind::Added, rest)
            } else if let Some(rest) = line.strip_prefix('-') {
                (HunkLineKind::Removed, rest)
            } else if let Some(rest) = line.strip_prefix(' ') {
                (HunkLineKind::Context, rest)
            } else if line.starts_with("\\ No newline") {
                continue;
            } else {
                return Err(format!("unexpected line inside hunk: {line:?}"));
            };
            h.lines.push(HunkLine {
                kind,
                text: body.to_string(),
            });
        }
    }
    flush(&mut files, &mut current, &mut hunk);
    if files.is_empty() {
        return Err("no hunks found in diff".into());
    }
    Ok(files)
}

fn strip_a_b_prefix(p: &str) -> String {
    let t = p.trim();
    if let Some(rest) = t.strip_prefix("a/").or_else(|| t.strip_prefix("b/")) {
        rest.to_string()
    } else {
        t.to_string()
    }
}

fn parse_hunk_header(line: &str) -> Result<Hunk, String> {
    let body = line.trim_start_matches("@@").trim_end_matches("@@").trim();
    let mut parts = body.split_whitespace();
    let old = parts
        .next()
        .ok_or_else(|| format!("bad hunk header: {line}"))?;
    let new = parts
        .next()
        .ok_or_else(|| format!("bad hunk header: {line}"))?;
    let parse_range = |s: &str| -> Result<(usize, usize), String> {
        let s = s.trim_start_matches(['-', '+']);
        if let Some((a, b)) = s.split_once(',') {
            let a: usize = a.parse().map_err(|_| format!("bad hunk header: {line}"))?;
            let b: usize = b.parse().map_err(|_| format!("bad hunk header: {line}"))?;
            Ok((a, b))
        } else {
            let a: usize = s.parse().map_err(|_| format!("bad hunk header: {line}"))?;
            Ok((a, 1))
        }
    };
    let (old_start, _) = parse_range(old)?;
    let (_, _) = parse_range(new)?;
    let old_pos0 = old_start.saturating_sub(1);
    Ok(Hunk {
        old_pos0,
        header: line.to_string(),
        lines: Vec::new(),
    })
}

fn flush_hunk(hunk: &mut Option<Hunk>, current: Option<&mut FileDiff>) {
    if let Some(h) = hunk.take()
        && let Some(c) = current
    {
        c.hunks.push(h);
    }
}

fn flush(files: &mut Vec<FileDiff>, current: &mut Option<FileDiff>, hunk: &mut Option<Hunk>) {
    flush_hunk(hunk, current.as_mut());
    if let Some(c) = current.take()
        && !c.path.is_empty()
        && !c.hunks.is_empty()
    {
        files.push(c);
    }
}

pub fn apply_unified(content: &str, hunks: &[Hunk]) -> Result<String, String> {
    let mut lines: Vec<String> = content.split('\n').map(String::from).collect();
    let had_trailing = content.ends_with('\n');
    if lines.last().map(|s| s.is_empty()) == Some(true) {
        lines.pop();
    }
    for h in hunks.iter().rev() {
        let pre: Vec<String> = h.pre_image();
        let mut pos = h.old_pos0.min(lines.len());
        let matches_at = |p: usize| -> bool {
            p + pre.len() <= lines.len()
                && pre
                    .iter()
                    .zip(&lines[p..p + pre.len()])
                    .all(|(a, b)| a == b)
        };
        if !matches_at(pos) {
            let found = (0..=lines.len().saturating_sub(pre.len()))
                .find(|&p| matches_at(p))
                .ok_or_else(|| format!("hunk context not found near line {}", h.old_pos0 + 1))?;
            pos = found;
        }
        let post: Vec<String> = h.post_image();
        lines.splice(pos..pos + pre.len(), post);
    }
    let mut out = lines.join("\n");
    if had_trailing {
        out.push('\n');
    }
    Ok(out)
}

pub fn rebuild_hunk(old_lines: &[String], new_lines: &[String], old_pos0: usize) -> Hunk {
    let old_joined = old_lines.join("\n");
    let new_joined = new_lines.join("\n");
    let diff = TextDiff::from_lines(&old_joined, &new_joined);
    let mut lines = Vec::new();
    for ch in diff.iter_all_changes() {
        let kind = match ch.tag() {
            ChangeTag::Equal => HunkLineKind::Context,
            ChangeTag::Delete => HunkLineKind::Removed,
            ChangeTag::Insert => HunkLineKind::Added,
        };
        lines.push(HunkLine {
            kind,
            text: ch.value().trim_end_matches('\n').to_string(),
        });
    }
    let old_count = lines
        .iter()
        .filter(|l| l.kind != HunkLineKind::Added)
        .count();
    let new_count = lines
        .iter()
        .filter(|l| l.kind != HunkLineKind::Removed)
        .count();
    let header = Hunk::header_for(old_pos0 + 1, old_count, old_pos0 + 1, new_count);
    Hunk {
        old_pos0,
        header,
        lines,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_single_file_diff() {
        let text = "--- a/f.txt\n+++ b/f.txt\n@@ -1,4 +1,4 @@\n line1\n-line2\n+line2 changed\n line3\n line4\n";
        let files = parse_unified(text).unwrap();
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].path, "f.txt");
        assert_eq!(files[0].hunks.len(), 1);
    }

    #[test]
    fn parses_multi_file_git_diff() {
        let text = "diff --git a/x.txt b/x.txt\nindex 111..222 100644\n--- a/x.txt\n+++ b/x.txt\n@@ -1,2 +1,2 @@\n a\n-b\n+b2\n c\ndiff --git a/y.txt b/y.txt\nindex 333..444 100644\n--- a/y.txt\n+++ b/y.txt\n@@ -1,1 +1,2 @@\n-a\n+a\n+b\n";
        let files = parse_unified(text).unwrap();
        assert_eq!(files.len(), 2);
        assert_eq!(files[0].path, "x.txt");
        assert_eq!(files[1].path, "y.txt");
    }

    #[test]
    fn applies_single_hunk() {
        let text = "--- a/f.txt\n+++ b/f.txt\n@@ -1,4 +1,4 @@\n line1\n-line2\n+line2 changed\n line3\n line4\n";
        let files = parse_unified(text).unwrap();
        let updated = apply_unified("line1\nline2\nline3\nline4\n", &files[0].hunks).unwrap();
        assert_eq!(updated, "line1\nline2 changed\nline3\nline4\n");
    }

    #[test]
    fn applies_multiple_hunks_in_order() {
        let text =
            "--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n@@ -4,2 +4,2 @@\n d\n-e\n+f\n";
        let files = parse_unified(text).unwrap();
        let updated = apply_unified("a\nb\nd\ne", &files[0].hunks).unwrap();
        assert_eq!(updated, "a\nc\nd\nf");
    }

    #[test]
    fn applies_new_file_hunk() {
        let text = "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+one\n+two\n";
        let files = parse_unified(text).unwrap();
        let updated = apply_unified("", &files[0].hunks).unwrap();
        assert_eq!(updated, "one\ntwo");
    }

    #[test]
    fn rebuild_hunk_produces_applicable_hunk() {
        let old = vec!["a".to_string(), "b".to_string(), "c".to_string()];
        let new = vec!["a".to_string(), "B!".to_string(), "c".to_string()];
        let h = rebuild_hunk(&old, &new, 0);
        let updated = apply_unified("a\nb\nc", &[h]).unwrap();
        assert_eq!(updated, "a\nB!\nc");
    }
}
