import pandas as pd
import geojson
from shapely.geometry import Polygon, MultiPolygon
import tifffile
import xml.etree.ElementTree as ET
from pathlib import Path


class XeniumGeoJSONConverter:

    def __init__(
        self,
        morphology_tiff_path,
        cell_boundaries_path,
        cell_geojson_out
    ):
        self.morphology_tiff_path = morphology_tiff_path
        self.cell_boundaries_path = cell_boundaries_path
        self.cell_boundaries_geojson = cell_geojson_out

        # Internal variables
        self.pixel_um_x = None
        self.pixel_um_y = None
        self.df = None
        self.features = []
        self.num_cells = 0

    # -----------------------------------------------------
    # 1. Extract pixel scaling
    # -----------------------------------------------------
    def get_pixel_sizes(self):
        with tifffile.TiffFile(self.morphology_tiff_path) as tif:
            ome_xml = tif.ome_metadata

        root = ET.fromstring(ome_xml)
        ns = {"ome": "http://www.openmicroscopy.org/Schemas/OME/2016-06"}
        pixels = root.find(".//ome:Pixels", ns)

        self.pixel_um_x = float(pixels.get("PhysicalSizeX"))
        self.pixel_um_y = float(pixels.get("PhysicalSizeY"))

        print("Microns per pixel:", self.pixel_um_x, self.pixel_um_y)

    # -----------------------------------------------------
    # 2. Load cell boundaries
    # -----------------------------------------------------
    def load_data(self):
        self.df = pd.read_csv(self.cell_boundaries_path)
        self.num_cells = self.df["cell_id"].nunique()

    # -----------------------------------------------------
    # 3. Convert to pixel coordinates
    # -----------------------------------------------------
    def convert_to_pixels(self):
        x_col = "vertex_x"
        y_col = "vertex_y"

        self.df["x_px"] = self.df[x_col] / self.pixel_um_x
        self.df["y_px"] = self.df[y_col] / self.pixel_um_y

    # -----------------------------------------------------
    # 4. Build polygons
    # -----------------------------------------------------
    def build_polygons(self):
        self.features = []

        for cell_id, group in self.df.groupby("cell_id"):
            coords = list(zip(group["x_px"].tolist(), group["y_px"].tolist()))

            poly = Polygon(coords)
            if not poly.is_valid:
                poly = poly.buffer(0)

            if isinstance(poly, Polygon):
                geometry = geojson.Polygon([list(poly.exterior.coords)])

            elif isinstance(poly, MultiPolygon):
                geometry = geojson.MultiPolygon([
                    [list(p.exterior.coords)] for p in poly.geoms
                ])

            feature = geojson.Feature(
                id=str(cell_id),
                geometry=geometry,
                properties={"cell_id": cell_id}
            )

            self.features.append(feature)

    # -----------------------------------------------------
    # 5. Save GeoJSON
    # -----------------------------------------------------
    def save_geojson(self):
        fc = geojson.FeatureCollection(self.features)

        with open(self.cell_boundaries_geojson, "w") as f:
            geojson.dump(fc, f)

        print("Saved scaled cell boundaries!")
        return fc

    # -----------------------------------------------------
    # 6. Validation
    # -----------------------------------------------------
    def validate_counts(self, fc):
        if "features" in fc:
            count_features = len(fc["features"])
        else:
            raise ValueError("Invalid GeoJSON: 'features' key not found")

        print("---- Cross Validation ----")
        print("Cells in CSV:", self.num_cells)
        print("Features in GeoJSON:", count_features)

        if self.num_cells == count_features:
            print("✅ All cells successfully converted!")
        else:
            print("⚠️ Mismatch detected! Some cells may be missing after conversion.")

    # -----------------------------------------------------
    # Run pipeline
    # -----------------------------------------------------
    def run(self):
        self.get_pixel_sizes()
        self.load_data()
        self.convert_to_pixels()
        self.build_polygons()
        fc = self.save_geojson()
        self.validate_counts(fc)


