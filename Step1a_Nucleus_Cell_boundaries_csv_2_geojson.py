###################################################################
##-------------   FUNCTIONAL OOP CODE FOR 1ST STAGE -------------##
###################################################################
import pandas as pd
import geojson
from shapely.geometry import Polygon, MultiPolygon
import tifffile
import xml.etree.ElementTree as ET
from pathlib import Path


def create_empty_folders_from_source(source_folder, target_folder):
    """
    Create empty folders in target_folder with the same names as those present in source_folder.
    
    Parameters:
    - source_folder: path to the folder whose folder names you want to replicate
    - target_folder: path where empty folders should be created
    """
    source_folder = Path(source_folder)
    target_folder = Path(target_folder)
    target_folder.mkdir(parents=True, exist_ok=True)

    # Iterate over all folders in the source folder
    for folder in source_folder.iterdir():
        if folder.is_dir():
            new_folder = target_folder / folder.name
            new_folder.mkdir(exist_ok=True)
            print(f"[CREATED] {new_folder}")


class XeniumBoundaryConverter:
    def __init__(self, main_path, output_dir):
        self.main_path = Path(main_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)

        self.morphology_tiff = self.main_path / "morphology_focus" / "morphology_focus_0000.ome.tif"
        #self.morphology_tiff = self.main_path / "morphology_focus" / "ch0002_18s.ome.tif"
        self.pixel_um_x, self.pixel_um_y = self._get_pixel_sizes()
        print(f"[INFO] Microns per pixel: {self.pixel_um_x}, {self.pixel_um_y}")

    # -----------------------------------------------------
    # Step 1: Extract pixel scaling
    # -----------------------------------------------------
    def _get_pixel_sizes(self):
        with tifffile.TiffFile(self.morphology_tiff) as tif:
            ome_xml = tif.ome_metadata

        root = ET.fromstring(ome_xml)
        ns = {"ome": "http://www.openmicroscopy.org/Schemas/OME/2016-06"}
        pixels = root.find(".//ome:Pixels", ns)

        size_x_um = float(pixels.get("PhysicalSizeX"))
        size_y_um = float(pixels.get("PhysicalSizeY"))

        return size_x_um, size_y_um

    # -----------------------------------------------------
    # Step 2: Convert CSV to GeoJSON FeatureCollection
    # -----------------------------------------------------
    def convert_boundaries(self, csv_path, output_geojson_path):
        csv_path = Path(csv_path)
        output_geojson_path = Path(output_geojson_path)

        print(f"[INFO] Reading: {csv_path}")
        df = pd.read_csv(csv_path)

        # Count cells
        num_cells = df["cell_id"].nunique()

        # Pixel conversion
        df["x_px"] = df["vertex_x"] / self.pixel_um_x
        df["y_px"] = df["vertex_y"] / self.pixel_um_y

        # Build polygons grouped by cell_id
        features = []
        for cell_id, group in df.groupby("cell_id"):
            coords = list(zip(group["x_px"].tolist(), group["y_px"].tolist()))
            poly = Polygon(coords)

            if not poly.is_valid:
                poly = poly.buffer(0)

            # Polygon or MultiPolygon handling
            if isinstance(poly, Polygon):
                geometry = geojson.Polygon([list(poly.exterior.coords)])
            elif isinstance(poly, MultiPolygon):
                geometry = geojson.MultiPolygon(
                    [[list(p.exterior.coords)] for p in poly.geoms]
                )

            # Feature creation
            feature = geojson.Feature(
                geometry=geometry,
                properties={"cell_id": cell_id}
            )
            features.append(feature)

        # Save GeoJSON
        fc = geojson.FeatureCollection(features)
        with open(output_geojson_path, "w") as f:
            geojson.dump(fc, f)

        print(f"[SUCCESS] Saved GeoJSON → {output_geojson_path}")

        # Cross-validate counts
        feature_count = len(fc["features"])
        print("---- Cross Validation ----")
        print("Cells in CSV:", num_cells)
        print("Features in GeoJSON:", feature_count)

        if num_cells == feature_count:
            print("✅ All cells successfully converted!\n")
        else:
            print("⚠️ Mismatch detected! Some cells may be missing.\n")

        return fc

    # -----------------------------------------------------
    # Step 3: Run conversion for multiple files
    # -----------------------------------------------------
    def process_multiple_boundaries(self, boundaries_dict):
        """
        boundaries_dict = {
            "cell_boundaries": "cell_boundaries.csv.gz",
            "nucleus_boundaries": "nucleus_boundaries.csv.gz"
        }
        """
        for name, filename in boundaries_dict.items():
            input_file = self.main_path / filename
            output_file = self.output_dir / f"{name}_pixel_scaled.geojson"

            print(f"\n=== Processing {name} ===")
            self.convert_boundaries(input_file, output_file)


if __name__ == "__main__":
    # Xenium bundles folder path where the original cell_boundaries CSV files are located
    Main_folder_Xenium = Path(r"/Users/hxm220004/Box/tavares_lab_projects/XENIUM/20251215__193020__SN4/")
    # Results folder path where empty folders will be created and GeoJSON files will be saved
    main_parent_path = Path(r"C:/Users/hxm220004/Box/Hemanth_Analysis_CAPS/Diana-Tavares/Xenium_Segment_Data_for_Qupath_Annotations/Batch2/")
    
    # Create empty folders from source to target
    create_empty_folders_from_source(Main_folder_Xenium, main_parent_path)
    
    output_root = main_parent_path

    # Loop over all subfolders in the main parent path
    for folder in main_parent_path.iterdir():
        if folder.is_dir():
            print(f"\n=== Processing folder: {folder.name} ===")
            
            # Create output folder for this subfolder
            output_dir = output_root / folder.name / "GeoJson_Files"
            output_dir.mkdir(parents=True, exist_ok=True)
            Main_path_fol = Main_folder_Xenium / folder.name

            # Initialize converter for this folder
            converter = XeniumBoundaryConverter(Main_path_fol, output_dir)

            # Define boundary files
            boundary_files = {
                "cell_boundaries": "cell_boundaries.csv.gz",
                "nucleus_boundaries": "nucleus_boundaries.csv.gz"
            }

            # Process both boundaries for this folder
            converter.process_multiple_boundaries(boundary_files)
