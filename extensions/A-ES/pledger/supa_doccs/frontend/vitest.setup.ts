import '@testing-library/jest-dom'

// Polyfill DOM methods missing from jsdom that Radix UI components require
if (typeof Element !== 'undefined') {
  Element.prototype.hasPointerCapture = Element.prototype.hasPointerCapture || (() => false);
  Element.prototype.setPointerCapture = Element.prototype.setPointerCapture || (() => {});
  Element.prototype.releasePointerCapture = Element.prototype.releasePointerCapture || (() => {});
  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || (() => {});
}

// Polyfill window.DOMRect for Radix Popper
if (typeof window !== 'undefined' && !window.DOMRect) {
  (window as unknown as Record<string, unknown>).DOMRect = class DOMRect {
    x = 0; y = 0; width = 0; height = 0; top = 0; right = 0; bottom = 0; left = 0;
    toJSON() { return {}; }
  };
}

// ResizeObserver polyfill for Radix components
if (typeof window !== 'undefined' && !window.ResizeObserver) {
  (window as unknown as Record<string, unknown>).ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
