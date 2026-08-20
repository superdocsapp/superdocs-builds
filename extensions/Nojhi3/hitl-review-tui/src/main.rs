use std::process::ExitCode;

use hitl_review_tui::{cli, headless, load, tui};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let cli = match cli::parse(&args) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("error: {e}\n\n{}", cli::usage());
            return ExitCode::from(2);
        }
    };
    if cli.help {
        println!("{}", cli::usage());
        return ExitCode::SUCCESS;
    }
    let mut changes = match load::load(&cli.input, cli.workspace.as_deref(), &cli.maps) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("error: {e}");
            return ExitCode::from(1);
        }
    };
    if changes.is_empty() {
        eprintln!("error: no changes found in {}", cli.input.display());
        return ExitCode::from(1);
    }
    let result = if cli.decide.is_some() || cli.decisions.is_some() {
        headless::run(&cli, &mut changes)
    } else {
        tui::run(tui::app::App::new(changes, cli))
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::from(1)
        }
    }
}
