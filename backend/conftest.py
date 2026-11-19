import sys
import os

# Ensure project root is on sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Prevent __pycache__ creation on filesystems that don't support it
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'