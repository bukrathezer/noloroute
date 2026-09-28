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
  accommodation: LatLng;
  budget: string | null;
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

export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface SavedRouteSummary {
  id: string;
  name: string;
  city_id: string;
  duration_days: number;
  travel_mode: TravelMode;
  stop_count: number;
  created_at: string;
}

export interface SavedRoute extends SavedRouteSummary {
  plan: PlanResponse;
}

// Sent as "Authorization: Bearer <token>" on every request once the user logs in.
let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers: { ...headers, ...(init?.headers as Record<string, string>) } });
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
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const fetchCities = () => request<City[]>("/api/v1/cities");

export const planRoute = (req: PlanRequest) =>
  request<PlanResponse>("/api/v1/routes/plan", { method: "POST", body: JSON.stringify(req) });

export const register = (email: string, password: string) =>
  request<TokenResponse>("/api/v1/auth/register", { method: "POST", body: JSON.stringify({ email, password }) });

// The login endpoint follows the OAuth2 password flow, which uses form fields, not JSON.
export const login = (email: string, password: string) =>
  request<TokenResponse>("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }).toString(),
  });

export const fetchMe = () => request<User>("/api/v1/auth/me");

export const saveRoute = (plan: PlanResponse, name: string) =>
  request<SavedRoute>("/api/v1/routes", { method: "POST", body: JSON.stringify({ name, plan }) });

export const listSavedRoutes = () => request<SavedRouteSummary[]>("/api/v1/routes");

export const getSavedRoute = (id: string) => request<SavedRoute>(`/api/v1/routes/${encodeURIComponent(id)}`);

export const deleteSavedRoute = (id: string) =>
  request<void>(`/api/v1/routes/${encodeURIComponent(id)}`, { method: "DELETE" });

export const removeStop = (plan: PlanResponse, poiId: string) =>
  request<PlanResponse>("/api/v1/routes/plan/remove-stop", {
    method: "POST",
    body: JSON.stringify({ plan, poi_id: poiId }),
  });

export const updateSavedRoute = (id: string, plan: PlanResponse) =>
  request<SavedRoute>(`/api/v1/routes/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ plan }) });

export const deleteAccount = (password: string) =>
  request<void>("/api/v1/auth/me", { method: "DELETE", body: JSON.stringify({ password }) });

export interface PlaceSuggestion {
  place_id: string;
  main_text: string;
  secondary_text: string;
}

export interface PlaceLocation {
  place_id: string;
  lat: number;
  lng: number;
  address: string;
}

export const placeAutocomplete = (q: string, near: LatLng, sessionToken: string, lang: string) =>
  request<PlaceSuggestion[]>(
    `/api/v1/places/autocomplete?${new URLSearchParams({
      q,
      lat: String(near.lat),
      lng: String(near.lng),
      session_token: sessionToken,
      lang,
    })}`,
  );

export const placeLocation = (placeId: string, sessionToken: string, lang: string) =>
  request<PlaceLocation>(
    `/api/v1/places/${encodeURIComponent(placeId)}?${new URLSearchParams({ session_token: sessionToken, lang })}`,
  );
