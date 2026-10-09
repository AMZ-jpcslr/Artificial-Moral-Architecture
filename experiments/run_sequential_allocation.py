"""Offline v0.2.x sequential allocation pilot, no installation needed."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from moral_agent.sequential.runner import main

if __name__ == '__main__':
    main()
