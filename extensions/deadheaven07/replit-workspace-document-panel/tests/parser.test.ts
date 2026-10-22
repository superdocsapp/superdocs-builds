import { describe, it, expect } from 'vitest';
import { parseProposedChangeBatch } from '../src/utils/parser';

describe('parseProposedChangeBatch', () => {
  it('parses valid nested JSON with string content', () => {
    const content = JSON.stringify({
      content: JSON.stringify({
        batch_id: 'batch-1',
        batch_total: 2,
        changes: [
          {
            change_id: 'ch-1',
            operation: 'replace',
            chunk_id: 'chunk-1',
            old_html: '<p>Old content</p>',
            new_html: '<p>New content</p>',
            ai_explanation: 'Updated for clarity',
          },
          {
            change_id: 'ch-2',
            operation: 'insert',
            chunk_id: 'chunk-2',
            old_html: '',
            new_html: '<p>Added section</p>',
            ai_explanation: 'Added missing information',
          },
        ],
        awaiting_kind: 'approval',
      }),
    });

    const result = parseProposedChangeBatch(content);
    
    expect(result.batch_id).toBe('batch-1');
    expect(result.batch_total).toBe(2);
    expect(result.changes).toHaveLength(2);
    expect(result.changes[0].change_id).toBe('ch-1');
    expect(result.changes[0].operation).toBe('replace');
    expect(result.changes[0].old_html).toBe('<p>Old content</p>');
    expect(result.changes[0].new_html).toBe('<p>New content</p>');
    expect(result.changes[1].operation).toBe('insert');
  });

  it('parses valid nested JSON with object content', () => {
    const content = JSON.stringify({
      content: {
        batch_id: 'batch-2',
        batch_total: 1,
        changes: [
          {
            change_id: 'ch-3',
            operation: 'delete',
            chunk_id: 'chunk-3',
            old_html: '<p>Removed</p>',
            new_html: '',
            ai_explanation: 'Removed outdated info',
          },
        ],
        awaiting_kind: 'approval',
      },
    });

    const result = parseProposedChangeBatch(content);
    
    expect(result.batch_id).toBe('batch-2');
    expect(result.batch_total).toBe(1);
    expect(result.changes[0].operation).toBe('delete');
  });

  it('handles empty changes array', () => {
    const content = JSON.stringify({
      content: JSON.stringify({
        batch_id: 'batch-empty',
        batch_total: 0,
        changes: [],
        awaiting_kind: 'approval',
      }),
    });

    const result = parseProposedChangeBatch(content);
    
    expect(result.batch_id).toBe('batch-empty');
    expect(result.batch_total).toBe(0);
    expect(result.changes).toHaveLength(0);
  });

  it('throws on malformed outer JSON', () => {
    const content = '{ invalid json';
    
    expect(() => parseProposedChangeBatch(content)).toThrow('JSON parse error');
  });

  it('throws on missing content field', () => {
    const content = JSON.stringify({ other_field: 'value' });
    
    expect(() => parseProposedChangeBatch(content)).toThrow("Missing 'content' field");
  });

  it('throws on malformed inner JSON string', () => {
    const content = JSON.stringify({
      content: '{ invalid inner json',
    });
    
    expect(() => parseProposedChangeBatch(content)).toThrow('JSON parse error');
  });

  it('handles missing optional fields gracefully', () => {
    const content = JSON.stringify({
      content: JSON.stringify({
        batch_id: 'batch-minimal',
        changes: [
          {
            change_id: 'ch-min',
            operation: 'replace',
            ai_explanation: 'Test',
          },
        ],
      }),
    });

    const result = parseProposedChangeBatch(content);
    
    expect(result.batch_id).toBe('batch-minimal');
    expect(result.changes[0].chunk_id).toBeUndefined();
    expect(result.changes[0].old_html).toBeUndefined();
    expect(result.changes[0].new_html).toBeUndefined();
  });
});