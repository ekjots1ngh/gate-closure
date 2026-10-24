import { useLayoutEffect, useRef, useState, type RefObject } from 'react';

/** The rendered size of an element, kept current by a ResizeObserver, so charts can fill their panel. */
export function useSize<T extends HTMLElement>(fallback = { width: 600, height: 300 }): [RefObject<T>, { width: number; height: number }] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const { width, height } = el.getBoundingClientRect();
      if (width > 0 && height > 0) setSize({ width: Math.round(width), height: Math.round(height) });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, size];
}

export function useWidth<T extends HTMLElement>(fallback = 600): [RefObject<T>, number] {
  const [ref, size] = useSize<T>({ width: fallback, height: 1 });
  return [ref, size.width];
}
