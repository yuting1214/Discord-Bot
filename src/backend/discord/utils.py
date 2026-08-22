import hashlib
import re
import uuid

# Any UUID version, on purpose. The previous pattern hard-coded version 4
# (`4[0-9a-f]{3}` and variant `[89ab]`), which is a trap on two counts:
# PostgreSQL 18 ships uuidv7() and this template's own image documents it, so
# the day session ids come from the database every resume would be rejected --
# and rejected as *malformed*, which is the one thing they would not be.
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def extract_uuid(input_string: str) -> str:
    """Return the first UUID in ``input_string``, or ``""`` if there is none.

    This answers "is this the right shape", and nothing else. Whether such a
    session exists is the caller's question, and conflating the two told a user
    pasting a valid id for a deleted session that their id was malformed and
    sent them back to /search to copy the same id again.

    Never raises. It is called outside the caller's try block, so a ValueError
    here would surface as the generic failure message rather than as anything
    the user could act on.
    """
    match = _UUID_PATTERN.search(input_string or "")
    if not match:
        return ""
    try:
        # No version= argument: passing one *forces* the version and variant
        # bits rather than checking them, so it would silently hand back a
        # different id than the user typed.
        return str(uuid.UUID(match.group(0)))
    except ValueError:
        return ""


def generate_uuid_key(uuid1: uuid.UUID | str, uuid2: uuid.UUID | str) -> str:
    # Ensure the inputs are UUID objects or valid UUID strings
    if isinstance(uuid1, str):
        uuid1 = uuid.UUID(uuid1)
    if isinstance(uuid2, str):
        uuid2 = uuid.UUID(uuid2)
        
    # Convert UUIDs to strings and concatenate them
    combined_str = str(uuid1) + str(uuid2)
    
    # Create a SHA-256 hash of the combined string
    hash_obj = hashlib.sha256(combined_str.encode('utf-8'))
    
    # Use the hash to generate a new UUID
    combined_uuid = uuid.UUID(hash_obj.hexdigest()[:32])
    
    return str(combined_uuid)
