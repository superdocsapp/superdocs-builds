import { describe, it, expect } from 'vitest';
import { extractProtectedValues, normalizeValue } from '../../src/verification/protectedValues.js';

describe('extractProtectedValues', () => {
  it('extracts currency, duration, percentage, identifier, and URL from one sentence without cross-contamination', () => {
    const values = extractProtectedValues(
      'Pay $250 within 30 days (a 1.5% surcharge applies) per Section 4.2, see https://example.com/terms.',
    );
    const kinds = values.map((v) => v.kind);
    expect(kinds).toEqual(expect.arrayContaining(['currency', 'duration', 'percentage', 'identifier', 'url']));
    expect(values.find((v) => v.kind === 'currency')?.normalized).toBe('USD:250.00');
    expect(values.find((v) => v.kind === 'duration')?.normalized).toBe('DUR:30:day');
    expect(values.find((v) => v.kind === 'percentage')?.normalized).toBe('PCT:1.5');
    expect(values.find((v) => v.kind === 'url')?.normalized).toBe('https://example.com/terms');
  });

  it('does not double-count digits already claimed by a higher-priority pattern', () => {
    const values = extractProtectedValues('The deadline is 2027-01-05.');
    expect(values).toHaveLength(1);
    expect(values[0]).toMatchObject({ kind: 'date', normalized: '2027-01-05' });
  });

  it('treats formatting-only numeric differences as equal after normalization', () => {
    expect(normalizeValue('currency', '$1,000.00')).toBe(normalizeValue('currency', '$1000'));
    expect(normalizeValue('integer', '1,000')).toBe(normalizeValue('integer', '1000'));
  });

  it('normalizes equivalent date formats to the same ISO value', () => {
    const iso = normalizeValue('date', '2027-01-05');
    expect(normalizeValue('date', 'January 5, 2027')).toBe(iso);
    expect(normalizeValue('date', '5 January 2027')).toBe(iso);
    expect(normalizeValue('date', '1/5/2027')).toBe(iso);
  });

  it('flags an actual date change as different after normalization', () => {
    expect(normalizeValue('date', 'January 5, 2027')).not.toBe(normalizeValue('date', 'January 6, 2027'));
  });

  it('normalizes 12-hour time to 24-hour', () => {
    expect(normalizeValue('time', '3:00 PM')).toBe('15:00');
    expect(normalizeValue('time', '12:00 AM')).toBe('00:00');
  });
});
