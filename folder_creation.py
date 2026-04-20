from pathlib import Path

src = Path('C:\\Users\\hxm220004\\Box\\Hemanth_Analysis_CAPS\\Diana-Tavares\\Pipeline_Results\\Stage1_Cell_Boundaries_2_GeoJSON\\Batch1')
dst = Path('C:\\Users\\hxm220004\\Box\\Hemanth_Analysis_CAPS\\Diana-Tavares\\Pipeline_Results\\Axon_Boundary_GeoJSON')

# Create destination if missing
dst.mkdir(parents=True, exist_ok=True)

# Iterate through immediate subdirectories in source
for folder in [x for x in src.iterdir() if x.is_dir()]:
    # Construct new path and create it
    (dst / folder.name).mkdir(exist_ok=True)
    print(f"Created: {folder.name}")
