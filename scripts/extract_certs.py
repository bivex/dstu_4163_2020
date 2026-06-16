#!/usr/bin/env python3
"""Вилучення індивідуальних CA сертифікатів з CACertificates.p7b у .euscp_store.

Це дозволяє надати UAPKI повний список довірених КНЕДП України для офлайн-перевірки.
"""

import subprocess
import os
import re
import sys

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p7b_path = os.path.join(base_dir, "external", "EUSignES6", "signdata", "CACertificates.p7b")
    out_dir = os.path.join(base_dir, ".euscp_store")
    
    import urllib.request
    
    # Спробуємо завантажити найновіший файл сертифікатів з сайту ІІТ
    url = "https://iit.com.ua/download/productfiles/CACertificates.p7b"
    try:
        print(f"Downloading latest CACertificates.p7b from {url}...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        os.makedirs(os.path.dirname(p7b_path), exist_ok=True)
        with open(p7b_path, "wb") as f:
            f.write(data)
        print("Download successful.")
    except Exception as e:
        print(f"Warning: Failed to download latest certs ({e}). Using existing local file.")

    if not os.path.isfile(p7b_path):
        print(f"Error: {p7b_path} not found.", file=sys.stderr)
        sys.exit(1)
        
    os.makedirs(out_dir, exist_ok=True)
    
    print(f"Extracting certificates from {p7b_path} to {out_dir}...")
    
    # Вилучаємо сертифікати через openssl
    res = subprocess.run(
        ["openssl", "pkcs7", "-inform", "DER", "-in", p7b_path, "-print_certs"],
        capture_output=True, text=True, check=True
    )
    
    certs = re.findall(
        r"(subject=.*?\n-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----)",
        res.stdout, re.DOTALL
    )
    
    print(f"Found {len(certs)} certificates in p7b container.")
    
    count = 0
    for idx, cert_pem_data in enumerate(certs):
        m = re.search(r"(-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----)", cert_pem_data, re.DOTALL)
        if not m:
            continue
        pem = m.group(1)
        
        # Отримуємо хеш сертифіката та серійник
        x509_res = subprocess.run(
            ["openssl", "x509", "-noout", "-hash", "-serial"],
            input=pem, capture_output=True, text=True, check=True
        )
        lines = x509_res.stdout.splitlines()
        cert_hash = lines[0].strip() if len(lines) > 0 else f"cert_{idx}"
        serial = lines[1].replace("serial=", "").strip() if len(lines) > 1 else f"{idx}"
        
        # Генеруємо назву файлу, сумісну з назвами EUSign
        filename = f"CA-{cert_hash}-{serial}.cer"
        filepath = os.path.join(out_dir, filename)
        
        # Конвертуємо PEM в DER для UAPKI
        der_res = subprocess.run(
            ["openssl", "x509", "-outform", "DER"],
            input=pem.encode("utf-8"), capture_output=True, check=True
        )
        with open(filepath, "wb") as f:
            f.write(der_res.stdout)
        count += 1
        
    print(f"Successfully extracted {count} certificates.")

if __name__ == "__main__":
    main()
