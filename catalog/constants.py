LANGUAGES = [
    ("en", "English"),
    ("hi", "Hindi"),
    ("te", "Telugu"),
    ("ml", "Malayalam"),
    ("mr", "Marathi"),
    ("kn", "Kannada"),
    ("ta", "Tamil"),
    ("bn", "Bengali"),
]

LANGUAGE_CODES = [c for c, _ in LANGUAGES]

# For this stage, you requested using one standard URL for all videos.
# Replace this with your real YouTube embed URL later (or store per-language URLs in admin).
DEFAULT_VIDEO_URL = "https://www.youtube.com/embed/VIDEO_ID_PLACEHOLDER"

# Standard thumbnail for all videos (replace later)
DEFAULT_THUMBNAIL_URL = "https://via.placeholder.com/1280x720.png?text=Video"
