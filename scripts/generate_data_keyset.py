"""
Utility script to generate a base64-encoded Tink AES256-GCM keyset for
DATA_ENCRYPTION_KEYSET_B64.
"""

import base64
import io

import tink
from tink import aead, cleartext_keyset_handle, JsonKeysetWriter


def main() -> None:
    aead.register()
    keyset_handle = tink.new_keyset_handle(aead.aead_key_templates.AES256_GCM)

    buffer = io.StringIO()
    writer = JsonKeysetWriter(buffer)

    # Key fix: arguments order changed in new Tink versions
    cleartext_keyset_handle.write(writer, keyset_handle)

    encoded = base64.b64encode(buffer.getvalue().encode("utf-8")).decode("ascii")
    print(encoded)
    print("\nAdd the above value to your .env as DATA_ENCRYPTION_KEYSET_B64")


if __name__ == "__main__":
    main()
