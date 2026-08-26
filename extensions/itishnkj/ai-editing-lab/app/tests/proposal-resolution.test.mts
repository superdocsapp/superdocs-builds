import assert from 'node:assert/strict';
import test from 'node:test';
import {
  resolveSiblingProposals,
  runHostedAcceptFlow,
  type SiblingProposal,
} from '../src/lib/proposal-resolution.ts';

type TestProposal = SiblingProposal & { id: string };

function diyProposal(overrides: Partial<TestProposal> = {}): TestProposal {
  return {
    id: 'diy-sibling',
    engine: 'diy',
    engineLabel: 'DIY Toolkit',
    requestId: 'req-1',
    review: null,
    ...overrides,
  };
}

function hostedProposal(overrides: Partial<TestProposal> = {}): TestProposal {
  return {
    id: 'superdocs-sibling',
    engine: 'superdocs',
    engineLabel: 'SuperDocs Hosted',
    requestId: 'req-1',
    review: { reviewId: 'review-1', state: 'awaiting_approval', batchNumber: 1 },
    ...overrides,
  };
}

test('failed hosted cancellation aborts resolution without recording anything', async () => {
  // Editor Compare acceptance: user accepts DIY while a SuperDocs hosted
  // review is still open, and the server-side cancellation FAILS.
  const calls: string[] = [];
  const outcome = await resolveSiblingProposals({
    siblings: [hostedProposal(), diyProposal({ id: 'other-completed' })],
    cancelHostedReview: async (reviewId) => {
      calls.push(`cancel:${reviewId}`);
      throw new Error('provider unavailable');
    },
    onCancelled: (sibling) => calls.push(`cancelled:${sibling.id}`),
    onRejected: (sibling) => calls.push(`rejected:${sibling.id}`),
  });

  assert.equal(outcome.ok, false);
  if (!outcome.ok) assert.equal(outcome.failed.id, 'superdocs-sibling');
  // The cancellation was attempted, but NO terminal state was recorded for
  // the hosted sibling and the completed sibling was left pending for retry.
  assert.deepEqual(calls, ['cancel:review-1']);
});

test('hosted cancellation is confirmed server-side before terminal state is recorded', async () => {
  const calls: string[] = [];
  let cancelSettled = false;
  const outcome = await resolveSiblingProposals({
    siblings: [hostedProposal(), diyProposal()],
    cancelHostedReview: async (reviewId) => {
      calls.push(`cancel:${reviewId}`);
      await Promise.resolve();
      cancelSettled = true;
    },
    onCancelled: (sibling) => {
      assert.equal(
        cancelSettled,
        true,
        'cancelled must only be recorded after the server confirms',
      );
      calls.push(`cancelled:${sibling.id}`);
    },
    onRejected: (sibling) => calls.push(`rejected:${sibling.id}`),
  });

  assert.equal(outcome.ok, true);
  // Hosted cancellation fully resolves first; completed siblings are
  // recorded as rejected only afterwards.
  assert.deepEqual(calls, [
    'cancel:review-1',
    'cancelled:superdocs-sibling',
    'rejected:diy-sibling',
  ]);
});

test('completed-only siblings resolve synchronously as rejected', async () => {
  const calls: string[] = [];
  const outcome = await resolveSiblingProposals({
    siblings: [diyProposal()],
    cancelHostedReview: async () => {
      throw new Error('must not be called when no review is open');
    },
    onCancelled: () => calls.push('cancelled'),
    onRejected: (sibling) => calls.push(`rejected:${sibling.id}`),
  });
  assert.equal(outcome.ok, true);
  assert.deepEqual(calls, ['rejected:diy-sibling']);
});

test('no siblings resolves trivially', async () => {
  const outcome = await resolveSiblingProposals({
    siblings: [],
    cancelHostedReview: async () => {},
    onCancelled: () => assert.fail('no sibling to cancel'),
    onRejected: () => assert.fail('no sibling to reject'),
  });
  assert.equal(outcome.ok, true);
});

test('hosted accept flow resolves siblings BEFORE the hosted accept request', async () => {
  // User accepts the SuperDocs (hosted) proposal while a DIY sibling is
  // still pending: the sibling must be recorded rejected before decideReview
  // is sent, and terminal acceptance only applies after hosted completion.
  const calls: string[] = [];
  const flow = await runHostedAcceptFlow({
    resolveSiblings: async () => {
      const outcome = await resolveSiblingProposals({
        siblings: [diyProposal()],
        cancelHostedReview: async () => {
          throw new Error('no hosted sibling in this scenario');
        },
        onCancelled: () => calls.push('cancelled'),
        onRejected: (sibling) => calls.push(`rejected:${sibling.id}`),
      });
      return outcome.ok;
    },
    decideReview: async () => {
      calls.push('decideReview:accept');
      return { candidateDocumentHtml: '<p>done</p>', review: null };
    },
  });
  assert.equal(flow.status, 'completed');
  assert.deepEqual(calls, ['rejected:diy-sibling', 'decideReview:accept']);
});

test('hosted-selected accept aborts BEFORE decideReview when a sibling cancellation fails', async () => {
  // The selected proposal is hosted AND a sibling holds an open hosted
  // review whose cancellation fails: the flow must abort without ever
  // sending the hosted accept request, leaving the selected review pending
  // and retryable with no server-side state changed.
  const calls: string[] = [];
  const flow = await runHostedAcceptFlow({
    resolveSiblings: async () => {
      const outcome = await resolveSiblingProposals({
        siblings: [hostedProposal({ id: 'sibling-review' })],
        cancelHostedReview: async (reviewId) => {
          calls.push(`cancel:${reviewId}`);
          throw new Error('provider unavailable');
        },
        onCancelled: (sibling) => calls.push(`cancelled:${sibling.id}`),
        onRejected: (sibling) => calls.push(`rejected:${sibling.id}`),
      });
      return outcome.ok;
    },
    decideReview: async () => {
      calls.push('decideReview:accept');
      assert.fail('the hosted accept request must never be sent after a failed sibling cancellation');
    },
  });
  assert.equal(flow.status, 'aborted-sibling-resolution');
  assert.deepEqual(calls, ['cancel:review-1']);
});
