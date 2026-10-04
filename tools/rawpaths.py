"""Where the raw data folders are: ../05_Raw_Data_Sources beside the repo, or one level further up in a git worktree
(../_worktrees/<branch>), so a tool run from a worktree writes to the same place as one run from the main checkout."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent if ROOT.parent.name == "_worktrees" else ROOT.parent
RAW_SOURCES = PROJECT / "05_Raw_Data_Sources"
SHAH_ALAM_RAW = RAW_SOURCES / "shah_alam"
