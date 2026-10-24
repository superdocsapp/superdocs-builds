import { useState } from "react";

export default function CheckinForm({ busy, onSubmit }) {
  const [comment, setComment] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    if (!comment.trim()) return;
    onSubmit(comment.trim());
    setComment("");
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border border-slate/30 bg-white p-5">
      <h2 className="font-doc text-lg mb-3">Check in</h2>
      <input
        className="w-full rounded border border-slate/40 px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-ink/20"
        placeholder="Version comment, e.g. Added liability cap clause"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      <button
        type="submit"
        disabled={busy}
        className="rounded bg-ink text-paper px-4 py-2 text-sm font-medium disabled:opacity-50"
      >
        Check in as new version
      </button>
    </form>
  );
}