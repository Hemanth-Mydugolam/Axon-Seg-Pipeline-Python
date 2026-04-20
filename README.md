# Xenium Axon Segmentation Pipeline

A multi-step Python pipeline for processing **10x Xenium spatial transcriptomics** data.  
It converts raw cell/nucleus boundary CSV files into GeoJSON annotations, rasterizes them into binary masks, subtracts cell bodies to isolate axon regions, and produces publication-quality visualizations.

---

## Pipeline Overview

```
Raw Xenium Bundle
      │
      ▼
Step 1a  CSV boundaries → GeoJSON (pixel-scaled)
      │
      ▼
Step 1b  GeoJSON validation
      │
      ▼
Step 2a  Cell boundaries CSV → pixel-scaled GeoJSON          ← IS-segmented bundles
      │
      ▼
Step 2b  Cell boundary GeoJSON → binary mask (.npy + .png)
      │
      ▼
Step 2c  Axon GeoJSON + cell mask → filtered axon mask
      │
      ▼
Step 3   cells.zarr.zip → nucleus & cell mask visualization
```

---

## Directory Structure

```
Axon_Pipeline_Python/
├── Step1a_Nucleus_Cell_boundaries_csv_2_geojson.py
├── Step1b_Corrected_NucleusBoundaries_GeoJson_validation.py
├── Step2a_CellBoundaries_2_GeoJson.py
├── Step2b_CellBoundaries_GeoJson_2_Mask.py
├── Step2c_AxonMask_Creation.py
├── Step3_Cells_zarr_plotting.py
├── folder_creation.py
└── requirements.txt
```

---

## Requirements

**Python 3.9+** is recommended.

Install all dependencies with:

```bash
pip install -r requirements.txt
```

| Package | Purpose |
|---|---|
| `pandas` | CSV / tabular data handling |
| `openpyxl` | Excel log writing (required by pandas) |
| `numpy` | Array operations |
| `geojson` | GeoJSON file creation |
| `shapely` | Polygon geometry |
| `rasterio` | Polygon rasterization |
| `tifffile` | Reading OME-TIFF metadata and image dimensions |
| `Pillow` | PNG image saving |
| `scipy` | Connected component labeling |
| `scikit-image` | Global component relabeling |
| `matplotlib` | Mask visualization plots |
| `zarr` | Reading Xenium `.zarr.zip` cell segmentation files |
| `aicsimageio` | OME-TIFF reading (Step 2c) |

> **Note:** Install `zarr<3` (`pip install "zarr<3"`) for compatibility with Xenium-generated zarr v2 files.

---

## Input Data

Each pipeline step expects **Xenium bundle folders** organized like this:

```
Stage1_IS/Batch1/
└── output-XETG00216__<slide>__<region>__<date>__<time>_im_segment_stage1/
    ├── morphology_focus/
    │   └── *.ome.tif               ← morphology image (used for pixel scale + dimensions)
    ├── cell_boundaries.csv.gz      ← cell polygon vertices in microns
    └── nucleus_boundaries.csv.gz   ← nucleus polygon vertices in microns

Axon_Boundary_GeoJSON/Batch1/
└── <same bundle name>/
    └── *axon*.geojson              ← axon annotation GeoJSON (one per bundle)

Stage2_IS/
└── <bundle>/
    └── cells.zarr.zip              ← Xenium cell segmentation zarr archive
```

---

## Step-by-Step Guide

### Step 1a — CSV Boundaries to GeoJSON

**Script:** `Step1a_Nucleus_Cell_boundaries_csv_2_geojson.py`

Converts `cell_boundaries.csv.gz` and `nucleus_boundaries.csv.gz` from micron coordinates to **pixel coordinates** using the OME-TIFF physical pixel size metadata, then saves them as GeoJSON FeatureCollections.

**Iterates over:** All bundle sub-folders in the source Xenium directory.

