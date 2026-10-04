# Search evaluation results

Dataset: 4 images + 3 videos + 3 PDFs (plus edge-case files). Relevant = expected file appears in results.

| # | Query | What the user wants | Expected asset | Rank of expected | Top score | Top 3 returned | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | a woman sitting on a sofa | photo of a woman indoors | pexels-anna-alexes | 1 | 0.61 | 0.61 pexels-anna-alexes-18139455-7682911.jp<br>0.37 4231453-hd_1920_1080_25fps.mp4<br>0.22 pexels-saplak-19649375.jpg | good |
| 2 | a bird | bird photo | pexels-saplak | 1 | 0.69 | 0.69 pexels-saplak-19649375.jpg<br>0.27 healthy_recipes_cookbook.pdf<br>0.24 pexels-anna-alexes-18139455-7682911.jp | good |
| 3 | a slice of cake on a plate | food photo | pexels-sarah-rosado | 1 | 0.72 | 0.72 pexels-sarah-rosado-1025745902-3981619<br>0.33 5348781-hd_1920_1080_30fps.mp4<br>0.22 healthy_recipes_cookbook.pdf | good |
| 4 | a house in a green field | property / landscape photo | pexels-adit-syahfiar | 2 | 0.89 | 0.89 greenview_residential_project_brochure<br>0.26 pexels-adit-syahfiar-991235-38302184.j<br>0.13 pexels-saplak-19649375.jpg | ok |
| 5 | videos of a modern living room | interior video | 4231453 | 1 | 0.81 | 0.81 4231453-hd_1920_1080_25fps.mp4<br>0.51 5348781-hd_1920_1080_30fps.mp4<br>0.46 greenview_residential_project_brochure | good |
| 6 | Videos containing construction activity | construction footage | 5348781 | 1 | 1.00 | 1.00 5348781-hd_1920_1080_30fps.mp4<br>0.48 semantic_image_retrieval_machine_learn<br>0.44 healthy_recipes_cookbook.pdf | good |
| 7 | construction workers on a building site | construction footage | 5348781 | 1 | 0.91 | 0.91 5348781-hd_1920_1080_30fps.mp4<br>0.37 greenview_residential_project_brochure<br>0.33 healthy_recipes_cookbook.pdf | good |
| 8 | a dog | dog footage | 19201621 | 1 | 0.54 | 0.54 19201621-uhd_3840_2160_24fps.mp4<br>0.33 4231453-hd_1920_1080_25fps.mp4<br>0.31 pexels-anna-alexes-18139455-7682911.jp | good |
| 9 | Brochures related to residential projects | residential brochure PDF | greenview | 1 | 0.91 | 0.91 greenview_residential_project_brochure<br>0.70 semantic_image_retrieval_machine_learn<br>0.70 healthy_recipes_cookbook.pdf | good |
| 10 | apartments with swimming pool and gym | text inside the brochure | greenview | 1 | 0.73 | 0.73 greenview_residential_project_brochure<br>0.45 5348781-hd_1920_1080_30fps.mp4<br>0.32 4231453-hd_1920_1080_25fps.mp4 | good |
| 11 | research paper about machine learning | ML paper PDF | semantic_image_retrieval | 1 | 0.71 | 0.71 semantic_image_retrieval_machine_learn<br>0.69 healthy_recipes_cookbook.pdf<br>0.42 pexels-saplak-19649375.jpg | good |
| 12 | easy pasta and pizza recipes | recipe PDF | healthy_recipes | 1 | 1.00 | 1.00 healthy_recipes_cookbook.pdf<br>0.27 pexels-sarah-rosado-1025745902-3981619<br>0.15 pexels-anna-alexes-18139455-7682911.jp | good |
| 13 | Customer testimonial videos | KNOWN WEAK: no testimonial video exists in this dataset | none | - | 0.55 | 0.55 healthy_recipes_cookbook.pdf<br>0.48 semantic_image_retrieval_machine_learn<br>0.39 5348781-hd_1920_1080_30fps.mp4 | WEAK (confident false positive) |
| 14 | a spaceship landing on mars | NEGATIVE test: nothing matches | none | - | 0.33 | 0.33 5348781-hd_1920_1080_30fps.mp4<br>0.25 4231453-hd_1920_1080_25fps.mp4 | PASS (no confident hit) |

**Summary:** 12/14 queries fully correct (rank 1 or correctly empty).

## Where search performs poorly

_Write 3-4 observations here (see the failing rows above)._
