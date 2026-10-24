import { useState } from "react";

export default function EditForm({ busy, onSubmit }) {
  const [instruction, setInstruction] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    if (!instruction.trim()) return;
    onSubmit(instruction.trim());
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border border-slate/30 bg-white p-5">
      <h2 className="font-doc text-lg mb-3">Propose an edit</h2>
      <textarea
        className="w-full rounded border border-slate/40 px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-ink/20"
        rows={3}
        placeholder="e.g. Add a paragraph capping each party's liability at $50,000"
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
      />
      <button
        type="submit"
        disabled={busy}
        className="rounded bg-ink text-paper px-4 py-2 text-sm font-medium disabled:opacity-50"
      >
        Propose edit
      </button>
    </form>
  );
}