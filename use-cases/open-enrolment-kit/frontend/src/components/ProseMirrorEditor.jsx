import React, { useEffect, useRef } from 'react';
import { EditorState } from 'prosemirror-state';
import { EditorView } from 'prosemirror-view';
import { schema as basicSchema } from 'prosemirror-schema-basic';
import { exampleSetup } from 'prosemirror-example-setup';
import { DOMParser, Schema } from 'prosemirror-model';
import { tableNodes, columnResizing, tableEditing } from 'prosemirror-tables';
import 'prosemirror-view/style/prosemirror.css';
import 'prosemirror-menu/style/menu.css';
import 'prosemirror-example-setup/style/style.css';
import 'prosemirror-tables/style/tables.css';

const mySchema = new Schema({
  nodes: basicSchema.spec.nodes.append(
    tableNodes({ tableGroup: 'block', cellContent: 'block+' })
  ),
  marks: basicSchema.spec.marks,
});

const ProseMirrorEditor = ({ initialHtml, onChange }) => {
  const editorRef = useRef(null);
  const viewRef = useRef(null);

  useEffect(() => {
    if (!editorRef.current) return;

    // Parse HTML string into DOM node
    const element = document.createElement('div');
    element.innerHTML = initialHtml || '<p>Start editing here...</p>';
    
    // Use DOMParser to correctly parse the HTML into ProseMirror nodes
    const doc = DOMParser.fromSchema(mySchema).parse(element);

    const state = EditorState.create({
      doc,
      plugins: [
        ...exampleSetup({ schema: mySchema }),
        columnResizing(),
        tableEditing(),
      ]
    });

    viewRef.current = new EditorView(editorRef.current, {
      state,
      dispatchTransaction(transaction) {
        let newState = viewRef.current.state.apply(transaction);
        viewRef.current.updateState(newState);
        
        if (transaction.docChanged && onChange) {
          // Just exporting text for this demo
          onChange(newState.doc.textContent);
        }
      }
    });

    return () => {
      if (viewRef.current) {
        viewRef.current.destroy();
      }
    };
  }, []);

  return (
    <div 
      className="glass-panel" 
      style={{
        padding: '1rem',
        marginTop: '1rem',
        backgroundColor: 'var(--bg-secondary)',
        color: 'white' // Note: ProseMirror default menu expects lighter background or custom styling
      }}
    >
      <div ref={editorRef} />
    </div>
  );
};

export default ProseMirrorEditor;
