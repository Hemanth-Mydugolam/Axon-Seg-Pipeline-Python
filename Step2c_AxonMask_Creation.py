import json
import logging
import numpy as np
import pandas as pd
import tifffile
from pathlib import Path
from shapely.geometry import shape
from rasterio.features import rasterize
from scipy.ndimage import label as scipy_label
from skimage.measure import label as skimage_label
from PIL import Image
import matplotlib
matplotlib.use("Agg")   # non-interactive backend — prevents plt.show() from blocking
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors


def _wp(path) -> str:
    """Return a Windows extended-length path string (\\\\?\\...) to bypass
    the 260-character MAX_PATH limit that is easily exceeded with long
    bundle names and deep output directories."""
    return "\\\\?\\" + str(Path(path).resolve())

# -----------------------------
# Logging configuration
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# -----------------------------
# Mask processing class
# -----------------------------
class MaskProcessor:
    def __init__(self, ome_tiff_path, axon_geojson_path, output_dir):
        self.ome_tiff_path = ome_tiff_path
        self.axon_geojson_path = axon_geojson_path
        self.output_dir = output_dir
        
        self.img_height = None
        self.img_width = None
        self.geometries = []
        self.new_mask = None
        self.global_id = 0

    def load_image(self):
        logger.info(f"Loading OME-TIFF image from: {self.ome_tiff_path}")
        with tifffile.TiffFile(self.ome_tiff_path) as tif:
            shape = tif.series[0].shape  # e.g. (C, Z, Y, X)
        self.img_height = shape[-2]
        self.img_width = shape[-1]
        logger.info(f"Image size: {self.img_width} x {self.img_height} (Width x Height)")

    def load_geojson(self):
        logger.info(f"Loading GeoJSON from: {self.axon_geojson_path}")
        with open(self.axon_geojson_path) as f:
            geojson = json.load(f)
        self.geometries = [
            shape(feat["geometry"])
            for feat in geojson["features"]
            if not shape(feat["geometry"]).is_empty
        ]
        logger.info(f"Total polygons loaded from GeoJSON: {len(self.geometries)}")

    def rasterize_polygons(self):
        logger.info("Rasterizing polygons and assigning unique IDs...")
        self.new_mask = np.zeros((self.img_height, self.img_width), dtype=np.uint32)
        connectivity_structure = np.ones((3, 3), dtype=int)  # 8-connected

        for poly_idx, geom in enumerate(self.geometries, start=1):
            poly_binary = rasterize(
                [(geom, 1)],
                out_shape=(self.img_height, self.img_width),
                fill=0,
                dtype=np.uint8
            )

            if poly_binary.sum() == 0:
                logger.warning(f"Polygon {poly_idx}: empty after rasterization — skipped")
                continue

            labeled_components, num_components = scipy_label(poly_binary, structure=connectivity_structure)
            logger.info(f"Polygon {poly_idx}: {poly_binary.sum()} pixels → {num_components} connected component(s)")

            for comp_id in range(1, num_components + 1):
                self.global_id += 1
                component_pixels = (labeled_components == comp_id)
                self.new_mask = np.where(
                    component_pixels & (self.new_mask == 0),
                    self.global_id,
                    self.new_mask
                )

        logger.info(f"✅ Total polygons processed: {len(self.geometries)}")
        logger.info(f"✅ Total connected components (unique IDs assigned): {self.global_id}")
        logger.info(f"✅ Unique values in new_mask (incl. background 0): {len(np.unique(self.new_mask))}")

    def save_mask(self, path, binary=False):
        if binary:
            vis_mask = ((self.new_mask > 0).astype(np.uint8)) * 255
            Image.fromarray(vis_mask).save(path)
        else:
            np.save(path, self.new_mask)
        logger.info(f"✅ Saved mask: {path}")

    def subtract_existing_mask(self, existing_mask_path):
        logger.info(f"Loading existing mask: {existing_mask_path}")
        mask = np.load(existing_mask_path)
        existing_mask = (mask > 0).astype(np.uint8)

        if existing_mask.shape != self.new_mask.shape:
            raise ValueError(f"Shape mismatch! new_mask: {self.new_mask.shape}, existing_mask: {existing_mask.shape}")

        difference_mask = np.where(
            (self.new_mask > 0) & (~existing_mask),
            self.new_mask,
            0
        ).astype(np.uint32)

        self.new_mask = difference_mask
        unique_ids_diff = np.unique(difference_mask)
        logger.info(f"✅ Unique component IDs after subtraction: {len(unique_ids_diff) - 1} (excluding background)")

    def relabel_components(self):
        logger.info("Performing global connected component relabeling...")
        diff_binary = (self.new_mask > 0).astype(np.uint8)
        relabeled_mask, num_components = skimage_label(diff_binary, connectivity=2, return_num=True)
        self.new_mask = relabeled_mask.astype(np.uint32)
        logger.info(f"Total connected components after subtraction split: {num_components}")
        return num_components

    def plot_components(self, mask=None, path="./Output/components_colored.png"):
        mask = mask if mask is not None else self.new_mask
        num_ids = mask.max() + 1
        np.random.seed(42)
        random_colors = np.random.rand(num_ids, 3)
        random_colors[0] = [0, 0, 0]  # background black
        cmap = mcolors.ListedColormap(random_colors)

        plt.figure(figsize=(20, 20))
        plt.imshow(mask, cmap=cmap, interpolation='nearest')
        plt.axis('off')
        plt.title(f"Connected Components — {num_ids - 1} unique IDs")
        plt.savefig(path, dpi=150, bbox_inches='tight')
        plt.close()
        logger.info(f"✅ Saved colored plot: {path}")

    def plot_rgb_components(self, mask=None, path="./Output/components_colored_rgb.png"):
        mask = mask if mask is not None else self.new_mask
        num_ids = mask.max() + 1
        np.random.seed(42)
        color_map = np.random.randint(50, 255, size=(num_ids, 3), dtype=np.uint8)
        color_map[0] = [0, 0, 0]  # background black
        rgb_image = color_map[mask]
        Image.fromarray(rgb_image).save(path)
        logger.info(f"✅ Saved RGB colored mask: {path}")

    def filter_by_min_pixels(self, min_pixels=1000, output_prefix="./Output/FilteredMask"):
        """
        Keep only components with at least `min_pixels` pixels, save filtered mask and plots.
        """
        mask = self.new_mask
        unique_ids, counts = np.unique(mask, return_counts=True)

        # Exclude background
        non_bg_mask = unique_ids != 0
        component_ids = unique_ids[non_bg_mask]
        component_counts = counts[non_bg_mask]

        # Filter components by minimum pixel count
        valid_ids = component_ids[component_counts >= min_pixels]

        if len(valid_ids) == 0:
            logger.warning(f"No components meet the minimum pixel threshold of {min_pixels}")
            self.new_mask = np.zeros_like(mask, dtype=np.uint32)
            return

        # Build new mask keeping only valid components
        filtered_mask = np.zeros_like(mask, dtype=np.uint32)
        for cid in valid_ids:
            filtered_mask[mask == cid] = cid

        self.new_mask = filtered_mask
        logger.info(f"✅ Filtered mask: {len(valid_ids)} components remain with ≥{min_pixels} pixels")

        # -----------------------------
        # Save filtered mask as .npy
        # -----------------------------
        np.save(f"{output_prefix}.npy", filtered_mask)
        logger.info(f"✅ Saved filtered mask: {output_prefix}.npy")

        # -----------------------------
        # Save binary visualization
        # -----------------------------
        vis_mask = ((filtered_mask > 0).astype(np.uint8)) * 255
        Image.fromarray(vis_mask).save(f"{output_prefix}_binary.png")
        logger.info(f"✅ Saved filtered mask binary image: {output_prefix}_binary.png")

        # -----------------------------
        # Save matplotlib plot
        # -----------------------------
        num_ids = filtered_mask.max() + 1
        np.random.seed(42)
        random_colors = np.random.rand(num_ids, 3)
        random_colors[0] = [0, 0, 0]  # background black
        cmap = mcolors.ListedColormap(random_colors)

        plt.figure(figsize=(20, 20))
        plt.imshow(filtered_mask, cmap=cmap, interpolation='nearest')
        plt.axis('off')
        plt.title(f"Filtered Components ≥ {min_pixels} pixels")
        plt.savefig(f"{output_prefix}_colored.png", dpi=150, bbox_inches='tight')
        plt.close()
        logger.info(f"✅ Saved matplotlib colored plot: {output_prefix}_colored.png")

        # -----------------------------
        # Save RGB image
        # -----------------------------
        color_map = np.random.randint(50, 255, size=(num_ids, 3), dtype=np.uint8)
        color_map[0] = [0, 0, 0]  # background black
        rgb_image = color_map[filtered_mask]
        Image.fromarray(rgb_image).save(f"{output_prefix}_colored_rgb.png")
        logger.info(f"✅ Saved RGB colored mask: {output_prefix}_colored_rgb.png")


