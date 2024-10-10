import re
import unicodedata

def sanitize_dirname(s):
    # Normalize unicode characters
    s = unicodedata.normalize('NFKD', s)

    # Remove non-ASCII characters
    s = s.encode('ASCII', 'ignore').decode('ASCII')

    # Replace spaces with underscores
    s = s.replace(' ', '_')

    # Remove any characters that aren't alphanumeric, underscore, or hyphen
    s = re.sub(r'[^\w\-]', '', s)

    # Remove leading/trailing hyphens and underscores
    s = s.strip('-_')

    # Limit length to 255 characters (common filesystem limit)
    s = s[:255]

    # Ensure the name isn't empty after sanitization
    if not s:
        s = 'untitled'

    return s
