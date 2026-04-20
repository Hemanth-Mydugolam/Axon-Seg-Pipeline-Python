import json
import numpy as np
import logging
import pandas as pd
import tifffile
from pathlib import Path
from shapely.geometry import shape
from rasterio.features import rasterize
from PIL import Image


class GeoJSONMaskGenerator:

    def __init__(
        self,
        ome_tiff_path,
        geojson_path,
        output_mask_path,
        output_npy_path,
        mask_scale=255,
    ):
        self.ome_tiff_path = Path(ome_tiff_path)
        self.geojson_path = Path(geojson_path)
        self.output_mask_path = Path(output_mask_path)
        self.output_npy_path = Path(output_npy_path)
        self.mask_scale = mask_scale

        self.img_height = None
        self.img_width = None
        self.geometries = []
        self.mask = None

        self._setup_logger()

    # -----------------------------------------------------
    # Logger setup (console only — avoids Box Drive mkdir issues)
    # -----------------------------------------------------
    def _setup_logger(self):
        # Use a unique logger per instance so handlers don't accumulate across bundles
        self.logger = logging.getLogger(f"GeoJSONMaskGenerator.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)

    # -----------------------------------------------------
    # Read OME-TIFF
    # -----------------------------------------------------
    def read_image_dimensions(self):
        with tifffile.TiffFile(self.ome_tiff_path) as tif:
            shape = tif.series[0].shape  # e.g. (Z, Y, X) or (T, C, Z, Y, X)

        self.img_height = shape[-2]
        self.img_width = shape[-1]

        self.logger.info(f"Image size: {self.img_width} x {self.img_height} (Width x Height)")

    # -----------------------------------------------------
    # Load GeoJSON
    # -----------------------------------------------------
    def load_geojson(self):
        with open(self.geojson_path) as f:
            geojson_data = json.load(f)

        self.geometries = [
            shape(feat["geometry"])
            for feat in geojson_data["features"]
            if not shape(feat["geometry"]).is_empty
        ]

        self.logger.info(f"Number of geometries to rasterize: {len(self.geometries)}")

    # -----------------------------------------------------
    # Rasterize mask
    # -----------------------------------------------------
    def rasterize_mask(self):
        self.mask = rasterize(
            [(geom, 1) for geom in self.geometries],
            out_shape=(self.img_height, self.img_width),
            fill=0,
            dtype=np.uint8
        )

        self.mask = self.mask * self.mask_scale

        self.logger.info("Mask rasterization complete.")

    # -----------------------------------------------------
    # Save outputs
    # -----------------------------------------------------
    @staticmethod
    def _wp(path: Path) -> str:
        """Return a Windows extended-length path string (\\?\...) to bypass the
        260-character MAX_PATH limit, which is easily exceeded when bundle names
        and output paths are both long."""
        return "\\\\?\\" + str(path.resolve())

    def save_outputs(self):
        self.output_mask_path.parent.mkdir(parents=True, exist_ok=True)

        # Save NPY
        np.save(self._wp(self.output_npy_path), self.mask)
        self.logger.info(f"Mask NPY saved to {self.output_npy_path}")

        # Save PNG
        mask_img = Image.fromarray(self.mask)
        mask_img.save(self._wp(self.output_mask_path))
        self.logger.info(f"Mask PNG saved to {self.output_mask_path}")

    # -----------------------------------------------------
    # Run pipeline
    # -----------------------------------------------------
    def run(self):
        self.read_image_dimensions()
        self.load_geojson()
        self.rasterize_mask()
        self.save_outputs()
        self.logger.info("✅ Mask generation completed successfully.")


# -----------------------------------------------------
# Main function
# -----------------------------------------------------
def main():
    # ── Paths (mirror Step2a) ─────────────────────────
    # Parent directory containing all bundle sub-folders (same as Step2a)
    main_path = Path("C:/Users/hxm220004/Box/Hemanth_Analysis_CAPS/Diana-Tavares/Pipeline_Results/Stage1_IS/Batch1/")
    # Root output directory where Step2a wrote GeoJSONs (masks go in the same per-bundle folders)
    Output_path = Path("C:/Users/hxm220004/Box/Hemanth_Analysis_CAPS/Diana-Tavares/Pipeline_Results/Stage1_Cell_Boundaries_2_GeoJSON/Batch1")

    # ── Discover bundles ──────────────────────────────
    bundles = sorted([d for d in main_path.iterdir() if d.is_dir()])
    if not bundles:
        print(f"No bundle folders found under: {main_path}")
        return

    print(f"Found {len(bundles)} bundle(s) to process.\n")

    # ── Log accumulator ───────────────────────────────
    log_rows = []

    # ── Process each bundle ───────────────────────────
    for bundle_dir in bundles:
        bundle_name = bundle_dir.name
        print(f"{'='*60}")
        print(f"Processing bundle: {bundle_name}")

        # Input: morphology tiff from original bundle folder
        tiff_candidates = list((bundle_dir / "morphology_focus").glob("*.ome.tif"))

        # Input: GeoJSON produced by Step2a
        geojson_path = Output_path / bundle_name / "cell_boundaries_pixel_scaled.geojson"

        # Output paths (defined early so skipped rows can still log them)
        out_bundle_dir = Output_path / bundle_name
        output_mask_png = out_bundle_dir / f"{bundle_name}_mask.png"
        output_mask_npy = out_bundle_dir / f"{bundle_name}_mask.npy"

        # ── Skip if required files are missing ────────
        if not tiff_candidates:
            msg = "SKIPPED – no *.ome.tif found in morphology_focus/"
            print(f"  {msg}\n")
            log_rows.append({
                "Bundle": bundle_name,
                "GeoJSON Input": str(geojson_path),
                "Cells in GeoJSON": "N/A",
                "Mask NPY": str(output_mask_npy),
                "Mask PNG": str(output_mask_png),
                "Status": msg,
            })
            continue

        if not geojson_path.exists():
            msg = "SKIPPED – GeoJSON not found (run Step2a first)"
            print(f"  {msg}: {geojson_path}\n")
            log_rows.append({
                "Bundle": bundle_name,
                "GeoJSON Input": str(geojson_path),
                "Cells in GeoJSON": "N/A",
                "Mask NPY": str(output_mask_npy),
                "Mask PNG": str(output_mask_png),
                "Status": msg,
            })
            continue

        morphology_tiff_path = tiff_candidates[0]

        # Ensure output folder exists before saving masks
        out_bundle_dir.mkdir(parents=True, exist_ok=True)

        # Count features in GeoJSON for the log
        with open(geojson_path) as f:
            geojson_feature_count = len(json.load(f).get("features", []))

        # ── Run mask generator ────────────────────────
        try:
            generator = GeoJSONMaskGenerator(
                ome_tiff_path=morphology_tiff_path,
                geojson_path=geojson_path,
                output_mask_path=output_mask_png,
                output_npy_path=output_mask_npy,
                mask_scale=255,
            )
            generator.run()
            print(f"  ✅ Mask saved: {output_mask_npy.name}, {output_mask_png.name}\n")
            log_rows.append({
                "Bundle": bundle_name,
                "GeoJSON Input": str(geojson_path),
                "Cells in GeoJSON": geojson_feature_count,
                "Mask NPY": str(output_mask_npy),
                "Mask PNG": str(output_mask_png),
                "Status": "OK",
            })
        except Exception as exc:
            msg = f"ERROR – {exc}"
            print(f"  {msg}\n")
            log_rows.append({
                "Bundle": bundle_name,
                "GeoJSON Input": str(geojson_path),
                "Cells in GeoJSON": geojson_feature_count,
                "Mask NPY": str(output_mask_npy),
                "Mask PNG": str(output_mask_png),
                "Status": msg,
            })

    # ── Write Excel log ───────────────────────────────
    log_path = Output_path / "mask_generation_log.xlsx"
    log_df = pd.DataFrame(log_rows, columns=[
        "Bundle",
        "GeoJSON Input",
        "Cells in GeoJSON",
        "Mask NPY",
        "Mask PNG",
        "Status",
    ])
    log_df.to_excel(log_path, index=False)
    print(f"Log saved to: {log_path}")


if __name__ == "__main__":
    main()