# -----------------------------
# Main — multi-bundle loop
# -----------------------------
def main():
    # ── Paths ──────────────────────────────────────────────────────────────────
    # Original Xenium bundles (OME-TIFF source)
    main_path      = Path("C:/Users/hxm220004/Box/Hemanth_Analysis_CAPS/Diana-Tavares/Pipeline_Results/Stage1_IS/Batch1/")
    # Axon GeoJSON files (one per bundle sub-folder, filename contains "axon"/"Axon")
    axon_root      = Path("C:/Users/hxm220004/Box/Hemanth_Analysis_CAPS/Diana-Tavares/Pipeline_Results/Axon_Boundary_GeoJSON/Batch1")
    # Step2b outputs: cell-boundary mask per bundle (used for subtraction)
    # Axon mask outputs also go here (same folder as cell boundary masks)
    cell_mask_root = Path("C:/Users/hxm220004/Box/Hemanth_Analysis_CAPS/Diana-Tavares/Pipeline_Results/Stage1_Cell_Boundaries_2_GeoJSON/Batch1")

    # ── Discover bundles ───────────────────────────────────────────────────────
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

        # ── Resolve input paths ────────────────────────────────────────────────
        tiff_candidates = list((bundle_dir / "morphology_focus").glob("*.ome.tif"))

        # Axon GeoJSON: single file whose name contains "axon" or "Axon"
        axon_geojson_candidates = (
            list((axon_root / bundle_name).glob("*[Aa]xon*.geojson"))
            if (axon_root / bundle_name).exists() else []
        )
        axon_geojson_path = axon_geojson_candidates[0] if axon_geojson_candidates else None

        # Cell-boundary mask from Step2b + output directory
        existing_mask_npy = cell_mask_root / bundle_name / f"{bundle_name}_mask.npy"
        out_dir           = cell_mask_root / bundle_name

        # ── Skip checks ────────────────────────────────────────────────────────
        # Note: we do NOT check existing_mask_npy.exists() — Box Drive returns
        # False for cloud-only files even when they are readable. A missing mask
        # will surface as a clear FileNotFoundError inside subtract_existing_mask().
        skip_reason = None
        if not tiff_candidates:
            skip_reason = "SKIPPED – no *.ome.tif in morphology_focus/"
        elif axon_geojson_path is None:
            skip_reason = f"SKIPPED – no *axon*.geojson found in {axon_root / bundle_name}"

        if skip_reason:
            print(f"  {skip_reason}\n")
            log_rows.append({
                "Bundle": bundle_name,
                "GeoJSON Input": str(axon_geojson_path),
                "Cell Boundary Mask (Step2b)": str(existing_mask_npy),
                "Polygons in GeoJSON": "N/A",
                "Components after subtraction": "N/A",
                "Filtered components (≥1000px)": "N/A",
                "Status": skip_reason,
            })
            continue

        morphology_tiff = tiff_candidates[0]
        out_dir.mkdir(parents=True, exist_ok=True)

        # ── Per-bundle output paths (all use _wp for MAX_PATH safety) ──────────
        raw_mask_npy    = _wp(out_dir / f"{bundle_name}_axon_raw_mask.npy")
        raw_mask_png    = _wp(out_dir / f"{bundle_name}_axon_raw_mask_vis.png")
        comp_colored    = _wp(out_dir / f"{bundle_name}_axon_components_colored.png")
        comp_rgb        = _wp(out_dir / f"{bundle_name}_axon_components_rgb.png")
        filtered_prefix = _wp(out_dir / f"{bundle_name}_FilteredAxon")

        try:
            processor = MaskProcessor(
                ome_tiff_path=str(morphology_tiff),
                axon_geojson_path=str(axon_geojson_path),
                output_dir=str(out_dir),
            )

            processor.load_image()
            processor.load_geojson()
            num_polygons = len(processor.geometries)

            processor.rasterize_polygons()
            processor.save_mask(path=raw_mask_npy)
            processor.save_mask(path=raw_mask_png, binary=True)

            processor.subtract_existing_mask(existing_mask_path=_wp(existing_mask_npy))
            num_components = processor.relabel_components()

            processor.plot_components(path=comp_colored)
            processor.plot_rgb_components(path=comp_rgb)
            processor.filter_by_min_pixels(min_pixels=1000, output_prefix=filtered_prefix)

            unique_filtered = len(np.unique(processor.new_mask)) - 1  # exclude background

            print(f"  ✅ Done: {num_components} components → {unique_filtered} after filter\n")
            log_rows.append({
                "Bundle": bundle_name,
                "GeoJSON Input": str(axon_geojson_path),
                "Cell Boundary Mask (Step2b)": str(existing_mask_npy),
                "Polygons in GeoJSON": num_polygons,
                "Components after subtraction": num_components,
                "Filtered components (≥1000px)": unique_filtered,
                "Status": "OK",
            })

        except Exception as exc:
            msg = f"ERROR – {exc}"
            print(f"  {msg}\n")
            log_rows.append({
                "Bundle": bundle_name,
                "GeoJSON Input": str(axon_geojson_path),
                "Cell Boundary Mask (Step2b)": str(existing_mask_npy),
                "Polygons in GeoJSON": "ERROR",
                "Components after subtraction": "ERROR",
                "Filtered components (≥1000px)": "ERROR",
                "Status": msg,
            })

    # ── Excel log ──────────────────────────────────────────────────────────────
    log_path = cell_mask_root / "axon_mask_log.xlsx"
    pd.DataFrame(log_rows, columns=[
        "Bundle",
        "GeoJSON Input",
        "Cell Boundary Mask (Step2b)",
        "Polygons in GeoJSON",
        "Components after subtraction",
        "Filtered components (≥1000px)",
        "Status",
    ]).to_excel(log_path, index=False)
    print(f"Log saved to: {log_path}")


if __name__ == "__main__":
    main()