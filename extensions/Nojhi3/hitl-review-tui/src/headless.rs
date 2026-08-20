use std::collections::HashMap;

use crate::actions;
use crate::cli::{Cli, DecideMode};
use crate::model::{Change, Decision};

pub fn run(cli: &Cli, changes: &mut [Change]) -> Result<(), String> {
    if let Some(file) = &cli.decisions {
        let text = std::fs::read_to_string(file)
            .map_err(|e| format!("cannot read {}: {e}", file.display()))?;
        let map: HashMap<String, String> =
            serde_json::from_str(&text).map_err(|e| format!("invalid decisions file: {e}"))?;
        for c in changes.iter_mut() {
            if let Some(v) = map.get(&c.id) {
                c.decision = match v.as_str() {
                    "accept" => Decision::Accepted,
                    "reject" => Decision::Rejected,
                    other => return Err(format!("bad decision {other:?} for {}", c.id)),
                };
            }
        }
    }
    if let Some(mode) = cli.decide {
        for c in changes.iter_mut() {
            if c.decision == Decision::Unreviewed {
                c.decision = match mode {
                    DecideMode::AcceptAll => Decision::Accepted,
                    DecideMode::RejectAll => Decision::Rejected,
                };
            }
        }
    }
    let unreviewed = changes
        .iter()
        .filter(|c| c.decision == Decision::Unreviewed)
        .count();
    let accepted = changes.iter().filter(|c| c.decision.is_applied()).count();
    let rejected = changes
        .iter()
        .filter(|c| c.decision == Decision::Rejected)
        .count();
    if unreviewed > 0 {
        return Err(format!(
            "{unreviewed} change(s) left unreviewed; every change must be decided in headless mode"
        ));
    }
    println!(
        "reviewed {} change(s): accepted {accepted}, rejected {rejected}",
        changes.len()
    );
    match &cli.workspace {
        Some(ws) => {
            let out = actions::apply_changes(changes, ws, cli.dry_run)?;
            println!("applied {} file(s)", out.applied.len());
            for f in &out.applied {
                println!("  + {f}");
            }
            for f in &out.failed {
                println!("  ! {f}");
            }
            let msg = actions::build_message(accepted, 0, rejected, &out.applied);
            let res = actions::commit_batch(ws, &out.applied, &msg, cli.dry_run)?;
            match res.hash {
                Some(h) => println!("committed: {h}"),
                None => println!("nothing to commit"),
            }
        }
        None => {
            if accepted > 0 {
                println!("no --workspace given: review only, nothing applied or committed");
            }
        }
    }
    Ok(())
}
