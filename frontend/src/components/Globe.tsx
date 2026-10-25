import { useEffect, useMemo, useRef } from "react";
import type { City } from "../api";
import { GLOBE_DOTS } from "../globeDots";
import { cityName, type Lang } from "../i18n";

// The welcome screen's globe: land as dots (Natural Earth, see globeDots.ts), turning slowly, with
// the app's cities on it and arcs from Istanbul to some of the farthest.
const HUB = "istanbul";
const LINKED = ["paris", "london", "new-york", "tokyo", "seoul", "dubai", "bangkok", "singapore", "marrakech"];
const SIZE = 680;
const CENTER = SIZE / 2;
const RADIUS = 300;
const TILT = (22 * Math.PI) / 180; // the north pole leans towards the viewer
const SPIN_SECONDS = 70; // one full turn
const FRAME_MS = 33; // ~30 redraws a second are smooth enough for this speed
const ARC_STEPS = 28;
const ARC_LIFT = 0.16; // how far an arc rises above the surface at its middle, as a share of the radius
const START_LNG = (-20 * Math.PI) / 180; // facing Europe, Africa and western Asia

const RAD = Math.PI / 180;
const DOTS = Array.from({ length: GLOBE_DOTS.length / 2 }, (_, i) => [
  (GLOBE_DOTS[2 * i] / 10) * RAD,
  (GLOBE_DOTS[2 * i + 1] / 10) * RAD,
]);

interface Point {
  x: number;
  y: number;
  front: boolean;
}

/** Orthographic projection (latitude, longitude in radians) for a globe turned to `lng0`. */
function project(lat: number, lng: number, lng0: number, lift = 0): Point {
  const r = RADIUS * (1 + lift);
  const cosLat = Math.cos(lat);
  const cosDelta = Math.cos(lng - lng0);
  return {
    x: CENTER + r * cosLat * Math.sin(lng - lng0),
    y: CENTER - r * (Math.cos(TILT) * Math.sin(lat) - Math.sin(TILT) * cosLat * cosDelta),
    front: Math.sin(TILT) * Math.sin(lat) + Math.cos(TILT) * cosLat * cosDelta > 0.02,
  };
}

/** The great circle from a to b ([lat, lng] in radians), lifted in the middle; only its near side. */
function arcPath(a: number[], b: number[], lng0: number): string {
  const vector = ([lat, lng]: number[]) => [Math.cos(lat) * Math.cos(lng), Math.cos(lat) * Math.sin(lng), Math.sin(lat)];
  const p = vector(a);
  const q = vector(b);
  const angle = Math.acos(Math.min(1, p[0] * q[0] + p[1] * q[1] + p[2] * q[2]));
  let d = "";
  let drawing = false;
  for (let i = 0; i <= ARC_STEPS; i++) {
    const t = i / ARC_STEPS;
    const s1 = Math.sin((1 - t) * angle) / Math.sin(angle);
    const s2 = Math.sin(t * angle) / Math.sin(angle);
    const v = [0, 1, 2].map((k) => s1 * p[k] + s2 * q[k]);
    const point = project(Math.asin(v[2]), Math.atan2(v[1], v[0]), lng0, ARC_LIFT * Math.sin(Math.PI * t) * Math.min(1, angle));
    if (point.front) {
      d += `${drawing ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`;
      drawing = true;
    } else {
      drawing = false;
    }
  }
  return d;
}

interface Props {
  cities: City[];
  lang: Lang;
  label: string;
}

export function Globe({ cities, lang, label }: Props) {
  const land = useRef<SVGPathElement>(null);
  const arcs = useRef<SVGPathElement>(null);
  const others = useRef<SVGPathElement>(null);
  const marks = useRef(new Map<string, SVGGElement>());
  const begin = useRef(performance.now());

  const placed = useMemo(
    () =>
      cities
        .filter((c) => c.center_lat != null && c.center_lng != null)
        .map((c) => ({ city: c, at: [(c.center_lat as number) * RAD, (c.center_lng as number) * RAD] })),
    [cities],
  );
  const hub = placed.find((p) => p.city.id === HUB);
  const marked = placed.filter((p) => p.city.id === HUB || LINKED.includes(p.city.id));

  useEffect(() => {
    const draw = (lng0: number) => {
      let dots = "";
      for (const [lat, lng] of DOTS) {
        const p = project(lat, lng, lng0);
        if (p.front) dots += `M${p.x.toFixed(1)} ${p.y.toFixed(1)}h0`;
      }
      land.current?.setAttribute("d", dots);
      let small = "";
      for (const { city, at } of placed) {
        const p = project(at[0], at[1], lng0);
        const mark = marks.current.get(city.id);
        if (mark) {
          mark.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`);
          mark.style.display = p.front ? "" : "none";
        } else if (p.front) {
          small += `M${p.x.toFixed(1)} ${p.y.toFixed(1)}h0`;
        }
      }
      others.current?.setAttribute("d", small);
      const linked = hub ? placed.filter((p) => LINKED.includes(p.city.id)) : [];
      arcs.current?.setAttribute("d", linked.map((p) => arcPath(hub?.at ?? [0, 0], p.at, lng0)).join(""));
    };

    const turnedTo = (now: number) => START_LNG + (((now - begin.current) / 1000) * 2 * Math.PI) / SPIN_SECONDS;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      draw(START_LNG); // still, turned to show Europe and Asia
      return;
    }
    // Drawn at once (no labels in a corner until the first frame), and on from where it was when
    // the cities arrive.
    draw(turnedTo(performance.now()));
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      if (now - last >= FRAME_MS) {
        last = now;
        draw(turnedTo(now));
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [placed, hub]);

  return (
    <svg className="globe" viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={label}>
      <defs>
        <radialGradient id="globe-ocean" cx="40%" cy="35%" r="70%">
          <stop offset="0" stopColor="#0f1c3d" />
          <stop offset="1" stopColor="#060b19" />
        </radialGradient>
      </defs>
      <circle cx={CENTER} cy={CENTER} r={RADIUS + 22} className="globe-halo" />
      <circle cx={CENTER} cy={CENTER} r={RADIUS} fill="url(#globe-ocean)" className="globe-sphere" />
      <path ref={land} className="globe-land" />
      <path ref={arcs} className="globe-arcs" />
      <path ref={others} className="globe-city-dots" />
      {marked.map(({ city }) => (
        <g
          key={city.id}
          ref={(el) => {
            if (el) marks.current.set(city.id, el);
            else marks.current.delete(city.id);
          }}
          className={city.id === HUB ? "globe-mark hub" : "globe-mark"}
        >
          <circle r={city.id === HUB ? 6 : 4} className="globe-pulse" />
          <text x={9} y={-8}>
            {cityName(city, lang)}
          </text>
        </g>
      ))}
    </svg>
  );
}
