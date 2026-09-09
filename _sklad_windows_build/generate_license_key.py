"""Run once on a trusted machine. Never distribute the private key."""
import argparse
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate(private_path, public_path):
    private_path, public_path = Path(private_path), Path(public_path)
    if private_path.exists():
        key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    else:
        if public_path.exists():
            raise RuntimeError('Public key exists but private key is missing. Restore the original private key.')
        key = Ed25519PrivateKey.generate()
        private_path.parent.mkdir(parents=True, exist_ok=True)
        with private_path.open('xb') as output:
            output.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
        private_path.chmod(0o600)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    if public_path.exists() and public_path.read_bytes() != public:
        raise RuntimeError('Existing public key does not match; refusing to overwrite.')
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_bytes(public)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('private_path')
    parser.add_argument('public_path')
    args = parser.parse_args()
    generate(args.private_path, args.public_path)
    print('License keypair ready. Only the public key may be bundled.')
