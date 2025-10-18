from dotenv import load_dotenv
import os
import bcrypt

# Load environment variables
load_dotenv('C:/Users/Laptop-bey/Desktop/kids/.env')

# Check if the variable is loaded
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH")
print(f"ADMIN_PASSWORD_HASH from .env: {ADMIN_PASSWORD_HASH}")

# Test the password
password = "admin"
if ADMIN_PASSWORD_HASH:
    try:
        # Ensure it's in bytes
        stored_hash = ADMIN_PASSWORD_HASH.encode('utf-8')
        plain_bytes = password.encode('utf-8')
        
        result = bcrypt.checkpw(plain_bytes, stored_hash)
        print(f"Password verification result for '{password}': {result}")
    except Exception as e:
        print(f"Error during verification: {e}")
else:
    print("ADMIN_PASSWORD_HASH is not loaded")