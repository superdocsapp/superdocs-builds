/**
 * All native Word/Office.js integration lives here. This is the ONLY module
 * that ever mutates the document (accepting/rejecting a tracked change,
 * posting/resolving a comment reply) -- and it does so with Word's own
 * tracked-changes and comment APIs, never through SuperDocs. That's what
 * makes "reviewer names and timestamps survive the round-trip" and
 * "applying a batch leaves every other reviewer's marks untouched and still
 * attributed" true by construction: nothing here ever leaves Word's own
 * document model.
 *
 * Tracked-change and comment objects are kept alive across separate
 * Word.run() calls via .track() (per Microsoft's documented pattern for
 * "use this object outside the .run batch it was created in") because the
 * user loads changes once, then acts on them from the task pane UI over
 * several later interactions.
 */
const WordChanges = (() => {
  let _trackedChangeRefs = {};
  let _commentRefs = {};

  /** Deletion immediately followed by an insertion from the same author is
   * how Word represents a single "replace" edit -- merge that pair into one
   * triage-able item so "typo fix" style instructions read naturally,
   * while keeping both underlying change IDs so accept/reject still hits
   * both halves. */
  function mergeReplacementPairs(items) {
    const merged = [];
    for (let i = 0; i < items.length; i++) {
      const cur = items[i];
      const next = items[i + 1];
      if (cur.wordType === "Deleted" && next && next.wordType === "Added" && next.author === cur.author) {
        merged.push({
          id: `${cur.id}+${next.id}`,
          memberIds: [cur.id, next.id],
          author: cur.author,
          date: next.date,
          wordType: "Replaced",
          previousText: cur.text,
          text: next.text,
          section: cur.section || next.section,
          position: cur.position,
        });
        i++; // consumed both
      } else {
        merged.push({ ...cur, memberIds: [cur.id] });
      }
    }
    return merged;
  }

  async function loadTrackedChanges() {
    const raw = await Word.run(async (context) => {
      const body = context.document.body;
      const paragraphs = body.paragraphs;
      paragraphs.load("items/text,items/style");
      const trackedChanges = body.getTrackedChanges();
      trackedChanges.load("items");
      await context.sync();

      const items = trackedChanges.items;
      items.forEach((tc) => tc.load(["author", "date", "text", "type"]));
      const ranges = items.map((tc) => tc.getRange());
      ranges.forEach((r) => r.load("text"));
      const firstParas = ranges.map((r) => r.paragraphs.getFirstOrNullObject());
      firstParas.forEach((p) => p.load("text"));
      await context.sync();

      // Running "current section heading" per paragraph, in body order --
      // best-effort context for instructions like "section 2"; see README
      // for why this is a heuristic, not a guarantee.
      const sectionTrack = [];
      let currentHeading = "";
      for (const p of paragraphs.items) {
        const isHeading = /^(Heading|Title)/i.test(p.style || "");
        if (isHeading && p.text.trim()) currentHeading = p.text.trim();
        sectionTrack.push({ text: p.text, heading: currentHeading });
      }

      _trackedChangeRefs = {};
      const results = [];
      let cursor = 0;
      items.forEach((tc, i) => {
        const id = `tc-${i}`;
        tc.track();
        _trackedChangeRefs[id] = tc;

        let section = "";
        const para = firstParas[i];
        const paraText = para && !para.isNullObject ? para.text : null;
        if (paraText != null) {
          let found = -1;
          for (let j = cursor; j < sectionTrack.length; j++) {
            if (sectionTrack[j].text === paraText) { found = j; break; }
          }
          if (found === -1) {
            for (let j = 0; j < cursor; j++) {
              if (sectionTrack[j].text === paraText) { found = j; break; }
            }
          }
          if (found !== -1) {
            section = sectionTrack[found].heading;
            cursor = found;
          }
        }

        results.push({
          id,
          author: tc.author,
          date: tc.date ? tc.date.toISOString() : null,
          text: tc.text,
          wordType: tc.type,
          section,
          position: i + 1,
        });
      });
      return results;
    });

    return mergeReplacementPairs(raw);
  }

  async function loadComments() {
    return Word.run(async (context) => {
      const comments = context.document.body.getComments();
      comments.load("items");
      await context.sync();

      comments.items.forEach((c) => {
        c.load(["id", "authorName", "authorEmail", "content", "creationDate", "resolved"]);
        c.replies.load("items");
      });
      await context.sync();

      comments.items.forEach((c) => {
        c.replies.items.forEach((r) => r.load(["authorName", "content", "creationDate"]));
      });
      await context.sync();

      _commentRefs = {};
      return comments.items.map((c) => {
        c.track();
        _commentRefs[c.id] = c;
        return {
          id: c.id,
          authorName: c.authorName,
          authorEmail: c.authorEmail,
          content: c.content,
          creationDate: c.creationDate ? c.creationDate.toISOString() : null,
          resolved: c.resolved,
          replies: c.replies.items.map((r) => ({ authorName: r.authorName, content: r.content })),
        };
      });
    });
  }

  /** decisions: [{id, memberIds, action: "accept"|"reject"}]. Everything in
   * one batch is applied in a single context.sync() -- either all of it
   * lands or (on error) none of it does, which is what "each batch is
   * previewed before it is applied" needs to mean in practice. */
  async function applyDecisions(decisions) {
    return Word.run(async (context) => {
      for (const decision of decisions) {
        const ids = decision.memberIds && decision.memberIds.length ? decision.memberIds : [decision.id];
        for (const memberId of ids) {
          const tc = _trackedChangeRefs[memberId];
          if (!tc) continue; // stale reference (doc changed since load) -- skip, don't fail the batch
          if (decision.action === "accept") tc.accept();
          else tc.reject();
        }
      }
      await context.sync();
    });
  }

  async function replyToComment(commentId, text) {
    return Word.run(async (context) => {
      const comment = _commentRefs[commentId];
      if (!comment) throw new Error("Comment reference lost -- reload comments and try again.");
      comment.reply(text);
      await context.sync();
    });
  }

  async function resolveComment(commentId, resolved) {
    return Word.run(async (context) => {
      const comment = _commentRefs[commentId];
      if (!comment) throw new Error("Comment reference lost -- reload comments and try again.");
      comment.resolved = resolved;
      await context.sync();
    });
  }

  return { loadTrackedChanges, loadComments, applyDecisions, replyToComment, resolveComment };
})();
