import hashlib
import re
import uuid


def extract_uuid(input_string: str) -> str:
    """
    Extracts a UUID (version 4) from the given string.
    
    Args:
    input_string (str): The string that contains a UUID.
    
    Returns:
    str: The extracted UUID if found, otherwise an empty string.
    
    Raises:
    ValueError: If the extracted string is not a valid UUID4.
    """
    # UUID4 pattern
    uuid4_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'
    
    # Find all matches
    matches = re.findall(uuid4_pattern, input_string, re.IGNORECASE)
    
    if matches:
        # Get the first match
        potential_uuid = matches[0]
        
        # Validate that it's a proper UUID4
        try:
            uuid_obj = uuid.UUID(potential_uuid, version=4)
            return str(uuid_obj)
        except ValueError:
            raise ValueError(f"The extracted string '{potential_uuid}' is not a valid UUID4.")
    
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
