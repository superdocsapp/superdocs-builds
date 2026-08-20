pub fn html_to_text(html: &str) -> String {
    let mut out = String::new();
    let mut chars = html.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '<' => {
                let mut tag = String::new();
                while let Some(&c2) = chars.peek() {
                    if c2 == '>' {
                        chars.next();
                        break;
                    }
                    tag.push(c2);
                    chars.next();
                }
                let name: String = tag
                    .trim_start_matches('/')
                    .trim_start()
                    .chars()
                    .take_while(|c| c.is_ascii_alphanumeric())
                    .collect::<String>()
                    .to_lowercase();
                match name.as_str() {
                    "br" => out.push('\n'),
                    "p" | "div" | "tr" | "li" | "h1" | "h2" | "h3" | "h4" | "table" => {
                        out.push('\n')
                    }
                    "td" | "th" => out.push_str(" | "),
                    _ => {}
                }
            }
            '&' => {
                let mut ent = String::new();
                while let Some(&c2) = chars.peek() {
                    if c2 == ';' {
                        chars.next();
                        break;
                    }
                    ent.push(c2);
                    chars.next();
                }
                let replacement = match ent.as_str() {
                    "amp" => Some("&".to_string()),
                    "lt" => Some("<".to_string()),
                    "gt" => Some(">".to_string()),
                    "quot" => Some("\"".to_string()),
                    "apos" => Some("'".to_string()),
                    "nbsp" => Some(" ".to_string()),
                    _ => None,
                };
                match replacement {
                    Some(r) => out.push_str(&r),
                    None => {
                        if let Some(num) = ent.strip_prefix('#')
                            && let Ok(n) = num.parse::<u32>()
                            && let Some(ch) = char::from_u32(n)
                        {
                            out.push(ch);
                            continue;
                        }
                        out.push('&');
                        out.push_str(&ent);
                        out.push(';');
                    }
                }
            }
            other => out.push(other),
        }
    }
    out.lines()
        .map(|l| l.split_whitespace().collect::<Vec<_>>().join(" "))
        .filter(|l| !l.trim().is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strips_tags_and_entities() {
        let text = html_to_text(
            "<table><tr><th>Plan</th><th>Fee &amp; terms</th></tr>\
             <tr><td>Basic</td><td>$29</td></tr></table>",
        );
        assert!(text.contains("Plan"));
        assert!(text.contains("&"));
        assert!(text.contains("$29"));
        assert!(!text.contains('<'));
        assert!(!text.contains('>'));
    }

    #[test]
    fn keeps_text_between_blocks() {
        let text = html_to_text("<p>Hello <b>world</b></p><p>Second para</p>");
        assert!(text.contains("Hello world"));
        assert!(text.contains("Second para"));
    }
}
