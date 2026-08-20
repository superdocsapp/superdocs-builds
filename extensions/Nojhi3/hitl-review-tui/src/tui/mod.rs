pub mod app;
pub mod ui;

use std::path::Path;
use std::time::Duration;

use crossterm::event::{Event, KeyEventKind};

use app::{Action, App};

pub fn run(app: App) -> Result<(), String> {
    let mut terminal = ratatui::init();
    let mut app = app;
    let result = app_loop(&mut terminal, &mut app);
    ratatui::restore();
    result
}

fn app_loop(terminal: &mut ratatui::DefaultTerminal, app: &mut App) -> Result<(), String> {
    loop {
        terminal
            .draw(|f| ui::render(f, app))
            .map_err(|e| e.to_string())?;
        if crossterm::event::poll(Duration::from_millis(150)).map_err(|e| e.to_string())?
            && let Event::Key(key) = crossterm::event::read().map_err(|e| e.to_string())?
        {
            if key.kind != KeyEventKind::Press {
                continue;
            }
            match app.handle_key(key.code) {
                Action::Quit => break,
                Action::Commit => {
                    if let Err(e) = app.do_commit() {
                        app.message = Some(e);
                    }
                }
                Action::None => {}
            }
        }
    }
    Ok(())
}

pub fn launch_editor(file: &Path) -> Result<Option<std::process::ExitStatus>, String> {
    let mut cmd: Vec<String> = Vec::new();
    for var in ["EDITOR", "VISUAL"] {
        if cmd.is_empty()
            && let Ok(v) = std::env::var(var)
            && !v.is_empty()
        {
            cmd = v.split_whitespace().map(String::from).collect();
        }
    }
    if cmd.is_empty() {
        if cfg!(windows) {
            cmd = vec![
                "cmd".into(),
                "/C".into(),
                "start".into(),
                "/wait".into(),
                "notepad".into(),
            ];
        } else {
            cmd = vec!["vi".into()];
        }
    }
    let mut c = std::process::Command::new(&cmd[0]);
    for a in cmd.iter().skip(1) {
        c.arg(a);
    }
    c.arg(file);
    match c.status() {
        Ok(s) => Ok(Some(s)),
        Err(first) => {
            if cfg!(windows) {
                match std::process::Command::new("notepad").arg(file).status() {
                    Ok(s) => Ok(Some(s)),
                    Err(second) => Err(format!(
                        "editor failed ({first}); notepad fallback failed: {second}"
                    )),
                }
            } else {
                Err(format!("editor failed: {first}"))
            }
        }
    }
}
