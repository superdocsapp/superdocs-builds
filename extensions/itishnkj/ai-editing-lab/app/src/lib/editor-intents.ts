/**
 * Tiny pub/sub used by the app shell to ask the editor page to run an action
 * (open the upload picker or the new-document dialog) after navigation.
 * If no editor page is mounted yet, the intent is buffered until one
 * subscribes, so sidebar actions work from any route.
 */
export type EditorIntent = 'upload-document' | 'new-document';

let pendingIntent: EditorIntent | null = null;
const listeners = new Set<(intent: EditorIntent) => void>();

export function requestEditorIntent(intent: EditorIntent) {
  if (listeners.size > 0) {
    listeners.forEach((listener) => listener(intent));
    return;
  }
  pendingIntent = intent;
}

export function subscribeToEditorIntents(
  listener: (intent: EditorIntent) => void,
): () => void {
  listeners.add(listener);
  if (pendingIntent) {
    const buffered = pendingIntent;
    pendingIntent = null;
    listener(buffered);
  }
  return () => {
    listeners.delete(listener);
  };
}
