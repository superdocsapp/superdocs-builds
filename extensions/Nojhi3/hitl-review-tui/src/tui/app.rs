use std::path::PathBuf;

use crossterm::event::KeyCode;

use crate::actions;
use crate::cli::Cli;
use crate::model::{Change, Decision, Payload};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Filter {
    All,
    Unreviewed,
    Accepted,
    Rejected,
}

impl Filter {
    pub fn label(self) -> &'static str {
        match self {
            Filter::All => "all",
            Filter::Unreviewed => "unreviewed",
            Filter::Accepted => "accepted",
            Filter::Rejected => "rejected",
        }
    }

    pub fn matches(self, d: Decision) -> bool {
        match self {
            Filter::All => true,
            Filter::Unreviewed => d == Decision::Unreviewed,
            Filter::Accepted => matches!(d, Decision::Accepted | Decision::Edited),
            Filter::Rejected => d == Decision::Rejected,
        }
    }
}

pub enum Popup {
    Commit { message: String },
    Quit { remaining: usize },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    None,
    Quit,
    Commit,
}

pub struct App {
    pub changes: Vec<Change>,
    pub selected: usize,
    pub filter: Filter,
    pub show_raw: bool,
    pub scroll: usize,
    pub popup: Option<Popup>,
    pub message: Option<String>,
    pub workspace: Option<PathBuf>,
    pub dry_run: bool,
    pub input_path: String,
}

impl App {
    pub fn new(changes: Vec<Change>, cli: Cli) -> App {
        App {
            changes,
            selected: 0,
            filter: Filter::All,
            show_raw: false,
            scroll: 0,
            popup: None,
            message: None,
            workspace: cli.workspace,
            dry_run: cli.dry_run,
            input_path: cli.input.display().to_string(),
        }
    }

    pub fn filtered(&self) -> Vec<usize> {
        self.changes
            .iter()
            .enumerate()
            .filter(|(_, c)| self.filter.matches(c.decision))
            .map(|(i, _)| i)
            .collect()
    }

    pub fn current(&self) -> Option<&Change> {
        self.filtered()
            .get(self.selected)
            .map(|&i| &self.changes[i])
    }

    pub fn current_mut(&mut self) -> Option<&mut Change> {
        let idx = self.filtered().get(self.selected).copied();
        idx.and_then(|i| self.changes.get_mut(i))
    }

    pub fn handle_key(&mut self, code: KeyCode) -> Action {
        if self.popup.is_some() {
            return self.handle_popup_key(code);
        }
        match code {
            KeyCode::Char('q') | KeyCode::Esc => {
                let remaining = self
                    .changes
                    .iter()
                    .filter(|c| c.decision == Decision::Unreviewed)
                    .count();
                if remaining > 0 {
                    self.popup = Some(Popup::Quit { remaining });
                    Action::None
                } else {
                    Action::Quit
                }
            }
            KeyCode::Down | KeyCode::Char('j') => self.move_sel(1),
            KeyCode::Up | KeyCode::Char('k') => self.move_sel(-1),
            KeyCode::Home | KeyCode::Char('g') => {
                self.selected = 0;
                Action::None
            }
            KeyCode::End | KeyCode::Char('G') => {
                self.selected = self.filtered().len().saturating_sub(1);
                Action::None
            }
            KeyCode::Char('a') => {
                self.set_decision(Decision::Accepted);
                Action::None
            }
            KeyCode::Char('r') => {
                self.set_decision(Decision::Rejected);
                Action::None
            }
            KeyCode::Char('u') => {
                self.set_decision(Decision::Unreviewed);
                Action::None
            }
            KeyCode::Char('e') => {
                self.edit_current();
                Action::None
            }
            KeyCode::Char('n') => {
                self.next_unreviewed();
                Action::None
            }
            KeyCode::Char('f') => {
                self.cycle_filter();
                Action::None
            }
            KeyCode::Char('t') => {
                self.show_raw = !self.show_raw;
                self.scroll = 0;
                Action::None
            }
            KeyCode::Char('c') => {
                self.open_commit();
                Action::None
            }
            KeyCode::PageDown | KeyCode::Char(']') => {
                self.scroll = self.scroll.saturating_add(8);
                Action::None
            }
            KeyCode::PageUp | KeyCode::Char('[') => {
                self.scroll = self.scroll.saturating_sub(8);
                Action::None
            }
            KeyCode::Char('0') => {
                self.scroll = 0;
                Action::None
            }
            _ => Action::None,
        }
    }

