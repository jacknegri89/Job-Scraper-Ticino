"""Freshness states of a cached job. Kept in its own module so every part can share them."""

# Seen in the latest scan of its source.
STATUS_ACTIVE = "active"
# Kept from an earlier scan because its source could not confirm it this time.
STATUS_CACHED = "cached_source_unavailable"
# Not seen for longer than the expiry policy allows, or missing from a complete scan.
STATUS_POSSIBLY_EXPIRED = "possibly_expired"
# The page was checked and still answers.
STATUS_ONLINE_VERIFIED = "online_verified"
# The page was checked and the portal says it is gone (404 or 410).
STATUS_GONE = "gone"

ALL_STATUSES = (STATUS_ACTIVE, STATUS_CACHED, STATUS_POSSIBLY_EXPIRED, STATUS_ONLINE_VERIFIED, STATUS_GONE)

# When two copies of one job are merged, the most reliable state wins.
STATUS_PRECEDENCE = {
    STATUS_ACTIVE: 4,
    STATUS_ONLINE_VERIFIED: 3,
    STATUS_CACHED: 2,
    STATUS_POSSIBLY_EXPIRED: 1,
    STATUS_GONE: 0,
}
