use std::path::PathBuf;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DecideMode {
    AcceptAll,
    RejectAll,
}

pub struct Cli {
    pub input: PathBuf,
    pub workspace: Option<PathBuf>,
    pub maps: Vec<(String, String)>,
    pub decide: Option<DecideMode>,
    pub decisions: Option<PathBuf>,
    pub dry_run: bool,
    pub help: bool,
}

pub fn parse(args: &[String]) -> Result<Cli, String> {
    let mut cli = Cli {
        input: PathBuf::new(),
        workspace: None,
        maps: Vec::new(),
        decide: None,
        decisions: None,
        dry_run: false,
        help: false,
    };
    let mut it = args.iter().peekable();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--workspace" => {
                let v = it.next().ok_or("--workspace needs a value")?;
                cli.workspace = Some(PathBuf::from(v));
            }
            "--map" => {
                let kv = it.next().ok_or("--map needs doc_id=path")?;
                let (k, v) = kv.split_once('=').ok_or("--map expects doc_id=path")?;
                cli.maps.push((k.to_string(), v.to_string()));
            }
            "--decide" => {
                let v = it.next().ok_or("--decide needs accept-all or reject-all")?;
                cli.decide = Some(match v.as_str() {
                    "accept-all" => DecideMode::AcceptAll,
                    "reject-all" => DecideMode::RejectAll,
                    other => return Err(format!("unknown --decide value {other:?}")),
                });
            }
            "--decisions" => {
                let v = it.next().ok_or("--decisions needs a file")?;
                cli.decisions = Some(PathBuf::from(v));
            }
            "--dry-run" => cli.dry_run = true,
            "-h" | "--help" => cli.help = true,
            other if other.starts_with('-') => return Err(format!("unknown option {other}")),
            other => {
                if cli.input.as_os_str().is_empty() {
                    cli.input = PathBuf::from(other);
                } else {
                    return Err(format!("unexpected argument {other}"));
                }
            }
        }
    }
    if !cli.help && cli.input.as_os_str().is_empty() {
        return Err("missing input file (JSON batch or unified diff)".into());
    }
    Ok(cli)
}

pub fn usage() -> String {
    "hitl-review-tui - review proposed changes in the terminal, commit the approved batch\n\
         \n\
         USAGE:\n\
         \x20 hitl-review-tui [OPTIONS] <input>\n\
         \n\
         ARGS:\n\
         \x20 <input>                pending_changes.json batch or a unified diff file (.diff/.patch)\n\
         \n\
         OPTIONS:\n\
         \x20 --workspace <dir>      git repo / file root for apply + commit (omit = review only)\n\
         \x20 --map <doc=path>       map a document_id to a target file path (repeatable)\n\
         \x20 --decide <mode>        headless: accept-all | reject-all\n\
         \x20 --decisions <file>     headless: JSON { change_id: \"accept\"|\"reject\" }\n\
         \x20 --dry-run              plan only, touch nothing\n\
         \x20 -h, --help             show this help\n\
         \n\
         KEYS (interactive):\n\
         \x20 j/k move | a accept | r reject | u undo | e edit ($EDITOR) | n next unreviewed\n\
         \x20 f filter | t raw/html toggle | [ ] scroll diff | 0 top | c commit | q quit".to_string()
}