    fn handle_popup_key(&mut self, code: KeyCode) -> Action {
        match code {
            KeyCode::Char('y') => match self.popup.take() {
                Some(Popup::Commit { .. }) => Action::Commit,
                Some(Popup::Quit { .. }) => Action::Quit,
                None => Action::None,
            },
            KeyCode::Char('n') | KeyCode::Esc | KeyCode::Char('q') => {
                self.popup = None;
                Action::None
            }
            _ => Action::None,
        }
    }

    fn move_sel(&mut self, delta: isize) -> Action {
        let n = self.filtered().len();
        if n == 0 {
            return Action::None;
        }
        self.selected = ((self.selected as isize + delta).clamp(0, n as isize - 1)) as usize;
        Action::None
    }

    fn set_decision(&mut self, d: Decision) {
        if let Some(c) = self.current_mut() {
            if d == Decision::Unreviewed {
                c.edited_text = None;
            }
            c.decision = d;
            self.scroll = 0;
            self.clamp_selection();
        }
    }

    fn clamp_selection(&mut self) {
        let n = self.filtered().len();
        if n == 0 {
            self.selected = 0;
        } else {
            self.selected = self.selected.min(n - 1);
        }
    }

    fn next_unreviewed(&mut self) {
        let idxs = self.filtered();
        if idxs.is_empty() {
            return;
        }
        let start = self.selected + 1;
        for off in 0..idxs.len() {
            let pos = (start + off) % idxs.len();
            if self.changes[idxs[pos]].decision == Decision::Unreviewed {
                self.selected = pos;
                self.scroll = 0;
                return;
            }
        }
        self.message = Some("all changes reviewed".into());
    }

    fn cycle_filter(&mut self) {
        self.filter = match self.filter {
            Filter::All => Filter::Unreviewed,
            Filter::Unreviewed => Filter::Accepted,
            Filter::Accepted => Filter::Rejected,
            Filter::Rejected => Filter::All,
        };
        self.clamp_selection();
        self.scroll = 0;
    }

    fn edit_current(&mut self) {
        let Some(c) = self.current() else {
            return;
        };
        let content = match &c.payload {
            Payload::Replace { new_raw, .. } => {
                c.edited_text.clone().unwrap_or_else(|| new_raw.clone())
            }
            Payload::Hunks { hunks, .. } => hunks
                .iter()
                .flat_map(|h| h.post_image())
                .collect::<Vec<_>>()
                .join("\n"),
        };
        let safe_id = c.id.replace(|ch: char| !ch.is_ascii_alphanumeric(), "_");
        let temp = std::env::temp_dir().join(format!("hitl_edit_{safe_id}.txt"));
        if std::fs::write(&temp, &content).is_err() {
            self.message = Some("cannot write temp file for edit".into());
            return;
        }
        match crate::tui::launch_editor(&temp) {
            Ok(Some(status)) if status.success() => {
                let edited = match std::fs::read_to_string(&temp) {
                    Ok(t) => t,
                    Err(_) => {
                        self.message = Some("cannot read edited file".into());
                        return;
                    }
                };
                if edited != content {
                    let idx = self.filtered().get(self.selected).copied();
                    if let Some(i) = idx {
                        match &mut self.changes[i].payload {
                            Payload::Replace { .. } => {
                                self.changes[i].edited_text = Some(edited);
                                self.changes[i].decision = Decision::Edited;
                            }
                            Payload::Hunks { hunks, .. } => {
                                let old: Vec<String> =
                                    hunks.iter().flat_map(|h| h.pre_image()).collect();
                                let new: Vec<String> =
                                    edited.lines().map(|l| l.to_string()).collect();
                                let h = crate::diffengine::rebuild_hunk(
                                    &old,
                                    &new,
                                    hunks.first().map(|h| h.old_pos0).unwrap_or(0),
                                );
                                *hunks = vec![h];
                                self.changes[i].decision = Decision::Edited;
                            }
                        }
                        self.message = Some("change edited".into());
                    }
                } else {
                    self.message = Some("no changes made in editor".into());
                }
            }
            Ok(_) => {
                self.message = Some("editor exited abnormally; change kept as-is".into());
            }
            Err(e) => {
                self.message = Some(format!("editor failed: {e}"));
            }
        }
        let _ = std::fs::remove_file(&temp);
    }

