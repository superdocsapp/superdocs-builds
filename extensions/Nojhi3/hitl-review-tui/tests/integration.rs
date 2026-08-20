use std::path::{Path, PathBuf};
use std::process::Command;

use hitl_review_tui::cli::{Cli, DecideMode};
use hitl_review_tui::model::Decision;
use hitl_review_tui::{actions, headless, load, tui};

fn tmpdir(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("hitl_it_{name}_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn write_text(dir: &Path, name: &str, text: &str) -> PathBuf {
    let p = dir.join(name);
    std::fs::write(&p, text).unwrap();
    p
}

fn git_init(dir: &PathBuf) {
    for args in [
        vec!["init", "-q", "-b", "main"],
        vec!["config", "user.email", "review@test"],
        vec!["config", "user.name", "reviewer"],
    ] {
        assert!(
            Command::new("git")
                .args(&args)
                .current_dir(dir)
                .status()
                .unwrap()
                .success(),
            "git {args:?} failed"
        );
    }
    Command::new("git")
        .args(["add", "-A"])
        .current_dir(dir)
        .status()
        .unwrap();
    Command::new("git")
        .args(["commit", "-q", "-m", "base"])
        .current_dir(dir)
        .status()
        .unwrap();
}

fn git(args: &[&str], dir: &PathBuf) -> String {
    let out = Command::new("git")
        .args(args)
        .current_dir(dir)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "git {args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8_lossy(&out.stdout).to_string()
}

#[test]
fn headless_partial_approval_commits_only_accepted_files() {
    let dir = tmpdir("partial");
    git_init(&dir);
    std::fs::write(dir.join("a.txt"), "keep-a\n").unwrap();
    std::fs::write(dir.join("b.txt"), "keep-b\n").unwrap();
    git(&["add", "-A"], &dir);
    git(&["commit", "-q", "-m", "seed"], &dir);

    let batch = write_text(
        &dir,
        "batch.json",
        r#"[
            {"change_id":"c1","document_id":"a.txt","old_text":"keep-a","new_text":"ACCEPTED-a","path":"a.txt"},
            {"change_id":"c2","document_id":"b.txt","old_text":"keep-b","new_text":"REJECTED-b","path":"b.txt"}
        ]"#,
    );
    let decisions = write_text(&dir, "decisions.json", r#"{"c1":"accept","c2":"reject"}"#);
    let cli = Cli {
        input: batch,
        workspace: Some(dir.clone()),
        maps: vec![],
        decide: None,
        decisions: Some(decisions),
        dry_run: false,
        help: false,
    };
    let mut changes = load::load(&cli.input, Some(&dir), &[]).unwrap();
    headless::run(&cli, &mut changes).unwrap();

    assert_eq!(
        std::fs::read_to_string(dir.join("a.txt")).unwrap(),
        "ACCEPTED-a\n"
    );
    assert_eq!(
        std::fs::read_to_string(dir.join("b.txt")).unwrap(),
        "keep-b\n"
    );
    let stat = git(&["show", "--stat", "--oneline", "HEAD"], &dir);
    assert!(stat.contains("a.txt"), "commit should touch a.txt:\n{stat}");
    assert!(
        !stat.contains("b.txt"),
        "commit must not touch b.txt:\n{stat}"
    );
}

#[test]
fn headless_reject_all_leaves_repo_untouched() {
    let dir = tmpdir("reject_all");
    git_init(&dir);
    std::fs::write(dir.join("a.txt"), "original\n").unwrap();
    git(&["add", "-A"], &dir);
    git(&["commit", "-q", "-m", "seed"], &dir);

    let batch = write_text(
        &dir,
        "batch.json",
        r#"[{"change_id":"c1","document_id":"a.txt","old_text":"original","new_text":"changed","path":"a.txt"}]"#,
    );
    let cli = Cli {
        input: batch,
        workspace: Some(dir.clone()),
        maps: vec![],
        decide: Some(DecideMode::RejectAll),
        decisions: None,
        dry_run: false,
        help: false,
    };
    let mut changes = load::load(&cli.input, Some(&dir), &[]).unwrap();
    headless::run(&cli, &mut changes).unwrap();
    assert_eq!(
        std::fs::read_to_string(dir.join("a.txt")).unwrap(),
        "original\n"
    );
    let log = git(&["log", "--oneline"], &dir);
    assert_eq!(log.lines().count(), 1, "no new commit expected:\n{log}");
}

#[test]
fn headless_unreviewed_is_an_error() {
    let dir = tmpdir("unreviewed");
    git_init(&dir);
    std::fs::write(dir.join("a.txt"), "original\n").unwrap();
    let batch = write_text(
        &dir,
        "batch.json",
        r#"[{"change_id":"c1","document_id":"a.txt","old_text":"original","new_text":"changed","path":"a.txt"}]"#,
    );
    let cli = Cli {
        input: batch,
        workspace: Some(dir.clone()),
        maps: vec![],
        decide: None,
        decisions: None,
        dry_run: false,
        help: false,
    };
    let mut changes = load::load(&cli.input, Some(&dir), &[]).unwrap();
    assert!(headless::run(&cli, &mut changes).is_err());
}

#[test]
fn tui_keys_then_commit_in_git_repo() {
    let dir = tmpdir("tui_commit");
    git_init(&dir);
    std::fs::write(dir.join("a.txt"), "old a\n").unwrap();
    std::fs::write(dir.join("b.txt"), "old b\n").unwrap();
    git(&["add", "-A"], &dir);
    git(&["commit", "-q", "-m", "seed"], &dir);

    let batch = write_text(
        &dir,
        "batch.json",
        r#"[
            {"change_id":"c1","document_id":"a.txt","old_text":"old a","new_text":"new a","path":"a.txt"},
            {"change_id":"c2","document_id":"b.txt","old_text":"old b","new_text":"new b","path":"b.txt"}
        ]"#,
    );
    let changes = load::load(&batch, Some(&dir), &[]).unwrap();
    let cli = Cli {
        input: batch,
        workspace: Some(dir.clone()),
        maps: vec![],
        decide: None,
        decisions: None,
        dry_run: false,
        help: false,
    };
    let mut app = tui::app::App::new(changes, cli);
    use crossterm::event::KeyCode;
    use tui::app::Action;
    assert_eq!(app.handle_key(KeyCode::Char('a')), Action::None);
    assert_eq!(app.handle_key(KeyCode::Char('j')), Action::None);
    assert_eq!(app.handle_key(KeyCode::Char('r')), Action::None);
    assert_eq!(app.handle_key(KeyCode::Char('c')), Action::None);
    assert_eq!(app.handle_key(KeyCode::Char('y')), Action::Commit);
    app.do_commit().unwrap();

    assert_eq!(
        std::fs::read_to_string(dir.join("a.txt")).unwrap(),
        "new a\n"
    );
    assert_eq!(
        std::fs::read_to_string(dir.join("b.txt")).unwrap(),
        "old b\n"
    );
    let stat = git(&["show", "--stat", "--oneline", "HEAD"], &dir);
    assert!(stat.contains("a.txt"));
    assert!(!stat.contains("b.txt"));
    assert!(stat.contains("Apply 1 approved change(s)"), "{stat}");
}

