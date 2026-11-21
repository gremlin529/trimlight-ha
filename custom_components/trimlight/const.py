"""Constants for the Trimlight integration."""

from datetime import timedelta

DOMAIN = "trimlight"

POLL_INTERVAL = timedelta(seconds=60)
# Patterns and schedules change rarely (only from the app), so they're read
# less often than the mode, or straight away when their IDs change.
LIBRARY_INTERVAL = timedelta(minutes=10)
# Polls that may fail in a row (e.g. while the Trimlight app is connected)
# before the controller shows as unavailable.
MAX_MISSED_POLLS = 3

CONF_TYPE = "type"
TYPE_GROUP = "group"
CONF_MEMBERS = "members"

SERVICE_TURN_OFF_IN = "turn_off_in"
SERVICE_TURN_OFF_AT = "turn_off_at"
SERVICE_CANCEL_OFF_TIMER = "cancel_off_timer"
ATTR_MINUTES = "minutes"
ATTR_TIME = "time"
ATTR_OFF_AT = "off_at"
SERVICE_SAVE_PATTERN = "save_pattern"
SERVICE_RENAME_PATTERN = "rename_pattern"
SERVICE_DELETE_PATTERN = "delete_pattern"
SERVICE_COPY_PATTERN = "copy_pattern"
SERVICE_PREVIEW_PATTERN = "preview_pattern"
