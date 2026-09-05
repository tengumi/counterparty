/**
 * Keep the feed pinned to the bottom only while the user is already there.
 *
 * Streaming text must not pull the page away from someone reading earlier
 * messages (06 §7), so the container follows new content exclusively when it
 * was scrolled to the end.
 */

import { useEffect, useRef } from 'react';

const THRESHOLD = 48;

export function useAutoScroll(
  containerRef: { current: HTMLElement | null },
  contentRef: { current: HTMLElement | null },
  followOnMount = true,
): () => void {
  const atBottom = useRef(true);

  const onScroll = () => {
    const element = containerRef.current;
    if (element === null) return;
    atBottom.current =
      element.scrollHeight - element.scrollTop - element.clientHeight <= THRESHOLD;
  };

  useEffect(() => {
    const container = containerRef.current;
    const content = contentRef.current;
    if (container === null || content === null) return;
    if (typeof ResizeObserver === 'undefined') return;

    // Scroll restoration runs before this effect. Initialise from the restored
    // location before ResizeObserver delivers its first notification.
    if (!followOnMount) {
      atBottom.current = container.scrollHeight - container.scrollTop - container.clientHeight <= THRESHOLD;
    }

    const observer = new ResizeObserver(() => {
      if (atBottom.current) container.scrollTop = container.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [containerRef, contentRef, followOnMount]);

  return onScroll;
}
