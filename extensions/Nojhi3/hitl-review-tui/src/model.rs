#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Decision {
    Unreviewed,
    Accepted,
    Rejected,
    Edited,
}

impl Decision {
    pub fn mark(self) -> &'static str {
        match self {
            Decision::Unreviewed => "[ ]",
            Decision::Accepted => "[A]",
            Decision::Rejected => "[R]",
            Decision::Edited => "[E]",
        }
    }

    pub fn is_applied(self) -> bool {
        matches!(self, Decision::Accepted | Decision::Edited)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HunkLineKind {
    Context,
    Added,
    Removed,
}

#[derive(Clone, Debug)]
pub struct HunkLine {
    pub kind: HunkLineKind,
    pub text: String,
}

#[derive(Clone, Debug)]
pub struct Hunk {
    pub old_pos0: usize,
    pub header: String,
    pub lines: Vec<HunkLine>,
}

impl Hunk {
    pub fn pre_image(&self) -> Vec<String> {
        self.lines
            .iter()
            .filter(|l| l.kind != HunkLineKind::Added)
            .map(|l| l.text.clone())
            .collect()
    }

    pub fn post_image(&self) -> Vec<String> {
        self.lines
            .iter()
            .filter(|l| l.kind != HunkLineKind::Removed)
            .map(|l| l.text.clone())
            .collect()
    }

    pub fn header_for(
        old_start: usize,
        old_count: usize,
        new_start: usize,
        new_count: usize,
    ) -> String {
        format!(
            "@@ -{},{} +{},{} @@",
            old_start, old_count, new_start, new_count
        )
    }
}

#[derive(Clone, Debug)]
pub enum Payload {
    Replace {
        path: String,
        old_raw: String,
        new_raw: String,
    },
    Hunks {
        path: String,
        hunks: Vec<Hunk>,
    },
}

impl Payload {
    pub fn path(&self) -> &str {
        match self {
            Payload::Replace { path, .. } => path,
            Payload::Hunks { path, .. } => path,
        }
    }
}

#[derive(Clone, Debug)]
pub struct Change {
    pub id: String,
    pub explanation: String,
    pub is_html: bool,
    pub payload: Payload,
    pub decision: Decision,
    pub edited_text: Option<String>,
}

impl Change {
    pub fn applied_raw(&self) -> Option<String> {
        match &self.payload {
            Payload::Replace { new_raw, .. } => {
                Some(self.edited_text.clone().unwrap_or_else(|| new_raw.clone()))
            }
            Payload::Hunks { .. } => None,
        }
    }
}
