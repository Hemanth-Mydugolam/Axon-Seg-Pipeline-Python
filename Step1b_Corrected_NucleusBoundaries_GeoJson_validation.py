import json
import logging
from pathlib import Path
from shapely.geometry import shape
from shapely.validation import explain_validity


class GeoJSONValidator:
    def __init__(self, geojson_path: Path, min_area: float = 10, log_file: str = "validation.log"):
        self.geojson_path = geojson_path
        self.min_area = min_area
        self.errors = []
        self.warnings = []
        self.geojson = None

        self._setup_logger(log_file)

    def _setup_logger(self, log_file):
        self.logger = logging.getLogger("GeoJSONValidator")
        self.logger.setLevel(logging.INFO)

        # Formatter
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

        # File handler
        fh = logging.FileHandler(log_file)
        fh.setFormatter(formatter)

        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)

        self.logger.addHandler(fh)
        self.logger.addHandler(ch)

    def load_geojson(self):
        with open(self.geojson_path, "r") as f:
            self.geojson = json.load(f)

        count = len(self.geojson.get("features", []))
        self.logger.info(f"Loaded GeoJSON with {count} features")

    def validate_feature_collection(self):
        if self.geojson.get("type") != "FeatureCollection":
            raise ValueError("GeoJSON must be a FeatureCollection")

        if "features" not in self.geojson or len(self.geojson["features"]) == 0:
            raise ValueError("No features found")

        self.logger.info("✅ FeatureCollection structure OK")

    def validate_crs(self):
        crs = self.geojson.get("crs")
        if crs:
            name = crs.get("properties", {}).get("name", "")
            if "EPSG:4326" in name or "lon" in name.lower():
                raise ValueError(
                    "GeoJSON uses geographic CRS (lat/lon). Xenium requires pixel coordinates."
                )

        self.logger.info("✅ CRS looks compatible")

    def _check_coordinates(self, coords):
        if isinstance(coords[0], (int, float)):
            if not all(isinstance(v, (int, float)) for v in coords):
                raise ValueError("Non-numeric coordinate found")
        else:
            for c in coords:
                self._check_coordinates(c)

    def validate_feature(self, feature, idx):
        if "geometry" not in feature or feature["geometry"] is None:
            raise ValueError("Missing geometry")

        geom = shape(feature["geometry"])

        if geom.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"Unsupported geometry type: {geom.geom_type}")

        if not geom.is_valid:
            raise ValueError(f"Invalid geometry: {explain_validity(geom)}")

        if geom.area < self.min_area:
            self.warnings.append(f"Feature {idx}: very small area ({geom.area:.2f})")

        self._check_coordinates(feature["geometry"]["coordinates"])

        props = feature.get("properties", {})
        if not props:
            self.warnings.append(f"Feature {idx}: missing properties")

        if not any(k.lower() in {"id", "cell_id", "objectid"} for k in props):
            self.warnings.append(f"Feature {idx}: no obvious ID")

    def validate_all_features(self):
        for i, feat in enumerate(self.geojson["features"], start=1):
            try:
                self.validate_feature(feat, i)
            except Exception as e:
                self.errors.append(f"Feature {i}: {e}")

    def summarize(self):
        self.logger.info(f"\n❌ Errors: {len(self.errors)}")
        for e in self.errors[:10]:
            self.logger.error(e)

        self.logger.info(f"\n⚠️ Warnings: {len(self.warnings)}")
        for w in self.warnings[:10]:
            self.logger.warning(w)

        if not self.errors:
            self.logger.info("✅ GeoJSON PASSED validation")
        else:
            self.logger.error("❌ Fix errors before running downstream steps")

    def run(self):
        try:
            self.load_geojson()
            self.validate_feature_collection()
            self.validate_crs()
            self.validate_all_features()
            self.summarize()
        except Exception as e:
            self.logger.exception(f"Critical failure: {e}")


# -----------------------------
# Usage
# -----------------------------
if __name__ == "__main__":
    validator = GeoJSONValidator(
        geojson_path=Path("./Input/output-XETG00216__0033801__Region_2__20250115__201447/GeoJson_Files/nucelus_final.geojson"),
        min_area=10,
        log_file="geojson_validation.log"
    )

    validator.run()