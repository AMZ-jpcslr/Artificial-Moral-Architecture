"""Offline entry point; only local simulation and new output directories."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.error_bounds_20261018.runner import main
if __name__=='__main__':main()