**Output per bundle** (in `Xenium_Segment_Data_for_Qupath_Annotations/Batch2/<bundle>/GeoJson_Files/`):
```
cell_boundaries_pixel_scaled.geojson
nucleus_boundaries_pixel_scaled.geojson
```

---

### Step 1b — GeoJSON Validation

**Script:** `Step1b_Corrected_NucleusBoundaries_GeoJson_validation.py`

Validates a GeoJSON file for:
- Correct `FeatureCollection` structure
- Compatible coordinate reference system (pixel, not lat/lon)
- Valid polygon geometries (no self-intersections)
- Minimum area threshold
- Presence of cell ID properties

Writes a `.log` file summarising errors and warnings.

**Usage:** Point `geojson_path` to the file to validate and run directly.

---

### Step 2a — Cell Boundaries to Pixel-Scaled GeoJSON

**Script:** `Step2a_CellBoundaries_2_GeoJson.py`

Reads `cell_boundaries.csv.gz` from IS-segmented Xenium bundles and converts micron coordinates to pixel coordinates using the OME-TIFF pixel size. Saves one GeoJSON per bundle and cross-validates cell counts.

**Configure in `main()`:**
```python
main_path   = Path("...Stage1_IS/Batch1/")          # input bundles
Output_path = Path("...Stage1_Cell_Boundaries_2_GeoJSON/Batch1")  # output root
```

**Output per bundle** (`Output_path/<bundle>/`):
```
cell_boundaries_pixel_scaled.geojson
```

**Log:** `Output_path/conversion_log.xlsx`

| Column | Description |
|---|---|
| Bundle | Bundle folder name |
| cell_boundaries.csv.gz | Full input path |
| Cells in CSV | Unique cell count |
| GeoJSON Output | Full output path |
| Features in GeoJSON | Feature count |
| Status | `OK`, `MISMATCH`, `SKIPPED`, or `ERROR` |

---

### Step 2b — GeoJSON to Binary Mask

**Script:** `Step2b_CellBoundaries_GeoJson_2_Mask.py`

Rasterizes `cell_boundaries_pixel_scaled.geojson` (from Step 2a) onto a canvas matching the OME-TIFF image dimensions to produce a binary mask.

**Configure in `main()`:**
```python
main_path   = Path("...Stage1_IS/Batch1/")
Output_path = Path("...Stage1_Cell_Boundaries_2_GeoJSON/Batch1")
```

**Output per bundle** (`Output_path/<bundle>/`):
```
<bundle>_mask.npy    ← binary numpy mask (uint8)
<bundle>_mask.png    ← visual binary mask image
```

**Log:** `Output_path/mask_generation_log.xlsx`

| Column | Description |
|---|---|
| Bundle | Bundle folder name |
| GeoJSON Input | Full input path |
| Cells in GeoJSON | Feature count |
| Mask NPY / PNG | Full output paths |
| Status | `OK`, `SKIPPED`, or `ERROR` |

> **Run this before Step 2c.** The `.npy` mask is used as input for cell body subtraction.

---

### Step 2c — Axon Mask Creation

**Script:** `Step2c_AxonMask_Creation.py`

The core axon isolation step:
1. Loads the axon annotation GeoJSON
2. Rasterizes axon polygons onto the image canvas (unique ID per connected component)
3. **Subtracts** the cell boundary mask (Step 2b) to remove cell body overlap
4. Relabels connected components globally
5. Filters out small components (< 1000 pixels)
6. Saves colored visualizations

**Configure in `main()`:**
```python
main_path      = Path("...Stage1_IS/Batch1/")
axon_root      = Path("...Axon_Boundary_GeoJSON/Batch1")
cell_mask_root = Path("...Stage1_Cell_Boundaries_2_GeoJSON/Batch1")
```

