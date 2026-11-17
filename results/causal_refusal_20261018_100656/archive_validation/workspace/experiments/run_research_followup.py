"""Run the additive 2026-10-18 study directly from checkout, without installation."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT))
from experiments.research_20261018.runner import main

if __name__ == '__main__':
    main()
