import L from "leaflet";
import { useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import type { City, DayPlan, LatLng, PlanResponse } from "../api";
import { cityName, type Lang, STRINGS } from "../i18n";
import { decodePolyline } from "../polyline";
import { dayColor } from "../theme";

type Point = [number, number];

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
}

const EUROPE_VIEW: { center: Point; zoom: number } = { center: [45.5, 15.5], zoom: 4 };
const CITY_ZOOM = 13;

// OpenStreetMap's own tiles: free and keyless for light use with attribution
// (https://operations.osmfoundation.org/policies/tiles/). Dark mode re-colours them in CSS.
// If traffic grows, switch to a keyed provider here.
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

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
}

/** Street geometry for each leg of a day, falling back to straight lines for estimates. */
function daySegments(day: DayPlan, hotel: Point): Segment[] {
  const legs = [
    ...day.stops.map((s) => ({
      to: [s.latitude, s.longitude] as Point,
      path: s.path_from_previous,
      mode: s.leg_from_previous?.mode,
    })),
    { to: hotel, path: day.return_path, mode: day.return_leg?.mode },
  ];
  let previous = hotel;
  return legs.map((leg) => {
    const points = leg.path ? decodePolyline(leg.path) : [previous, leg.to];
    previous = leg.to;
    return { points, walk: leg.mode === "WALK" };
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
function ViewController({ city, bounds }: { city: City | null; bounds: Point[] | null }) {
  const map = useMap();
  useEffect(() => {
    if (bounds && bounds.length > 0) {
      map.flyToBounds(L.latLngBounds(bounds), { padding: [48, 48], duration: 0.8, maxZoom: 15 });
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
  const hotelPoint: Point | null = hotel ? [hotel.lat, hotel.lng] : null;

  // What the map should frame: the whole plan, or just the focused day.
  const bounds = useMemo<Point[] | null>(() => {
    if (!plan || !hotel) return null;
    const days = activeDay ? plan.days.filter((d) => d.day_number === activeDay) : plan.days;
    return [[hotel.lat, hotel.lng], ...days.flatMap((d) => d.stops.map((s): Point => [s.latitude, s.longitude]))];
  }, [plan, activeDay, hotel]);

  return (
    <MapContainer center={EUROPE_VIEW.center} zoom={EUROPE_VIEW.zoom} className="map" zoomControl={false}>
      <TileLayer url={TILE_URL} attribution={ATTRIBUTION} maxZoom={19} />
      <ViewController city={city} bounds={bounds} />
      {/* Clicking only drops the first pin; after that it is moved by dragging, so a stray click
          on the map can't wipe out a plan. */}
      <ClickToPlaceHotel enabled={Boolean(city) && !hotel} onPick={onPickHotel} />

      {!city &&
        cities.map(
          (c) =>
            c.center_lat != null &&
            c.center_lng != null && (
              <CircleMarker
                key={c.id}
                center={[c.center_lat, c.center_lng]}
                radius={9}
                pathOptions={{ color: "#0f766e", fillColor: "#14b8a6", fillOpacity: 0.9, weight: 3 }}
                eventHandlers={{ click: () => onPickCity(c) }}
              >
                <Tooltip permanent direction="top" offset={[0, -8]} className="city-label">
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
                dashArray: segment.walk ? "1 9" : undefined,
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
                    <strong>{stop.name}</strong>
                    <br />
                    {STRINGS[lang].result.day(day.day_number)} · #{stop.order_in_day}
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
