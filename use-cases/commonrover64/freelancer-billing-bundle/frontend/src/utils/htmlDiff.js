// strips HTML tags for clean display, adding readable separators for table rows/cells
// so a diff like "<tr><td>Date</td>..." doesn't collapse into unreadable run-on text.
export function stripHtml(html) {
    return html
        .replace(/<tr[^>]*>/gi, "\n")
        .replace(/<\/?(td|th)[^>]*>/gi, " | ")
        .replace(/<[^>]+>/g, "")
        .replace(/\s+\|\s+/g, " | ")
        .replace(/\n\s*\|\s*/g, "\n")
        .trim();
}
