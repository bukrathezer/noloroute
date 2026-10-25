# Import every model here so Base.metadata is complete and string-based
# relationship targets ("POI", "RouteStop", ...) resolve once any model is used.
from app.models.city import City
from app.models.email_code import EmailCode
from app.models.poi import POI
from app.models.route_stop import RouteStop
from app.models.saved_route import SavedRoute
from app.models.shared_plan import SharedPlan
from app.models.user import User

__all__ = ["City", "EmailCode", "POI", "RouteStop", "SavedRoute", "SharedPlan", "User"]