# -----------------------------------------------------
# Usage
# -----------------------------------------------------
def main():
    # ── Paths ────────────────────────────────────────
    # Parent directory containing all bundle sub-folders
    main_path = Path("C:/Users/hxm220004/Box/Hemanth_Analysis_CAPS/Diana-Tavares/Pipeline_Results/Stage1_IS/Batch1/")
    # Root output directory (log file is saved here too)
    Output_path = Path("C:/Users/hxm220004/Box/Hemanth_Analysis_CAPS/Diana-Tavares/Pipeline_Results/Stage1_Cell_Boundaries_2_GeoJSON/Batch1")
    Output_path.mkdir(parents=True, exist_ok=True)

    # ── Discover bundles ─────────────────────────────
    bundles = sorted([d for d in main_path.iterdir() if d.is_dir()])
    if not bundles:
        print(f"No bundle folders found under: {main_path}")
        return

    print(f"Found {len(bundles)} bundle(s) to process.\n")

    # ── Log accumulator ──────────────────────────────
    log_rows = []

    # ── Process each bundle ──────────────────────────
    for bundle_dir in bundles:
        bundle_name = bundle_dir.name
        print(f"{'='*60}")
        print(f"Processing bundle: {bundle_name}")

        # Locate the morphology tiff (glob so filename variations are handled)
        tiff_candidates = list((bundle_dir / "morphology_focus").glob("*.ome.tif"))
        cell_boundaries_path = bundle_dir / "cell_boundaries.csv.gz"

        # ── Skip if required files are missing ───────
        if not tiff_candidates:
            msg = "SKIPPED – no *.ome.tif found in morphology_focus/"
            print(f"  {msg}\n")
            log_rows.append({
                "Bundle": bundle_name,
                "cell_boundaries.csv.gz": str(cell_boundaries_path),
                "Cells in CSV": "N/A",
                "GeoJSON Output": "N/A",
                "Features in GeoJSON": "N/A",
                "Status": msg,
            })
            continue

        if not cell_boundaries_path.exists():
            msg = "SKIPPED – cell_boundaries.csv.gz not found"
            print(f"  {msg}\n")
            log_rows.append({
                "Bundle": bundle_name,
                "cell_boundaries.csv.gz": str(cell_boundaries_path),
                "Cells in CSV": "N/A",
                "GeoJSON Output": "N/A",
                "Features in GeoJSON": "N/A",
                "Status": msg,
            })
            continue

        morphology_tiff_path = tiff_candidates[0]

        # Per-bundle output folder (same name as bundle)
        out_xenium_bundle = Output_path / bundle_name
        out_xenium_bundle.mkdir(parents=True, exist_ok=True)
        cell_geojson_out = out_xenium_bundle / "cell_boundaries_pixel_scaled.geojson"

        # ── Run converter ─────────────────────────────
        try:
            converter = XeniumGeoJSONConverter(
                morphology_tiff_path=morphology_tiff_path,
                cell_boundaries_path=cell_boundaries_path,
                cell_geojson_out=cell_geojson_out,
            )
            converter.run()
            match = converter.num_cells == len(converter.features)
            status = "OK" if match else "MISMATCH"
            log_rows.append({
                "Bundle": bundle_name,
                "cell_boundaries.csv.gz": str(cell_boundaries_path),
                "Cells in CSV": converter.num_cells,
                "GeoJSON Output": str(cell_geojson_out),
                "Features in GeoJSON": len(converter.features),
                "Status": status,
            })
        except Exception as exc:
            msg = f"ERROR – {exc}"
            print(f"  {msg}\n")
            log_rows.append({
                "Bundle": bundle_name,
                "cell_boundaries.csv.gz": str(cell_boundaries_path),
                "Cells in CSV": "ERROR",
                "GeoJSON Output": str(cell_geojson_out),
                "Features in GeoJSON": "ERROR",
                "Status": msg,
            })

        print()

    # ── Write Excel log ───────────────────────────────
    log_path = Output_path / "conversion_log.xlsx"
    log_df = pd.DataFrame(log_rows, columns=[
        "Bundle",
        "cell_boundaries.csv.gz",
        "Cells in CSV",
        "GeoJSON Output",
        "Features in GeoJSON",
        "Status",
    ])
    log_df.to_excel(log_path, index=False)
    print(f"Log saved to: {log_path}")


if __name__ == "__main__":
    main()