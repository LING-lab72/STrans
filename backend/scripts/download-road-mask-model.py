from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.road_mask import road_mask_service


if __name__ == "__main__":
    print(road_mask_service.download_model())
