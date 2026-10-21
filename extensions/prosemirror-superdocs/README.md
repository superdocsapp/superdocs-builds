# prosemirror-superdocs

A production-ready integration between ProseMirror and the SuperDocs API.

## Features

- **Chunk ID Preservation**: Automatically preserves SuperDocs' `data-chunk-id` attributes on every block-level element.
- **Round-trip Reliability**: Ensures surgical AI edits land exactly where they should.
- **React Component**: Includes a drop-in React component `ProseMirrorEditor` for quick setup.

## Installation

```bash
npm install prosemirror-superdocs
```

## Usage

```jsx
import React, { useRef } from 'react';
import { ProseMirrorEditor } from 'prosemirror-superdocs';

function App() {
  const editorRef = useRef(null);

  const handleSave = () => {
    // Get the HTML containing preserved data-chunk-id attributes
    const html = editorRef.current.getHtml();
    console.log(html);
  };

  return (
    <div>
      <ProseMirrorEditor 
        ref={editorRef} 
        initialHtml="<p data-chunk-id='uuid'>Hello SuperDocs</p>" 
      />
      <button onClick={handleSave}>Save</button>
    </div>
  );
}
```

## Advanced

If you want to build your own component or use the schema directly:

```javascript
import { schema } from 'prosemirror-superdocs';
import { DOMParser, DOMSerializer } from 'prosemirror-model';

// Parse HTML string to ProseMirror Doc
const div = document.createElement('div');
div.innerHTML = "<p data-chunk-id='uuid'>Hello</p>";
const doc = DOMParser.fromSchema(schema).parse(div);

// Serialize back to HTML string
const fragment = DOMSerializer.fromSchema(schema).serializeFragment(doc.content);
const outDiv = document.createElement('div');
outDiv.appendChild(fragment);
console.log(outDiv.innerHTML);
```

---
*Built for the SuperDocs Engineer Task.*
