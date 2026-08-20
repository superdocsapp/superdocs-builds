use ratatui::Frame;
use ratatui::layout::{Constraint, Direction, Layout, Margin, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{
    Block, Clear, List, ListItem, Paragraph, Scrollbar, ScrollbarOrientation, ScrollbarState, Wrap,
};

use crate::diffengine::{ViewKind, render_change};
use crate::model::Decision;

use super::app::{App, Popup};

pub fn render(frame: &mut Frame, app: &App) {
    let area = frame.area();
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Min(1),
            Constraint::Length(4),
        ])
        .split(area);
    render_header(frame, chunks[0], app);
    let main = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(38), Constraint::Percentage(62)])
        .split(chunks[1]);
    render_list(frame, main[0], app);
    render_diff(frame, main[1], app);
    render_footer(frame, chunks[2], app);
    if let Some(p) = &app.popup {
        render_popup(frame, p);
    }
}

fn render_header(frame: &mut Frame, area: Rect, app: &App) {
    let reviewed = app
        .changes
        .iter()
        .filter(|c| c.decision != Decision::Unreviewed)
        .count();
    let accepted = app
        .changes
        .iter()
        .filter(|c| c.decision.is_applied())
        .count();
    let rejected = app
        .changes
        .iter()
        .filter(|c| c.decision == Decision::Rejected)
        .count();
    let title = format!(" HITL REVIEW  {} ", app.input_path);
    let counts = format!(
        "reviewed {reviewed}/{}   accepted {accepted}   rejected {rejected}   unreviewed {}   filter: {}   raw: {}",
        app.changes.len(),
        app.changes.len() - reviewed,
        app.filter.label(),
        if app.show_raw { "on" } else { "off" }
    );
    let block = Block::bordered().title(title);
    frame.render_widget(
        Paragraph::new(Line::from(vec![Span::styled(
            counts,
            Style::default().fg(Color::Cyan),
        )]))
        .block(block),
        area,
    );
}

fn render_list(frame: &mut Frame, area: Rect, app: &App) {
    let indices = app.filtered();
    let items: Vec<ListItem> = indices
        .iter()
        .enumerate()
        .map(|(pos, &idx)| {
            let c = &app.changes[idx];
            let (fg, mods) = match c.decision {
                Decision::Accepted => (Color::Green, Modifier::empty()),
                Decision::Rejected => (Color::Red, Modifier::empty()),
                Decision::Edited => (Color::Yellow, Modifier::BOLD),
                Decision::Unreviewed => (Color::Gray, Modifier::empty()),
            };
            let marker = if pos == app.selected { ">" } else { " " };
            let name = format!(
                "{marker} {} {:3} {}",
                c.decision.mark(),
                pos + 1,
                c.payload.path()
            );
            let mut spans = vec![Span::styled(
                name,
                Style::default().fg(fg).add_modifier(mods),
            )];
            if !c.explanation.is_empty() {
                let ex: String = c.explanation.chars().take(44).collect();
                spans.push(Span::styled(
                    format!("  {ex}"),
                    Style::default().fg(Color::DarkGray),
                ));
            }
            ListItem::new(Line::from(spans))
        })
        .collect();
    let mut state = ratatui::widgets::ListState::default();
    state.select(Some(app.selected.min(indices.len().saturating_sub(1))));
    let block = Block::bordered().title(format!(" changes ({}) ", indices.len()));
    frame.render_stateful_widget(
        List::new(items).block(block).highlight_style(
            Style::default()
                .bg(Color::Indexed(236))
                .add_modifier(Modifier::BOLD),
        ),
        area,
        &mut state,
    );
}

