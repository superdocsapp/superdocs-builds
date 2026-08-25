/**
 * @jest-environment jsdom
 */

import { schema } from '../src/schema';
import { DOMParser, DOMSerializer } from 'prosemirror-model';

describe('schema with data-chunk-id preservation', () => {
  it('parses data-chunk-id from a paragraph', () => {
    const div = document.createElement('div');
    div.innerHTML = '<p data-chunk-id="chunk-123">Hello World</p>';
    const doc = DOMParser.fromSchema(schema).parse(div);
    
    expect(doc.content.childCount).toBe(1);
    const p = doc.content.child(0);
    expect(p.type.name).toBe('paragraph');
    expect(p.attrs['data-chunk-id']).toBe('chunk-123');
    expect(p.textContent).toBe('Hello World');
  });

  it('serializes data-chunk-id back to HTML', () => {
    const div = document.createElement('div');
    div.innerHTML = '<p data-chunk-id="chunk-456">Testing serialization</p>';
    const doc = DOMParser.fromSchema(schema).parse(div);
    
    const fragment = DOMSerializer.fromSchema(schema).serializeFragment(doc.content);
    const outDiv = document.createElement('div');
    outDiv.appendChild(fragment);
    
    expect(outDiv.innerHTML).toBe('<p data-chunk-id="chunk-456">Testing serialization</p>');
  });

  it('ignores missing data-chunk-id gracefully', () => {
    const div = document.createElement('div');
    div.innerHTML = '<p>No chunk id here</p>';
    const doc = DOMParser.fromSchema(schema).parse(div);
    
    expect(doc.content.childCount).toBe(1);
    const p = doc.content.child(0);
    expect(p.attrs['data-chunk-id']).toBeNull();
    
    const fragment = DOMSerializer.fromSchema(schema).serializeFragment(doc.content);
    const outDiv = document.createElement('div');
    outDiv.appendChild(fragment);
    
    expect(outDiv.innerHTML).toBe('<p>No chunk id here</p>');
  });
});