#[test]
fn two_hundred_changes_stay_usable() {
    let dir = tmpdir("scale200");
    git_init(&dir);
    let mut batch = String::from("[");
    for f in 0..20 {
        let base = format!("file_{f:03}.txt");
        let mut content = String::new();
        for k in 0..10 {
            content.push_str(&format!("line {f}_{k}\n"));
        }
        std::fs::write(dir.join(&base), content).unwrap();
        for k in 0..10 {
            let i = f * 10 + k;
            if i > 0 {
                batch.push(',');
            }
            batch.push_str(&format!(
                r#"{{"change_id":"c{i}","document_id":"{base}","old_text":"line {f}_{k}","new_text":"line {f}_{k} EDITED","path":"{base}"}}"#
            ));
        }
    }
    batch.push(']');
    let batch_path = write_text(&dir, "batch.json", &batch);
    git(&["add", "-A"], &dir);
    git(&["commit", "-q", "-m", "seed"], &dir);

    let (mut changes, _) = {
        let loaded = load::load(&batch_path, Some(&dir), &[]).unwrap();
        (loaded, ())
    };
    assert_eq!(changes.len(), 200);
    for c in changes.iter_mut() {
        c.decision = Decision::Accepted;
    }
    let t0 = std::time::Instant::now();
    let out = actions::apply_changes(&changes, &dir, false).unwrap();
    let elapsed = t0.elapsed();
    assert_eq!(out.applied.len(), 20);
    assert_eq!(out.failed.len(), 0);
    assert!(elapsed.as_secs() < 10, "200-change apply took {elapsed:?}");
    let content = std::fs::read_to_string(dir.join("file_003.txt")).unwrap();
    assert!(content.contains("line 3_5 EDITED"));
}

#[test]
fn unified_diff_flow_through_git() {
    let dir = tmpdir("diff_flow");
    git_init(&dir);
    std::fs::write(dir.join("x.txt"), "a\nb\nc\n").unwrap();
    git(&["add", "-A"], &dir);
    git(&["commit", "-q", "-m", "seed"], &dir);

    let diff = write_text(
        &dir,
        "change.diff",
        "diff --git a/x.txt b/x.txt\nindex 111..222 100644\n--- a/x.txt\n+++ b/x.txt\n@@ -1,3 +1,3 @@\n a\n-b\n+B!\n c\n",
    );
    let cli = Cli {
        input: diff,
        workspace: Some(dir.clone()),
        maps: vec![],
        decide: Some(DecideMode::AcceptAll),
        decisions: None,
        dry_run: false,
        help: false,
    };
    let mut changes = load::load(&cli.input, Some(&dir), &[]).unwrap();
    headless::run(&cli, &mut changes).unwrap();
    assert_eq!(
        std::fs::read_to_string(dir.join("x.txt")).unwrap(),
        "a\nB!\nc\n"
    );
    let stat = git(&["show", "--stat", "--oneline", "HEAD"], &dir);
    assert!(stat.contains("x.txt"), "{stat}");
}

#[test]
fn dry_run_touches_nothing() {
    let dir = tmpdir("dry_run");
    git_init(&dir);
    std::fs::write(dir.join("a.txt"), "old\n").unwrap();
    git(&["add", "-A"], &dir);
    git(&["commit", "-q", "-m", "seed"], &dir);

    let batch = write_text(
        &dir,
        "batch.json",
        r#"[{"change_id":"c1","document_id":"a.txt","old_text":"old","new_text":"new","path":"a.txt"}]"#,
    );
    let cli = Cli {
        input: batch,
        workspace: Some(dir.clone()),
        maps: vec![],
        decide: Some(DecideMode::AcceptAll),
        decisions: None,
        dry_run: true,
        help: false,
    };
    let mut changes = load::load(&cli.input, Some(&dir), &[]).unwrap();
    headless::run(&cli, &mut changes).unwrap();
    assert_eq!(std::fs::read_to_string(dir.join("a.txt")).unwrap(), "old\n");
    assert_eq!(git(&["log", "--oneline"], &dir).lines().count(), 1);
}