**Output per bundle** (`cell_mask_root/<bundle>/`):
```
<bundle>_axon_raw_mask.npy           ← rasterized axon mask before subtraction
<bundle>_axon_raw_mask_vis.png       ← binary visualization
<bundle>_axon_components_colored.png ← colored component map after subtraction
<bundle>_axon_components_rgb.png     ← RGB colored component image
<bundle>_FilteredAxon.npy            ← final filtered axon mask (≥ 1000 px)
<bundle>_FilteredAxon_binary.png
<bundle>_FilteredAxon_colored.png
<bundle>_FilteredAxon_colored_rgb.png
```

**Log:** `cell_mask_root/axon_mask_log.xlsx`

| Column | Description |
|---|---|
| Bundle | Bundle folder name |
| GeoJSON Input | Axon GeoJSON path |
| Cell Boundary Mask (Step2b) | `.npy` mask used for subtraction |
| Polygons in GeoJSON | Number of axon polygons |
| Components after subtraction | Connected components post-subtraction |
| Filtered components (≥1000px) | Final component count |
| Status | `OK`, `SKIPPED`, or `ERROR` |

---

### Step 3 — Zarr Cell Mask Visualization

**Script:** `Step3_Cells_zarr_plotting.py`

Reads the `cells.zarr.zip` archive produced by Xenium segmentation, extracts nucleus and cell masks, colorizes them with random per-ID colors, and saves a side-by-side high-resolution plot.

**Configure in `main()`:**
```python
main_path   = Path("...Stage2_IS/")
output_root = Path("...Stage2_Cells_Zarr_Plot")
```

**Output per bundle** (`output_root/<bundle>/`):
```
<bundle>_cells_zarr_plot.png    ← 600 DPI side-by-side nucleus + cell mask
```

**Log:** `output_root/zarr_plot_log.xlsx`

| Column | Description |
|---|---|
| Bundle | Bundle folder name |
| Zarr Input | Full zarr path |
| Nucleus Cells | Unique nucleus IDs |
| Cell Cells | Unique cell IDs |
| Plot Output | Full output path |
| Status | `OK`, `SKIPPED`, or `ERROR` |

---

### Utility — Folder Creation

**Script:** `folder_creation.py`

Mirrors the bundle sub-folder structure from one directory into another (creates empty folders only). Useful for setting up the `Axon_Boundary_GeoJSON` directory tree before placing axon GeoJSON files.

```bash
python folder_creation.py
```

---

## Execution Order

```
python Step1a_Nucleus_Cell_boundaries_csv_2_geojson.py   # (optional — standard bundles)
python Step1b_Corrected_NucleusBoundaries_GeoJson_validation.py  # (optional — validate)
python Step2a_CellBoundaries_2_GeoJson.py                # IS bundles → GeoJSON
python Step2b_CellBoundaries_GeoJson_2_Mask.py           # GeoJSON → cell boundary mask
python Step2c_AxonMask_Creation.py                       # axon GeoJSON + mask → axon mask
python Step3_Cells_zarr_plotting.py                      # zarr → visualization
```

---

## Windows Long Path Note

Bundle names in Xenium datasets are long (70+ characters). Combined with deep output paths, total file paths can exceed Windows' 260-character `MAX_PATH` limit. All file-write operations in this pipeline use the `\\?\` extended-length path prefix internally to bypass this limit — no manual Windows registry changes are required.

---

## Output Summary

| Step | Key Output | Location |
|---|---|---|
| 1a | `*_pixel_scaled.geojson` | `Xenium_Segment_Data.../GeoJson_Files/` |
| 2a | `cell_boundaries_pixel_scaled.geojson` | `Stage1_Cell_Boundaries_2_GeoJSON/Batch1/<bundle>/` |
| 2b | `<bundle>_mask.npy/png` | same as 2a |
| 2c | `<bundle>_FilteredAxon.*` | same as 2a |
| 3  | `<bundle>_cells_zarr_plot.png` | `Stage2_Cells_Zarr_Plot/<bundle>/` |
| All | `*_log.xlsx` | respective output root |
