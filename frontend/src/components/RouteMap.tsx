import L from "leaflet";
import { useEffect, useMemo, useRef } from "react";
import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import type { City, DayPlan, LatLng, PlanResponse, Sight } from "../api";
import { cityName, type Lang, STRINGS } from "../i18n";
import { decodePolyline } from "../polyline";
import { stopName } from "../text";
import { dayColor } from "../theme";

export type Point = [number, number];

interface Props {
  cities: City[];
  city: City | null;
  hotel: LatLng | null;
  plan: PlanResponse | null;
  activeDay: number | null;
  highlightedStop: string | null;
  onPickCity: (city: City) => void;
  onPickHotel: (hotel: LatLng) => void;
  onHighlightStop: (poiId: string | null) => void;
  lang: Lang;
  /** The city's sights, most famous first, shown while there is no plan yet. */
  sights: Sight[] | null;
  /** On a phone: how much of the map the floating bar and the panel cover, top and bottom (px). */
  insets: Insets | null;
}

interface Insets {
  top: number;
  bottom: number;
}

const EUROPE_VIEW: { center: Point; zoom: number } = { center: [45.5, 15.5], zoom: 4 };
const CITY_ZOOM = 13;
// With more cities than this, names show on hover only: otherwise they pile up over Europe.
const MAX_CITY_LABELS = 8;
// Of a city's sights shown before planning, the most famous are named on the map.
const NAMED_SIGHTS = 6;

// OpenStreetMap's own tiles: free and keyless for light use with attribution
// (https://operations.osmfoundation.org/policies/tiles/). Dark mode re-colours them in CSS.
// If traffic grows, switch to a keyed provider here.
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

const hotelIcon = L.divIcon({
  className: "hotel-marker",
  html: '<span aria-hidden="true">⌂</span>',
  iconSize: [34, 34],
  iconAnchor: [17, 17],
});