fn render_diff(frame: &mut Frame, area: Rect, app: &App) {
    let Some(c) = app.current() else {
        frame.render_widget(
            Paragraph::new("no change selected").block(Block::bordered().title(" diff ")),
            area,
        );
        return;
    };
    let lines = render_change(c, app.show_raw);
    let mut text_lines: Vec<Line> = Vec::new();
    if !c.explanation.is_empty() {
        text_lines.push(Line::from(vec![Span::styled(
            format!("note: {}", c.explanation),
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::ITALIC),
        )]));
    }
    for v in &lines {
        let style = match v.kind {
            ViewKind::Context => Style::default().fg(Color::Gray),
            ViewKind::Removed => Style::default().fg(Color::Red),
            ViewKind::Added => Style::default().fg(Color::Green),
            ViewKind::Header => Style::default()
                .fg(Color::DarkGray)
                .add_modifier(Modifier::ITALIC),
        };
        let prefix = match v.kind {
            ViewKind::Removed => "- ",
            ViewKind::Added => "+ ",
            ViewKind::Context => "  ",
            ViewKind::Header => "",
        };
        let line = match &v.segments {
            Some(segs) => {
                let mut spans = vec![Span::styled(prefix, style)];
                for (seg, changed) in segs {
                    let mut s = style;
                    if *changed {
                        s = match v.kind {
                            ViewKind::Removed => {
                                s.fg(Color::LightRed).add_modifier(Modifier::CROSSED_OUT)
                            }
                            _ => s.fg(Color::LightGreen).add_modifier(Modifier::UNDERLINED),
                        };
                    }
                    spans.push(Span::styled(seg.clone(), s));
                }
                Line::from(spans)
            }
            None => Line::from(vec![Span::styled(format!("{prefix}{}", v.text), style)]),
        };
        text_lines.push(line);
    }
    let max_scroll = text_lines
        .len()
        .saturating_sub(area.height as usize)
        .saturating_sub(2);
    let scroll = app.scroll.min(max_scroll);
    let block = Block::bordered().title(format!(" diff  {}  (t = raw toggle) ", c.payload.path()));
    let para = Paragraph::new(text_lines.clone())
        .block(block)
        .wrap(Wrap { trim: false })
        .scroll((scroll as u16, 0));
    frame.render_widget(para, area);
    let scrollbar = Scrollbar::new(ScrollbarOrientation::VerticalRight);
    let mut scrollbar_state = ScrollbarState::new(text_lines.len()).position(scroll);
    frame.render_stateful_widget(
        scrollbar,
        area.inner(Margin {
            vertical: 1,
            horizontal: 1,
        }),
        &mut scrollbar_state,
    );
}

fn render_footer(frame: &mut Frame, area: Rect, app: &App) {
    let keys = " j/k move  g/G first/last  a accept  r reject  u undo  e edit($EDITOR)  n next unreviewed  f filter  t raw  [ ] scroll  c commit  q quit ";
    let mut spans = vec![Span::styled(keys, Style::default().fg(Color::White))];
    if let Some(m) = &app.message {
        spans.push(Span::styled(
            format!("  ! {m}"),
            Style::default().fg(Color::Yellow),
        ));
    }
    frame.render_widget(
        Paragraph::new(Line::from(spans)).block(Block::bordered()),
        area,
    );
}

fn render_popup(frame: &mut Frame, popup: &Popup) {
    let area = frame.area();
    let (title, body) = match popup {
        Popup::Commit { message } => (
            " commit ",
            format!("{message}\n\n  y = confirm    n/esc = cancel"),
        ),
        Popup::Quit { remaining } => (
            " quit ",
            format!(
                "{remaining} change(s) not reviewed yet.\n\n  y = quit anyway    n/esc = cancel"
            ),
        ),
    };
    let pop = centered_rect(72, 16, area);
    frame.render_widget(Clear, pop);
    frame.render_widget(
        Paragraph::new(body).block(Block::bordered().title(title)),
        pop,
    );
}

fn centered_rect(w: u16, h: u16, area: Rect) -> Rect {
    let x = area.x + area.width.saturating_sub(w) / 2;
    let y = area.y + area.height.saturating_sub(h) / 2;
    Rect::new(x, y, w.min(area.width), h.min(area.height))
}
