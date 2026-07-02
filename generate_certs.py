import datetime
import os
import ipaddress
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

def generate_self_signed_cert():
    cert_path = "cert.pem"
    key_path = "key.pem"
    
    if os.path.exists(cert_path) and os.path.exists(key_path):
        print("Certificates already exist. Skipping generation.")
        return
        
    print("Generating self-signed SSL certificates for localhost...")
    
    # 1. Generate private key
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # 2. Setup subject and issuer
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"IN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"Maharashtra"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"Mumbai"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Intraday Helper"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"127.0.0.1"),
    ])
    
    # 3. Build certificate
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        now - datetime.timedelta(days=1)
    ).not_valid_after(
        now + datetime.timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName(u"localhost"),
            x509.IPAddress(ipaddress.ip_address(os.environ.get("LOCAL_IP", "127.0.0.1")))
        ]),
        critical=False,
    ).sign(key, hashes.SHA256())
    
    # 4. Write private key
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        
    # 5. Write certificate
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
        
    print("SSL Certificates successfully generated (key.pem & cert.pem).")

if __name__ == "__main__":
    generate_self_signed_cert()
