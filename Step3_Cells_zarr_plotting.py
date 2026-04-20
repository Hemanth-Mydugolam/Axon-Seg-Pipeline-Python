import zarr
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")   # non-interactive — prevents blocking in a loop
import matplotlib.pyplot as plt
from pathlib import Path


def _wp(path) -> str:
    """Windows extended-length path prefix to bypass 260-char MAX_PATH limit."""
    return "\\\\?\\" + str(Path(path).resolve())


class ZarrMaskVisualizer:

    def __init__(self, zarr_path, output_path):
        self.zarr_path = Path(zarr_path)
        self.output_path = Path(output_path)

        self.zf = None
        self.nucleus_mask = None
        self.cell_mask = None

    # -----------------------------------------------------
    # Step 1: Load Zarr file
    # -----------------------------------------------------
    def load_zarr(self):
        self.zf = zarr.open(self.zarr_path, mode='r')

        print("Zarr structure:")
        print(self.zf.tree())
        print("\nKeys:", list(self.zf.keys()))

    # -----------------------------------------------------
    # Step 2: Load masks
    # -----------------------------------------------------
    def load_masks(self):
        self.nucleus_mask = self.zf['masks/0'][:]
        self.cell_mask = self.zf['masks/1'][:]

        print(f"Nucleus mask shape : {self.nucleus_mask.shape}, dtype: {self.nucleus_mask.dtype}")
        print(f"Cell mask shape    : {self.cell_mask.shape},    dtype: {self.cell_mask.dtype}")
        print(f"Nucleus unique IDs : {len(np.unique(self.nucleus_mask)):,}")
        print(f"Cell unique IDs    : {len(np.unique(self.cell_mask)):,}")

    # -----------------------------------------------------
    # Step 3: Colorize mask
    # -----------------------------------------------------
    def colorize(self, mask):
        np.random.seed(42)
        num_ids = int(mask.max()) + 1

        color_map = np.random.randint(50, 255, size=(num_ids, 3), dtype=np.uint8)
        color_map[0] = [0, 0, 0]  # background

        return color_map[mask]

    # -----------------------------------------------------
    # Step 4: Plot masks
    # -----------------------------------------------------
    def plot_masks(self):
        fig, axes = plt.subplots(1, 2, figsize=(30, 15))  # larger figure for higher quality

        axes[0].imshow(self.colorize(self.nucleus_mask), interpolation='nearest')
        axes[0].set_title(f"Nucleus Mask — {len(np.unique(self.nucleus_mask))-1:,} cells", fontsize=18)
        axes[0].axis('off')

        axes[1].imshow(self.colorize(self.cell_mask), interpolation='nearest')
        axes[1].set_title(f"Cell Mask — {len(np.unique(self.cell_mask))-1:,} cells", fontsize=18)
        axes[1].axis('off')

        plt.tight_layout()
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(_wp(self.output_path), dpi=600, bbox_inches='tight')  # _wp bypasses MAX_PATH limit
        plt.close()  # do not show

        print(f"✅ Saved {self.output_path.name} (high-quality, plot not displayed)")

    # -----------------------------------------------------
    # Run pipeline
    # -----------------------------------------------------
    def run(self):
        self.load_zarr()
        self.load_masks()
        self.plot_masks()


# -----------------------------------------------------
# Main function
# -----------------------------------------------------
def main():
    # ── Paths ─────────────────────────────────────────
    # Parent folder containing all bundle sub-folders with cells.zarr.zip
    main_path   = Path("C:/Users/hxm220004/Box/Hemanth_Analysis_CAPS/Diana-Tavares/Pipeline_Results/Stage2_IS/")
    # Root output folder — per-bundle sub-folders are created automatically
    output_root = Path("C:/Users/hxm220004/Box/Hemanth_Analysis_CAPS/Diana-Tavares/Pipeline_Results/Stage2_Cells_Zarr_Plot")
    output_root.mkdir(parents=True, exist_ok=True)

    # ── Discover bundles ──────────────────────────────
    bundles = sorted([d for d in main_path.iterdir() if d.is_dir()])
    if not bundles:
        print(f"No bundle folders found under: {main_path}")
        return

    print(f"Found {len(bundles)} bundle(s) to process.\n")

    log_rows = []

    for bundle_dir in bundles:
        bundle_name = bundle_dir.name
        print(f"{'='*60}")
        print(f"Processing bundle: {bundle_name}")

        zarr_path = bundle_dir / "cells.zarr.zip"

        if not zarr_path.exists():
            msg = "SKIPPED – cells.zarr.zip not found"
            print(f"  {msg}\n")
            log_rows.append({
                "Bundle": bundle_name,
                "Zarr Input": str(zarr_path),
                "Nucleus Cells": "N/A",
                "Cell Cells": "N/A",
                "Plot Output": "N/A",
                "Status": msg,
            })
            continue

        out_dir    = output_root / bundle_name
        plot_file  = out_dir / f"{bundle_name}_cells_zarr_plot.png"

        try:
            visualizer = ZarrMaskVisualizer(
                zarr_path=str(zarr_path),
                output_path=plot_file,
            )
            visualizer.run()

            nucleus_cells = len(np.unique(visualizer.nucleus_mask)) - 1
            cell_cells    = len(np.unique(visualizer.cell_mask)) - 1

            print(f"  ✅ Nucleus cells: {nucleus_cells:,} | Cell IDs: {cell_cells:,}\n")
            log_rows.append({
                "Bundle": bundle_name,
                "Zarr Input": str(zarr_path),
                "Nucleus Cells": nucleus_cells,
                "Cell Cells": cell_cells,
                "Plot Output": str(plot_file),
                "Status": "OK",
            })

        except Exception as exc:
            msg = f"ERROR – {exc}"
            print(f"  {msg}\n")
            log_rows.append({
                "Bundle": bundle_name,
                "Zarr Input": str(zarr_path),
                "Nucleus Cells": "ERROR",
                "Cell Cells": "ERROR",
                "Plot Output": str(plot_file),
                "Status": msg,
            })

    # ── Excel log ─────────────────────────────────────
    log_path = output_root / "zarr_plot_log.xlsx"
    pd.DataFrame(log_rows, columns=[
        "Bundle", "Zarr Input", "Nucleus Cells", "Cell Cells", "Plot Output", "Status",
    ]).to_excel(log_path, index=False)
    print(f"Log saved to: {log_path}")


if __name__ == "__main__":
    main()