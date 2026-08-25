import React, { useEffect, useRef, forwardRef, useImperativeHandle } from 'react';
import { EditorState } from 'prosemirror-state';
import { EditorView } from 'prosemirror-view';
import { DOMParser, DOMSerializer } from 'prosemirror-model';
import { exampleSetup } from 'prosemirror-example-setup';
import { schema } from './schema';

import 'prosemirror-view/style/prosemirror.css';
import 'prosemirror-menu/style/menu.css';
import 'prosemirror-example-setup/style/style.css';

const ProseMirrorEditor = forwardRef(({ initialHtml, onChange }, ref) => {
  const editorRef = useRef(null);
  const viewRef = useRef(null);

  useImperativeHandle(ref, () => ({
    getHtml: () => {
      if (!viewRef.current) return '';
      const div = document.createElement('div');
      const fragment = DOMSerializer.fromSchema(schema).serializeFragment(viewRef.current.state.doc.content);
      div.appendChild(fragment);
      return div.innerHTML;
    },
    setHtml: (html) => {
      if (!viewRef.current) return;
      const div = document.createElement('div');
      div.innerHTML = html;
      const doc = DOMParser.fromSchema(schema).parse(div);
      const newState = EditorState.create({
        doc,
        plugins: exampleSetup({ schema })
      });
      viewRef.current.updateState(newState);
    }
  }));

  useEffect(() => {
    if (!editorRef.current) return;

    const div = document.createElement('div');
    div.innerHTML = initialHtml || '<p></p>';
    const doc = DOMParser.fromSchema(schema).parse(div);

    const state = EditorState.create({
      doc,
      plugins: exampleSetup({ schema })
    });

    viewRef.current = new EditorView(editorRef.current, {
      state,
      dispatchTransaction(transaction) {
        const newState = viewRef.current.state.apply(transaction);
        viewRef.current.updateState(newState);
        
        if (transaction.docChanged && onChange) {
          onChange();
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
      className="prosemirror-superdocs-container" 
      style={{
        padding: '1rem',
        marginTop: '1rem',
        backgroundColor: 'var(--bg-secondary)',
        color: 'white'
      }}
    >
      <div ref={editorRef} />
    </div>
  );
});

export default ProseMirrorEditor;
