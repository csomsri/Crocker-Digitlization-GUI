"""3D view: main magnet height by default, or coil-only UMAP with --third-axis umap."""
from umap_common import run


if __name__ == '__main__':
    raise SystemExit(run(three_dimensional=True))
