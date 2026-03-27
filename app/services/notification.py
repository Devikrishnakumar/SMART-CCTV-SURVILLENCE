import logging
from typing import List
from app.models import IncidentType

logger = logging.getLogger(__name__)

# In production these would be real dispatch integrations
# (CAD system API, SMS gateway, radio dispatch, etc.)

UNIT_MAP = {
    IncidentType.accident: ["ambulance", "police"],
    IncidentType.violence: ["police"],
    IncidentType.fallen_person: ["ambulance"],
    IncidentType.fire: ["fire", "ambulance", "police"],
}


async def notify_emergency_services(
    incident_id: str,
    incident_type: IncidentType,
    location: dict,
) -> List[str]:
    """
    Trigger notifications to relevant emergency services.
    Returns list of services notified.
    """
    services = UNIT_MAP.get(incident_type, [])
    notified = []

    for service in services:
        success = await _dispatch_unit(service, incident_id, location)
        if success:
            notified.append(service)

    logger.info(
        f"Incident {incident_id} ({incident_type.value}): notified {notified}"
    )
    return notified


async def _dispatch_unit(unit_type: str, incident_id: str, location: dict) -> bool:
    """Mock unit dispatch — replace with real CAD/radio integration."""
    logger.info(
        f"[MOCK DISPATCH] Alerting {unit_type.upper()} for incident {incident_id} "
        f"at lat={location.get('latitude')}, lon={location.get('longitude')}"
    )
    # Simulate: return True on success
    return True