function stopIcon(n: number, color: string, highlighted: boolean) {
  return L.divIcon({
    className: `stop-marker${highlighted ? " highlighted" : ""}`,
    html: `<span style="background:${color}">${n}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

interface Segment {
  points: Point[];
  /** A walk within a transit plan: drawn dotted, so rides stand out. */
  walk: boolean;
  /** An estimated ride (no transit data for the city): drawn dashed, as a straight line. */
  estimated: boolean;
}

/** Street geometry for each leg of a day, falling back to straight lines for estimates. */
function daySegments(day: DayPlan, hotel: Point): Segment[] {
  const legs = [
    ...day.stops.map((s) => ({
      to: [s.latitude, s.longitude] as Point,
      path: s.path_from_previous,
      mode: s.leg_from_previous?.mode,
      estimated: Boolean(s.leg_from_previous?.estimated),
    })),
    { to: hotel, path: day.return_path, mode: day.return_leg?.mode, estimated: Boolean(day.return_leg?.estimated) },
  ];
  let previous = hotel;
  return legs.map((leg) => {
    const points = leg.path ? decodePolyline(leg.path) : [previous, leg.to];
    previous = leg.to;
    return { points, walk: leg.mode === "WALK", estimated: leg.estimated };
  });
}

function ClickToPlaceHotel({ enabled, onPick }: { enabled: boolean; onPick: (p: LatLng) => void }) {
  useMapEvents({
    click(e) {
      if (enabled) onPick({ lat: e.latlng.lat, lng: e.latlng.lng });
    },
  });
  return null;
}

/** Moves the map when the city, plan or focused day changes. */
function ViewController(props: { city: City | null; bounds: Point[] | null; insets: Insets | null }) {
  const { city, bounds } = props;
  const map = useMap();
  // Read when the map moves, not a reason to move it: pulling the panel up mustn't pan the map.
  const insets = useRef(props.insets);
  insets.current = props.insets;
  useEffect(() => {
    const padding = {
      paddingTopLeft: [48, 48 + (insets.current?.top ?? 0)] as Point,
      paddingBottomRight: [48, 48 + (insets.current?.bottom ?? 0)] as Point,
    };
    if (bounds && bounds.length > 0) {
      map.flyToBounds(L.latLngBounds(bounds), { ...padding, duration: 0.8, maxZoom: 15 });
    } else if (city?.center_lat != null && city.center_lng != null) {
      map.flyTo([city.center_lat, city.center_lng], CITY_ZOOM, { duration: 1 });
    } else {
      map.flyTo(EUROPE_VIEW.center, EUROPE_VIEW.zoom, { duration: 0.8 });
    }
  }, [map, city, bounds]);
  return null;
}

export function RouteMap(props: Props) {
  const { cities, city, hotel, plan, activeDay, highlightedStop, onPickCity, onPickHotel, onHighlightStop, lang } =
    props;
  const sights = city && !plan ? props.sights : null;
  const hotelPoint: Point | null = hotel ? [hotel.lat, hotel.lng] : null;

  // What the map should frame: the whole plan, or just the focused day.
  const bounds = useMemo<Point[] | null>(() => {
    if (!plan || !hotel) return null;
    const days = activeDay ? plan.days.filter((d) => d.day_number === activeDay) : plan.days;
    return [[hotel.lat, hotel.lng], ...days.flatMap((d) => d.stops.map((s): Point => [s.latitude, s.longitude]))];
  }, [plan, activeDay, hotel]);

  return (
    <MapContainer center={EUROPE_VIEW.center} zoom={EUROPE_VIEW.zoom} className="map" zoomControl={false}>
      <TileLayer url={TILE_URL} attribution={STRINGS[lang].mapAttribution} maxZoom={19} />
      <ViewController city={city} bounds={bounds} insets={props.insets} />
      {/* Clicking only drops the first pin; after that it is moved by dragging, so a stray click
          on the map can't wipe out a plan. */}
      <ClickToPlaceHotel enabled={Boolean(city) && !hotel} onPick={onPickHotel} />

      {/* Before planning: the city's sights, the best known named, so there is something to see. */}
      {sights?.map((sight, i) => (
        <CircleMarker
          key={`sight-${sight.poi_id}`}
          center={[sight.lat, sight.lng]}
          radius={i < NAMED_SIGHTS ? 7 : 5}
          interactive={false}
          pathOptions={{
            color: "#1d4ed8",
            fillColor: i < NAMED_SIGHTS ? "#3b82f6" : "#93a0bf",
            fillOpacity: i < NAMED_SIGHTS ? 0.95 : 0.7,
            weight: i < NAMED_SIGHTS ? 2 : 1,
          }}
        >
          {i < NAMED_SIGHTS && (
            <Tooltip permanent direction="top" offset={[0, -6]} className="city-label">
              {(lang === "tr" && sight.name_tr) || sight.name}
            </Tooltip>
          )}
        </CircleMarker>
      ))}

      {!city &&
        cities.map(
          (c) =>
            c.center_lat != null &&
            c.center_lng != null && (
              <CircleMarker
                key={c.id}
                center={[c.center_lat, c.center_lng]}
                radius={9}
                pathOptions={{ color: "#1d4ed8", fillColor: "#3b82f6", fillOpacity: 0.9, weight: 3 }}
                eventHandlers={{ click: () => onPickCity(c) }}
              >
                <Tooltip
                  permanent={cities.length <= MAX_CITY_LABELS}
                  direction="top"
                  offset={[0, -8]}
                  className="city-label"
                >
                  {cityName(c, lang)}
                </Tooltip>
              </CircleMarker>
            ),
        )}

      {plan &&
        hotelPoint &&
        plan.days.map((day) => {
          const dimmed = activeDay !== null && activeDay !== day.day_number;
          const color = dayColor(day.day_number);
          return daySegments(day, hotelPoint).map((segment, i) => (
            <Polyline
              key={`path-${day.day_number}-${i}`}
              positions={segment.points}
              interactive={false}
              pathOptions={{
                color,
                weight: dimmed ? 3 : 5,
                opacity: dimmed ? 0.2 : 0.85,
                dashArray: segment.walk ? "1 9" : segment.estimated ? "10 8" : undefined,
                lineCap: "round",
              }}
            />
          ));
        })}

      {plan &&
        plan.days.flatMap((day) =>
          activeDay !== null && activeDay !== day.day_number
            ? []
            : day.stops.map((stop) => (
                <Marker
                  key={stop.poi_id}
                  position={[stop.latitude, stop.longitude]}
                  icon={stopIcon(stop.order_in_day, dayColor(day.day_number), highlightedStop === stop.poi_id)}
                  zIndexOffset={highlightedStop === stop.poi_id ? 1000 : 0}
                  eventHandlers={{
                    mouseover: () => onHighlightStop(stop.poi_id),
                    mouseout: () => onHighlightStop(null),
                  }}
                >
                  <Tooltip direction="top" offset={[0, -14]}>
                    <strong>{stopName(stop, lang)}</strong>
                    <br />
                    {STRINGS[lang].result.day(day.day_number)} · {STRINGS[lang].result.stopNumber(stop.order_in_day)}
                  </Tooltip>
                </Marker>
              )),
        )}

      {hotelPoint && (
        <Marker
          position={hotelPoint}
          icon={hotelIcon}
          draggable
          zIndexOffset={2000}
          eventHandlers={{
            dragend: (e) => {
              const p = (e.target as L.Marker).getLatLng();
              onPickHotel({ lat: p.lat, lng: p.lng });
            },
          }}
        />
      )}
    </MapContainer>
  );
}
