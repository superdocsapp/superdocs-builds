export default function CheckoutPanel({ document, checkedOut, busy, onCheckout, onDiscard }) {
  return (
    <section className="rounded-lg border border-slate/30 bg-white p-5">
      <h2 className="font-doc text-lg mb-1">{document.title}</h2>
      <p className="text-xs text-slate mb-4">
        Currently at version {document.current_version}
        {checkedOut ? " - checked out by you" : ""}
      </p>

      {!checkedOut ? (
        <button
          onClick={onCheckout}
          disabled={busy}
          className="rounded bg-ink text-paper px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          Check out
        </button>
      ) : (
        <button
          onClick={onDiscard}
          disabled={busy}
          className="rounded border border-slate/40 px-4 py-2 text-sm font-medium text-slate disabled:opacity-50"
        >
          Discard checkout
        </button>
      )}
    </section>
  );
}