    fn open_commit(&mut self) {
        let accepted = self
            .changes
            .iter()
            .filter(|c| c.decision.is_applied())
            .count();
        if accepted == 0 {
            self.message = Some("no accepted changes to commit".into());
            return;
        }
        if self.workspace.is_none() {
            self.message = Some("no --workspace: review-only mode, cannot commit".into());
            return;
        }
        let mut files: Vec<String> = self
            .changes
            .iter()
            .filter(|c| c.decision.is_applied())
            .map(|c| c.payload.path().to_string())
            .collect();
        files.sort();
        files.dedup();
        let edited = self
            .changes
            .iter()
            .filter(|c| c.decision == Decision::Edited)
            .count();
        let rejected = self
            .changes
            .iter()
            .filter(|c| c.decision == Decision::Rejected)
            .count();
        let message = actions::build_message(accepted, edited, rejected, &files);
        self.popup = Some(Popup::Commit { message });
    }

    pub fn do_commit(&mut self) -> Result<(), String> {
        let ws = self.workspace.clone().ok_or("no workspace given")?;
        let outcome = actions::apply_changes(&self.changes, &ws, self.dry_run)?;
        if !outcome.failed.is_empty() {
            return Err(format!(
                "failed to apply {} change(s): {}",
                outcome.failed.len(),
                outcome.failed.join("; ")
            ));
        }
        let accepted = self
            .changes
            .iter()
            .filter(|c| c.decision.is_applied())
            .count();
        let edited = self
            .changes
            .iter()
            .filter(|c| c.decision == Decision::Edited)
            .count();
        let rejected = self
            .changes
            .iter()
            .filter(|c| c.decision == Decision::Rejected)
            .count();
        let msg = actions::build_message(accepted, edited, rejected, &outcome.applied);
        let res = actions::commit_batch(&ws, &outcome.applied, &msg, self.dry_run)?;
        self.message = match res.hash {
            Some(h) => Some(format!(
                "committed {h} ({} file(s), {} change(s))",
                outcome.applied.len(),
                accepted + edited
            )),
            None => Some("nothing to commit (dry-run)".into()),
        };
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::load;

    fn app_with(changes: Vec<Change>) -> App {
        App {
            changes,
            selected: 0,
            filter: Filter::All,
            show_raw: false,
            scroll: 0,
            popup: None,
            message: None,
            workspace: None,
            dry_run: false,
            input_path: "test".into(),
        }
    }

    fn sample_changes() -> Vec<Change> {
        let text = r#"[
            {"change_id":"c1","document_id":"a.txt","old_text":"x","new_text":"y"},
            {"change_id":"c2","document_id":"b.txt","old_text":"x","new_text":"y"},
            {"change_id":"c3","document_id":"c.txt","old_text":"x","new_text":"y"}
        ]"#;
        load::load_json_batch_for_test(text)
    }

    #[test]
    fn accept_reject_edit_keys() {
        let mut app = app_with(sample_changes());
        assert_eq!(app.handle_key(KeyCode::Char('a')), Action::None);
        assert_eq!(app.changes[0].decision, Decision::Accepted);
        app.handle_key(KeyCode::Char('j'));
        app.handle_key(KeyCode::Char('r'));
        assert_eq!(app.changes[1].decision, Decision::Rejected);
        app.handle_key(KeyCode::Char('u'));
        assert_eq!(app.changes[1].decision, Decision::Unreviewed);
    }

    #[test]
    fn filter_shrinks_list_and_selection_clamps() {
        let mut app = app_with(sample_changes());
        app.handle_key(KeyCode::Char('a'));
        app.handle_key(KeyCode::Char('f'));
        assert_eq!(app.filter, Filter::Unreviewed);
        assert_eq!(app.filtered().len(), 2);
        app.handle_key(KeyCode::Char('a'));
        assert_eq!(app.filtered().len(), 1);
        app.handle_key(KeyCode::Char('a'));
        assert_eq!(app.filtered().len(), 0);
        assert_eq!(app.selected, 0);
    }

    #[test]
    fn quit_pops_up_when_unreviewed_remain() {
        let mut app = app_with(sample_changes());
        assert_eq!(app.handle_key(KeyCode::Char('q')), Action::None);
        assert!(matches!(app.popup, Some(Popup::Quit { .. })));
        assert_eq!(app.handle_key(KeyCode::Char('y')), Action::Quit);
    }

    #[test]
    fn commit_prompt_requires_workspace() {
        let mut app = app_with(sample_changes());
        app.handle_key(KeyCode::Char('a'));
        app.handle_key(KeyCode::Char('c'));
        assert!(app.message.unwrap().contains("review-only"));
    }
}
