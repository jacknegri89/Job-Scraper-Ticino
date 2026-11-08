# Copy this file to user_config.py and fill in local private settings.
# Keep user_config.py out of version control.

# Your starting point for distance estimates, in decimal degrees (for example 45.83 and 9.03).
# Leave both as None to hide distances in the dashboard.
HOME_LAT = None
HOME_LNG = None
HOME_CITY = "Home"

# Profile sent to the AI model when assessing whether a job fits.
CANDIDATE_PROFILE = """
Candidate profile template.

Location and commute area: ...
Work preferences: ...
Education: ...
Experience: ...
Technical skills: ...
Languages: ...
Transportation: ...

Not suitable if:
- The role requires a credential the candidate does not have.
- The role requires residency or authorization the candidate does not have.
- The role requires specific experience not present in the profile.

Suitable if:
- The core requirements match the candidate profile.
- Any missing requirements are optional or trainable.
"""
