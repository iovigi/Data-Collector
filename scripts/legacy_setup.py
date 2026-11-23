import os
import sys
import subprocess
import platform

def create_virtual_env():
    """Create a virtual environment if it doesn't exist."""
    if not os.path.exists('venv'):
        print("Creating virtual environment...")
        subprocess.call([sys.executable, '-m', 'venv', 'venv'])
        print("Virtual environment created successfully.")
    else:
        print("Virtual environment already exists.")

def install_dependencies():
    """Install dependencies from requirements.txt."""
    print("Installing dependencies...")
    if platform.system() == 'Windows':
        subprocess.call(['venv\\Scripts\\pip', 'install', '-r', 'requirements.txt'])
    else:
        subprocess.call(['venv/bin/pip', 'install', '-r', 'requirements.txt'])
    print("Dependencies installed successfully.")

def create_env_file():
    """Create .env file if it doesn't exist."""
    if not os.path.exists('.env'):
        print("Creating .env file...")
        with open('.env', 'w') as f:
            f.write("MONGODB_URI=mongodb://localhost:27017/\n")
            f.write("DB_NAME=data_collector\n")
        print(".env file created successfully.")
    else:
        print(".env file already exists.")

def run_app():
    """Run the Flask application."""
    print("Starting the application...")
    if platform.system() == 'Windows':
        subprocess.call(['venv\\Scripts\\python', 'app.py'])
    else:
        subprocess.call(['venv/bin/python', 'app.py'])

if __name__ == '__main__':
    create_virtual_env()
    install_dependencies()
    create_env_file()
    
    print("\nSetup completed successfully!")
    print("\nTo activate the virtual environment:")
    if platform.system() == 'Windows':
        print("    venv\\Scripts\\activate")
    else:
        print("    source venv/bin/activate")
    
    print("\nTo run the application:")
    print("    python app.py")
    
    run_now = input("\nDo you want to run the application now? (y/n): ")
    if run_now.lower() == 'y':
        run_app() 