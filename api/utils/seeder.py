import os
import bcrypt
from api.database import get_db

def seed_users():
    """Seed users from environment variables"""
    db = get_db()
    
    # Get admin credentials from environment variables
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@example.com')
    
    # Check if admin user already exists
    if not db.users.find_one({'username': admin_username}):
        # Hash the password
        hashed = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt())
        
        # Create admin user
        admin_user = {
            'username': admin_username,
            'password': hashed.decode('utf-8'),
            'email': admin_email,
            'role': 'admin'
        }
        db.users.insert_one(admin_user)
        print(f"Admin user '{admin_username}' created successfully")
    else:
        print(f"Admin user '{admin_username}' already exists") 