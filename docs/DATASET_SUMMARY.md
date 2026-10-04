# Dataset summary

Folder: `C:\Users\Sahup\Downloads\dam-assignment\dam\media`

| Type | Files | Size |
|---|---:|---:|
| image | 6 | 8.1 MB |
| video | 5 | 31.7 MB |
| pdf | 4 | 0.0 MB |
| unsupported | 2 | 0.0 MB |
| **total** | **17** | **39.8 MB** |

**Breakdown:** 10 real assets (4 images from Pexels, 3 videos from Pexels, 3 PDFs: a residential brochure, an ML paper and a recipe book) plus 7 deliberate edge cases (corrupted image, empty video, truncated video, truncated PDF, duplicate image, unsupported .txt and .zip).

**Limitation:** The brief asks for 5–10 GB. This dataset is about 40 MB because of limited download time and local hardware/storage constraints. The indexer processes files incrementally and saves progress after each file, so larger datasets can be handled without changing the core indexing design. The project also includes `scripts/fetch_dataset.py` for downloading larger public datasets.