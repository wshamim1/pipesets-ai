"""Write backend/release_notes.json from git, for builds without a .git directory (Docker image, desktop
app). Run it before the build:  python backend/scripts/write_release_notes.py [--limit 20]"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import release_notes  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=release_notes.MAX_COMMITS)
    commits = release_notes.from_git(parser.parse_args().limit)
    if commits is None:
        sys.exit("No git checkout here — run this from the repository.")
    with open(release_notes.BUNDLED, "w", encoding="utf-8") as fh:
        json.dump({"commits": [{k: c[k] for k in ("hash", "short", "date", "author", "subject", "body", "files")}
                               for c in commits]}, fh, indent=1)
    print(f"Wrote {len(commits)} commit(s) to {release_notes.BUNDLED}")


if __name__ == "__main__":
    main()
