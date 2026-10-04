# How search quality was checked

`eval/queries.json` holds 14 test searches (the 5 from the brief + 8 content queries + 1 negative query).
Each has: what the user wants, which assets should appear, and automatic weak labels:
* COCO images → relevant if the human-written **COCO captions** contain the required words (independent of our model)
* other assets → relevant if the path matches the source query folder created by `fetch_dataset.py`
  (used **only for scoring**, never by the search)

`python eval/run_eval.py` reports P@5, P@10, rank of first relevant hit, top score, and writes
`data/eval_report.html` (thumbnails with green/red/grey borders) so every list can be eyeballed.
The negative query ("spaceship landing on Mars") checks that unrelated queries do not return confident hits.

After running it, write the observations (what failed and why) into the "Notes on weak cases" section of
`docs/EVALUATION_RESULTS.md`. Typical things to look for: abstract queries ("customer testimonial" has no literal visual),
counting/relations ("woman *with* a cat" returns cats-only or women-only), short videos with one scene, scanned PDFs without text.
Tuning knobs: `CLIP_LO/CLIP_HI/TEXT_LO/TEXT_HI` and `MIN_SCORE`.
