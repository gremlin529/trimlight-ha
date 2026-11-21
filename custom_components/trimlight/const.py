"""Constants for the Trimlight integration."""

from datetime import timedelta

DOMAIN = "trimlight"

POLL_INTERVAL = timedelta(seconds=60)
# Patterns and schedules change rarely (only from the app), so they're read
# less often than the mode, or straight away when their IDs change.
LIBRARY_INTERVAL = timedelta(minutes=10)

SERVICE_TURN_OFF_IN = "turn_off_in"
SERVICE_TURN_OFF_AT = "turn_off_at"
SERVICE_CANCEL_OFF_TIMER = "cancel_off_timer"
ATTR_MINUTES = "minutes"
ATTR_TIME = "time"
ATTR_OFF_AT = "off_at"
