import { useCallback, useEffect, useMemo, useRef } from 'react';
import { DecisionClock } from './timing.js';

/**
 * The single timer hook shared by all four condition views.
 *
 * PLAN.md.pdf section 4: "timer starts on render, stops on decision click".
 * Keeping one hook for every condition is the point -- if each view timed
 * itself, a difference between conditions could be a difference between four
 * timer implementations rather than between four presentations.
 *
 * The clock itself lives in timing.js and is tested directly; this is the thin
 * React binding.
 *
 * @param {string[]} visibleChangeIds ids currently on screen. Batch conditions
 *   pass every change; sequential conditions pass exactly one.
 */
export function useDecisionTimer(visibleChangeIds) {
  const clockRef = useRef(null);
  if (clockRef.current === null) clockRef.current = new DecisionClock();
  const clock = clockRef.current;

  // Join on identity, not array reference: a parent re-render producing a new
  // array with the same ids must not restart anybody's clock.
  const key = useMemo(() => visibleChangeIds.join('|'), [visibleChangeIds]);

  useEffect(() => {
    // start() is idempotent for an already-running id, so ids that stay on
    // screen keep their original start time.
    key.split('|').filter(Boolean).forEach((id) => clock.start(id));
  }, [key, clock]);

  const stop = useCallback((changeId) => clock.stop(changeId), [clock]);
  const isOpen = useCallback((changeId) => clock.isOpen(changeId), [clock]);
  const restart = useCallback((changeId) => clock.restart(changeId), [clock]);
  const engage = useCallback((changeId) => clock.engage(changeId), [clock]);

  /**
   * Ref callback that marks a change engaged the moment it is genuinely
   * reached: scrolled at least halfway into view, hovered, or focused.
   *
   * Attach with <section ref={engageRef(change.id)}>. Without this the batch
   * conditions time every change from the batch render, which is what made
   * pilot run 1's decision times meaningless (PROGRESS.md A18).
   */
  const engageRef = useCallback(
    (changeId) => (node) => {
      if (!node) return;
      const mark = () => clock.engage(changeId);

      node.addEventListener('mouseenter', mark, { once: true });
      node.addEventListener('focusin', mark, { once: true });

      if (typeof IntersectionObserver === 'undefined') {
        // Older browser: fall back to hover/focus alone rather than to render
        // time, which is the measure we are trying to get away from.
        return;
      }
      const observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (entry.isIntersecting) {
              mark();
              observer.disconnect();
            }
          }
        },
        { threshold: 0.5 },
      );
      observer.observe(node);
    },
    [clock],
  );

  return { stop, isOpen, restart, engage, engageRef };
}
