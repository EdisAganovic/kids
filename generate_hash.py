import bcrypt

def generate_hash(password):
    """Generate bcrypt hash for a given password"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

if __name__ == "__main__":
    # Generate a hash for the default password 'admin'
    password = "admin"
    hashed_password = generate_hash(password)
    print(f"Generated hash for password '{password}': {hashed_password}")