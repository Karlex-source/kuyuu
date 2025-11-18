# Vercel serverless function entry point
import sys
import os

# Add parent directory to path to import app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import Flask app
from app import app

# Vercel Python runtime expects the app to be exported directly
# The app object will be used as the WSGI application

# Export for Vercel
__all__ = ['app']

