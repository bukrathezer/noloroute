// Types mirror the FastAPI schemas (app/schemas). Money fields arrive as strings (Python Decimal).

export type TravelMode = "WALK" | "DRIVE";

export interface City {
  id: string;
  name: string;
  currency_code: string;
  poi_count: number;
  center_lat: number | null;
  center_lng: number | null;
}

export interface LatLng {
  lat: number;
  lng: number;
}

export interface PlanRequest {
  city_id: string;
  accommodation: LatLng;
  duration_days: number;
  budget?: number;
  travel_mode: TravelMode;
}

export interface PlannedStop {
  order_in_day: number;
  poi_id: string;
  name: string;
  category: string;
  latitude: number;
  longitude: number;
  visit_minutes: number;
  travel_minutes_from_previous: number;
  distance_km_from_previous: number;
  path_from_previous: string | null;
  entry_price: string | null;
  rating: number | null;
}

export interface DayPlan {
  day_number: number;
  stops: PlannedStop[];
  return_travel_minutes: number;
  return_distance_km: number;
  return_path: string | null;
  total_travel_minutes: number;
  total_visit_minutes: number;
  routing_source: "google" | "estimate";
}

export interface PlanResponse {
  city_id: string;
  currency_code: string;
  travel_mode: TravelMode;
  duration_days: number;
  total_entry_cost: string;
  unpriced_stop_count: number;
  days: DayPlan[];
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  } catch {
    throw new ApiError("network", 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // Non-JSON error body: keep the status text.
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export const fetchCities = () => request<City[]>("/api/v1/cities");

export const planRoute = (req: PlanRequest) =>
  request<PlanResponse>("/api/v1/routes/plan", { method: "POST", body: JSON.stringify(req) });
