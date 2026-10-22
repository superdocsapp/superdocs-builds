import { diffHtml, stripTags } from '../diff.js';

/**
 * Word-level inline diff for one change.
 *
 * Both conditions of the diff-granularity factor render through this, so the
 * *diff itself* looks identical in section and whole-document mode. Only the
 * surrounding context differs. That is what makes the factor a clean
 * manipulation rather than two unrelated renderers.
 */
export function DiffView({ change }) {
  const ops = diffHtml(change.old_html, change.new_html);
  const isDelete = !change.new_html;

  return (
    <div className="diff">
      {isDelete && <p className="diff-flag">This change deletes the passage below.</p>}
      <p className="diff-body">
        {ops.map((op, i) => {
          const text = op.tokens.join('');
          if (op.type === 'equal') return <span key={i}>{text}</span>;
          if (op.type === 'delete') return <del key={i}>{text}</del>;
          return <ins key={i}>{text}</ins>;
        })}
      </p>
    </div>
  );
}

/** The full document with the changed chunk highlighted in place. */
export function WholeDocumentView({ documentHtml, change }) {
  const target = stripTags(change.old_html);

  // Locate the changed chunk inside the document by its visible text. The
  // corpus stores chunk ids, but the source document is plain HTML without
  // them, so text is the reliable join.
  const plain = stripTags(documentHtml);
  const index = target ? plain.indexOf(target) : -1;

  if (index === -1) {
    return (
      <div className="whole-doc">
        <p className="diff-flag">
          Showing the change on its own; the surrounding passage could not be located.
        </p>
        <DiffView change={change} />
      </div>
    );
  }

  return (
    <div className="whole-doc">
      <p className="context">{plain.slice(Math.max(0, index - 700), index)}</p>
      <div className="highlight">
        <DiffView change={change} />
      </div>
      <p className="context">{plain.slice(index + target.length, index + target.length + 700)}</p>
    </div>
  );
}
