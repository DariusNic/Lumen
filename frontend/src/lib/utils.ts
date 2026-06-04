import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// tailwind-merge's default classGroups know about stock utilities (text-xs,
// text-sm, text-red-500, …) but not about our custom ones from
// tailwind.config.js (text-h1, text-body-small, text-on-primary, …). Without
// teaching it, it conflates everything starting with `text-` and drops the
// "earlier" one when classes are merged — which silently turned the Pay
// button's white text into invisible-on-purple because the cva-merged
// `text-on-primary text-body-small` collapsed to just `text-body-small`.
//
// Extend with two new groups:
//   - font-size  → our custom text-* size utilities
//   - text-color → our custom text-* color utilities (named after the CSS var)
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [
        {
          text: [
            "display",
            "h1",
            "h2",
            "h3",
            "h4",
            "body-large",
            "body",
            "body-small",
            "uppercase-label",
          ],
        },
      ],
      "text-color": [
        {
          text: [
            "on-primary",
            "on-primary-container",
            "text-primary",
            "text-muted",
            "primary-fixed",
            "primary-fixed-dim",
          ],
        },
      ],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
