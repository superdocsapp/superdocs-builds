# Browser interaction fix

This build moves the browser application JavaScript from an inline `<script>` block to `/app.js`.
The server serves `/app.js` as a first-class JavaScript resource with no-store caching headers.
This prevents a malformed/stale inline script from disabling every UI handler.

The browser script retains explicit DOMContentLoaded bindings for manuscript/demo/prepare controls,
and the existing SuperDocs functions are available from the external classic script.

Also fixes the PDF ASCII85 decoder typed-array assignment for modern TypeScript/Node runtimes.

The favicon 404 is handled with a 204 response.
