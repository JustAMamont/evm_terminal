import os
import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class SecurityManager:
    def __init__(self):
        self._fernet: Fernet | None = None
        self._is_unlocked = False

    def generate_salt(self) -> bytes:
        return os.urandom(16)

    def derive_key(self, password: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    def unlock(self, password: str, salt: bytes) -> bool:
        try:
            key = self.derive_key(password, salt)
            self._fernet = Fernet(key)
            self._is_unlocked = True
            return True
        except Exception:
            self._is_unlocked = False
            return False

    def encrypt(self, data: str) -> str:
        if not self._is_unlocked or not self._fernet:
            raise RuntimeError("DB Locked")
        return self._fernet.encrypt(data.encode()).decode()

    def decrypt(self, token: str) -> str:
        if not self._is_unlocked or not self._fernet:
            raise RuntimeError("DB Locked")
        return self._fernet.decrypt(token.encode()).decode()
    
    def is_active(self) -> bool:
        return self._is_unlocked

