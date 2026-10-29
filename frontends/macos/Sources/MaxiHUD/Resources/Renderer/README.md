# Response renderer

These assets ship inside the native app; rendering does not load a CDN.

- [Marked](https://marked.js.org/), version 18.1.1: CommonMark/GFM parsing (MIT).
- [DOMPurify](https://github.com/cure53/DOMPurify), version 3.4.17: sanitizes response HTML (Apache-2.0 or MPL-2.0).
- [highlight.js](https://highlightjs.org/), version 11.12.0: code highlighting (BSD-3-Clause).

`vendor.json` records pinned npm source archives, their registry integrity values,
and the SHA-256 of each vendored JavaScript file. License texts are included next
to those files. `response.js` and `response.css` belong to Maxi.

HTML previews use opaque-origin sandboxed frames. Only the main document may
send native copy/height messages. Preview JavaScript runs locally; CSP and the
navigation delegate block external resources, navigation and backend access.
