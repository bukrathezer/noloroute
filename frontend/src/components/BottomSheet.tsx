import { type PointerEvent, type RefObject, useRef } from "react";

/** How far the panel is pulled up over the map on a phone. */
export type SheetState = "peek" | "half" | "full";

// Heights of the positions, as styles.css sets them for the phone layout ("full" is its max-height).
export const PEEK_HEIGHT = 152;
export const HALF_SHARE = 0.52;
// A pull faster than this (px per ms) goes on to the next position.
const FLICK_SPEED = 0.6;

function heights(panel: HTMLElement): Record<SheetState, number> {
  const full = parseFloat(getComputedStyle(panel).maxHeight) || window.innerHeight;
  return { peek: PEEK_HEIGHT, half: Math.min(full, window.innerHeight * HALF_SHARE), full };
}

interface Props {
  panel: RefObject<HTMLElement | null>;
  state: SheetState;
  onChange: (state: SheetState) => void;
  label: string;
}

/** The grip at the top of the phone's panel: drag it up or down, or tap it to open or close the panel. */
export function SheetHandle({ panel, state, onChange, label }: Props) {
  // Set while a drag is on, so the click that ends it doesn't also toggle.
  const dragged = useRef(false);

  const onPointerDown = (e: PointerEvent<HTMLButtonElement>) => {
    const el = panel.current;
    if (!el) return;
    const handle = e.currentTarget;
    const h = heights(el);
    const startY = e.clientY;
    const startHeight = el.getBoundingClientRect().height;
    let lastY = startY;
    let lastTime = e.timeStamp;
    let speed = 0; // px per ms, downwards positive
    dragged.current = false;
    handle.setPointerCapture(e.pointerId);

    const move = (ev: globalThis.PointerEvent) => {
      if (!dragged.current && Math.abs(ev.clientY - startY) < 6) return;
      dragged.current = true;
      el.style.transition = "none";
      el.style.height = `${Math.min(h.full, Math.max(h.peek, startHeight - (ev.clientY - startY)))}px`;
      speed = (ev.clientY - lastY) / Math.max(1, ev.timeStamp - lastTime);
      lastY = ev.clientY;
      lastTime = ev.timeStamp;
    };
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      el.style.transition = "";
      el.style.height = "";
      if (!dragged.current) return;
      const height = startHeight - (lastY - startY);
      let next: SheetState;
      if (speed < -FLICK_SPEED) next = height > h.half ? "full" : "half";
      else if (speed > FLICK_SPEED) next = height < h.half ? "peek" : "half";
      else {
        const order: SheetState[] = ["peek", "half", "full"];
        next = order.reduce((best, s) => (Math.abs(h[s] - height) < Math.abs(h[best] - height) ? s : best));
      }
      onChange(next);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  };

  return (
    <button
      type="button"
      className="sheet-handle"
      aria-label={label}
      aria-expanded={state === "full"}
      onPointerDown={onPointerDown}
      onClick={() => {
        if (dragged.current) {
          dragged.current = false;
          return;
        }
        onChange(state === "full" ? "half" : "full");
      }}
    />
  );
}
