# Togo-box shared config
# Edit this file before running a workflow. Do not commit private emails or tokens.

## Identity
email: your@email.com        # Used for CrossRef polite pool and Unpaywall API

## literature_radar settings
days_back: 7                 # How many days back to scan
max_arxiv_results: 60
max_crossref_rows: 25
max_selected_papers: 10
report_language: zh          # zh by default; keep paper titles and links in original language

## Keywords - Atmospheric Chemistry Track
atmo_keywords:
  - atmospheric chemistry
  - aerosol
  - tropospheric ozone
  - OH radical
  - GEOS-Chem
  - emission inventory
  - satellite retrieval
  - secondary organic aerosol
  - NOx chemistry
  - halogen chemistry
  - photolysis
  - HONO
  - cloud chemistry
  - atmospheric oxidation

## Keywords - AI/ML for Science Track
ml_keywords:
  - neural emulator climate
  - physics-informed machine learning atmospheric
  - foundation model earth system
  - surrogate model chemistry transport
  - machine learning air quality
  - deep learning weather
  - uncertainty quantification geophysical
  - transformer climate model

## Target Journals (leave empty [] to search all journals)
journals:
  - Atmospheric Chemistry and Physics
  - Journal of Geophysical Research Atmospheres
  - Geophysical Research Letters
  - Environmental Science and Technology
  - Nature Climate Change
  - npj Climate and Atmospheric Science
  - Journal of Climate
  - Atmospheric Environment
  - Science Advances

## arXiv Categories
arxiv_cats:
  - physics.ao-ph
  - cs.LG
  - stat.ML
  - physics.geo-ph

## Output
output_dir: output/
