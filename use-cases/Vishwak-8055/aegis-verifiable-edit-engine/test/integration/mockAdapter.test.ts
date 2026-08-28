import { describe, it, expect } from 'vitest';
import { MockSuperDocClient } from '../../src/execution/mockSuperDocClient.js';
import { fixedResult } from '../../src/execution/scenarioResolvers.js';
import { SuperDocError } from '../../src/execution/errors.js';

describe('MockSuperDocClient', () => {
  it('proposes an edit as a tracked change and accepts it', async () => {
    const client = new MockSuperDocClient({ resolver: fixedResult('after content') });
    const session = await client.open({ documentId: 'd1', content: 'before content' });
    const proposed = await session.proposeEdit('do something');
    expect(proposed.changeMode).toBe('tracked');
    expect(proposed.resultDocument).toBe('after content');
    const receipt = await session.decideTrackedChanges('accept');
    expect(receipt.status).toBe('applied');
    await session.close();
  });

  it('rejects a tracked change and reports that in the receipt', async () => {
    const client = new MockSuperDocClient({ resolver: fixedResult('after content') });
    const session = await client.open({ documentId: 'd1', content: 'before content' });
    await session.proposeEdit('do something');
    const receipt = await session.decideTrackedChanges('reject');
    expect(receipt.status).toBe('rejected');
  });

  it('throws a structured, correlation-ID error when there is no pending change to decide on', async () => {
    const client = new MockSuperDocClient({ resolver: fixedResult('x') });
    const session = await client.open({ documentId: 'd1', content: 'y' });
    await expect(session.decideTrackedChanges('accept')).rejects.toThrow(SuperDocError);
  });

  it('never leaves a session in a pending state after close() (implicit reject as a safety net)', async () => {
    const client = new MockSuperDocClient({ resolver: fixedResult('x') });
    const session = await client.open({ documentId: 'd1', content: 'y' });
    await session.proposeEdit('do something');
    await session.close();
    await expect(session.proposeEdit('do something else')).rejects.toThrow('closed');
  });

  it('always resolves each attempt against the ORIGINAL content, never a rejected prior attempt', async () => {
    let seenContent: string[] = [];
    const client = new MockSuperDocClient({
      resolver: ({ currentContent }) => {
        seenContent.push(currentContent);
        return { resultDocument: `${currentContent} [edited attempt ${seenContent.length}]` };
      },
    });
    const session = await client.open({ documentId: 'd1', content: 'ORIGINAL' });
    await session.proposeEdit('first try');
    await session.decideTrackedChanges('reject');
    await session.proposeEdit('second try');
    expect(seenContent).toEqual(['ORIGINAL', 'ORIGINAL']);
  });

  it('simulates an open() failure on the configured attempt, then can succeed on a later attempt', async () => {
    const client = new MockSuperDocClient({ resolver: fixedResult('x'), failOpenOnAttempt: 1 });
    await expect(client.open({ documentId: 'd1', content: 'y' })).rejects.toThrow(SuperDocError);
    const session = await client.open({ documentId: 'd1', content: 'y' }); // 2nd attempt succeeds
    expect(session.sessionId).toBe('d1');
  });

  it('produces a user-safe message and a redacted log payload that never leaks a token', () => {
    const error = new SuperDocError('failed with token=sk-abcdefghijklmnop', 'X', 'corr-1');
    expect(error.toUserSafeMessage()).not.toContain('sk-abcdefghijklmnop');
    expect(JSON.stringify(error.toLogPayload())).not.toContain('sk-abcdefghijklmnop');
  });
});
