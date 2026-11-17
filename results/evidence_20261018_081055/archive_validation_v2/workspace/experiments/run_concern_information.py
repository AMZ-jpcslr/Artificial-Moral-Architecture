"""Offline entry point for the independent Concern and information-value pilot."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from moral_agent.concern_information.runner import main
if __name__ == '__main__':
    main()
