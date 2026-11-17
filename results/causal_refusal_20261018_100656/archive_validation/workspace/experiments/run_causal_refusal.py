"""Offline entry point for isolated, one-factor refusal experiments."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from experiments.causal_refusal_20261018.runner import main

if __name__=='__main__':main()
