"""Source checkout entry point, offline and standard-library only."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from moral_agent.affect.runner import main
if __name__ == "__main__":
    main()
