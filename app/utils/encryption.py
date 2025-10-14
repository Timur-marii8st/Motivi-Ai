from __future__ import annotations
import json
from cryptography.fernet import Fernet
from loguru import logger
from ..config import settings

class TokenEncryption:
    """
    Encrypt/decrypt OAuth tokens using Fernet symmetric encryption.
    """
    def __init__(self, key: bytes | None = None):
        if key:
            self.cipher = Fernet(key)
        else:
            # Generate from ENCRYPTION_KEY in settings (must be 32 url-safe base64 bytes)
            # For production, store in env: ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
            encryption_key = getattr(settings, 'ENCRYPTION_KEY', None)
            if not encryption_key or encryption_key == "INSECURE_DEFAULT_REPLACE_IN_PRODUCTION":
                logger.error("ENCRYPTION_KEY is not set or is insecure. Application cannot start.")
                raise ValueError("A secure ENCRYPTION_KEY must be configured.")
            self.cipher = Fernet(encryption_key.encode())

    def encrypt(self, data: dict) -> str:
        """Encrypt a dictionary to a base64 string."""
        json_str = json.dumps(data)
        encrypted_bytes = self.cipher.encrypt(json_str.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')

    def decrypt(self, encrypted_str: str) -> dict:
        """Decrypt a base64 string back to a dictionary."""
        encrypted_bytes = encrypted_str.encode('utf-8')
        decrypted_bytes = self.cipher.decrypt(encrypted_bytes)
        return json.loads(decrypted_bytes.decode('utf-8'))

# Singleton
token_encryptor = TokenEncryption()