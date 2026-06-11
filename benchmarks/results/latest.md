# resolvekit benchmark — 2026-06-11

Hardware: arm, 18 cores, 49,152 MB RAM, Python 3.12.13.
Warmup: 100 queries discarded. Seed: 42.

## Datasets

| dataset | rows | sha256 |
|---|---|---|
| ambiguous | 58 | a578ad16e956… |
| eval_geo | 467 | f115ac82771c… |
| eval_org | 25 | 4b527129a91e… |
| geo_admin | 2,657 | c00b4865d2ce… |
| geo_cities | 2,148 | 39d087a1af08… |
| geo_countries_en | 4,155 | 71453cc82206… |
| geo_countries_multilingual | 2,240 | 0cdb932d48ce… |
| no_match | 43 | 58405a1893e1… |

## Results

### ambiguous

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| country_converter | 1.3.2 | 0.913 | [0.73, 0.98] | 48.3% | 0.000 | 0.000 | 0.1 | 0.1 | 9342.8 | 115.6 | 0.1 | — |
| countryguess | 0.4.9 | 0.957 | [0.79, 0.99] | 48.3% | 0.000 | 0.000 | 0.0 | 0.1 | 32641.5 | 113.3 | 0.3 | — |
| data_commons_resolve | 2.1.6 | 0.909 | [0.79, 0.96] | 93.1% | 0.023 | 0.000 | 0.0 | 0.2 | 12578.3 | 125.9 | 0.3 | — |
| geonamescache | 3.0.1 | 0.536 | [0.36, 0.70] | 60.3% | 0.214 | 0.000 | 0.0 | 68.4 | 68.3 | 190.8 | 164.7 | — |
| hdx_python_country | 4.1.1 | 1.000 | [0.86, 1.00] | 48.3% | 0.000 | 0.000 | 0.0 | 4.9 | 2057.5 | 177.3 | 0.2 | — |
| pycountry | 26.2.16 | 0.652 | [0.45, 0.81] | 48.3% | 0.000 | 0.000 | 0.0 | 0.0 | 342216.0 | 112.6 | 20.1 | — |
| rapidfuzz_dict | 3.14.5 | 0.783 | [0.58, 0.90] | 48.3% | 0.217 | 0.000 | 0.2 | 0.4 | 4747.6 | 112.9 | 4.1 | — |
| resolvekit | 0.1.2 | 0.872 | [0.75, 0.94] | 100.0% | 0.000 | 0.000 | 2.3 | 3.3 | 463.4 | 1139.5 | 9.6 | 807.3 |
| resolvekit_typed | 0.1.2 | 0.915 | [0.80, 0.97] | 100.0% | 0.000 | 0.000 | 2.2 | 3.6 | 477.7 | 174.0 | 9.6 | 807.3 |

#### recall metrics

| tool | abst R | amb recall |
|---|---|---|
| country_converter | 0.000 | 0.913 |
| countryguess | 0.000 | 0.957 |
| data_commons_resolve | 0.000 | 0.909 |
| geonamescache | 0.000 | 0.536 |
| hdx_python_country | 0.000 | 1.000 |
| pycountry | 0.000 | 0.652 |
| rapidfuzz_dict | 0.000 | 0.783 |
| resolvekit | 0.000 | 0.872 |
| resolvekit_typed | 0.000 | 0.915 |

#### per-capability accuracy

| tool | admin_hierarchy | ambiguity_signaling |
|---|---|---|
| country_converter | 0.875 | 0.913 |
| countryguess | 1.000 | 0.957 |
| data_commons_resolve | 0.880 | 0.909 |
| geonamescache | 0.778 | 0.536 |
| hdx_python_country | 1.000 | 1.000 |
| pycountry | 0.875 | 0.652 |
| rapidfuzz_dict | 0.875 | 0.783 |
| resolvekit | 0.821 | 0.872 |
| resolvekit_typed | 0.893 | 0.915 |

#### per-entity-type accuracy

| tool | admin1 | admin2 | admin3 | admin4 | city | country |
|---|---|---|---|---|---|---|
| country_converter | — | — | — | — | — | 0.913 (n=23) |
| countryguess | — | — | — | — | — | 0.957 (n=23) |
| data_commons_resolve | 0.833 (n=6) | 0.900 (n=10) | — | — | 1.000 (n=6) | 0.909 (n=22) |
| geonamescache | — | — | — | — | 0.000 (n=6) | 0.682 (n=22) |
| hdx_python_country | — | — | — | — | — | 1.000 (n=23) |
| pycountry | — | — | — | — | — | 0.652 (n=23) |
| rapidfuzz_dict | — | — | — | — | — | 0.783 (n=23) |
| resolvekit | 0.667 (n=6) | 0.700 (n=10) | 1.000 (n=2) | 1.000 (n=1) | 0.833 (n=6) | 1.000 (n=22) |
| resolvekit_typed | 1.000 (n=6) | 0.700 (n=10) | 1.000 (n=2) | 1.000 (n=1) | 0.833 (n=6) | 1.000 (n=22) |

### eval_geo

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| country_converter | 1.3.2 | 0.700 | [0.40, 0.89] | 23.6% | 0.000 | 0.250 | 0.1 | n/a | 11116.8 | 115.6 | 0.1 | — |
| countryguess | 0.4.9 | 0.800 | [0.49, 0.94] | 23.6% | 0.100 | 0.500 | 0.0 | n/a | 11155.0 | 113.3 | 0.3 | — |
| data_commons_resolve | 2.1.6 | 0.763 | [0.70, 0.82] | 65.7% | 0.092 | 0.281 | 0.1 | 0.2 | 8552.3 | 125.9 | 0.3 | — |
| geonamescache | 3.0.1 | 0.280 | [0.20, 0.37] | 42.8% | 0.330 | 0.188 | 0.0 | 70.0 | 33.2 | 190.8 | 164.7 | — |
| hdx_python_country | 4.1.1 | 0.800 | [0.49, 0.94] | 23.6% | 0.000 | 0.333 | 0.1 | n/a | 451.6 | 177.3 | 0.2 | — |
| pycountry | 26.2.16 | 0.500 | [0.24, 0.76] | 23.6% | 0.000 | 0.167 | 0.0 | n/a | 305343.4 | 112.6 | 20.1 | — |
| rapidfuzz_dict | 3.14.5 | 0.600 | [0.31, 0.83] | 23.6% | 0.400 | 0.000 | 0.2 | n/a | 4457.3 | 112.9 | 4.1 | — |
| resolvekit | 0.1.2 | 0.886 | [0.85, 0.91] | 100.0% | 0.052 | 0.538 | 0.5 | 2.5 | 1190.4 | 1139.5 | 9.6 | 807.3 |
| resolvekit_typed | 0.1.2 | 0.913 | [0.88, 0.94] | 100.0% | 0.025 | 0.423 | 0.3 | 2.4 | 1422.4 | 174.0 | 9.6 | 807.3 |

#### recall metrics

| tool | abst R | amb recall |
|---|---|---|
| country_converter | 1.000 | 1.000 |
| countryguess | 1.000 | 1.000 |
| data_commons_resolve | 0.643 | 0.915 |
| geonamescache | 1.000 | 0.375 |
| hdx_python_country | 1.000 | 1.000 |
| pycountry | 1.000 | 0.750 |
| rapidfuzz_dict | 0.000 | 0.750 |
| resolvekit | 0.824 | 0.894 |
| resolvekit_typed | 0.647 | 0.929 |

#### per-capability accuracy

| tool | informal_alias | iso_code | multilingual | transliteration |
|---|---|---|---|---|
| country_converter | 1.000 | — | 0.000 | 0.000 |
| countryguess | 1.000 | — | 0.500 | 0.000 |
| data_commons_resolve | 0.913 | 0.900 | 0.667 | 0.933 |
| geonamescache | 0.133 | 0.000 | 0.000 | 0.091 |
| hdx_python_country | 1.000 | — | 1.000 | 1.000 |
| pycountry | 0.000 | — | 0.000 | 0.000 |
| rapidfuzz_dict | 0.000 | — | 0.500 | 1.000 |
| resolvekit | 0.938 | 1.000 | 0.875 | 0.833 |
| resolvekit_typed | 0.969 | 1.000 | 0.875 | 0.833 |

#### per-entity-type accuracy

| tool | admin1 | admin2 | admin3 | admin4 | admin5 | city | continent | continental_union | country | world_region |
|---|---|---|---|---|---|---|---|---|---|---|
| country_converter | — | — | — | — | — | — | — | — | 0.700 (n=10) | — |
| countryguess | — | — | — | — | — | — | — | — | 0.800 (n=10) | — |
| data_commons_resolve | 0.700 (n=40) | 0.615 (n=26) | — | — | — | 0.794 (n=68) | — | — | 0.822 (n=73) | — |
| geonamescache | — | — | — | — | — | 0.000 (n=44) | — | — | 0.500 (n=56) | — |
| hdx_python_country | — | — | — | — | — | — | — | — | 0.800 (n=10) | — |
| pycountry | — | — | — | — | — | — | — | — | 0.500 (n=10) | — |
| rapidfuzz_dict | — | — | — | — | — | — | — | — | 0.600 (n=10) | — |
| resolvekit | 0.782 (n=55) | 0.969 (n=32) | 0.818 (n=33) | 0.875 (n=32) | 0.886 (n=35) | 0.889 (n=72) | 1.000 (n=7) | 1.000 (n=9) | 0.964 (n=83) | 0.556 (n=9) |
| resolvekit_typed | 0.818 (n=55) | 0.938 (n=32) | 0.848 (n=33) | 0.938 (n=32) | 0.971 (n=35) | 0.889 (n=72) | 1.000 (n=7) | 1.000 (n=9) | 0.952 (n=83) | 1.000 (n=9) |

### eval_org

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| resolvekit | 0.1.2 | 0.750 | [0.53, 0.89] | 100.0% | 0.100 | 1.000 | 0.9 | 3.4 | 694.8 | 1139.5 | 9.6 | 807.3 |
| resolvekit_typed | 0.1.2 | 0.750 | [0.53, 0.89] | 100.0% | 0.100 | 1.000 | 0.9 | 3.2 | 735.4 | 174.0 | 9.6 | 807.3 |
| country_converter | *skipped (scope: supports ['country'], dataset has ['org'])* | — | — | — | — | — | — | — | — | — | — | — |
| countryguess | *skipped (scope: supports ['country'], dataset has ['org'])* | — | — | — | — | — | — | — | — | — | — | — |
| geonamescache | *skipped (scope: supports ['city', 'country'], dataset has ['org'])* | — | — | — | — | — | — | — | — | — | — | — |
| hdx_python_country | *skipped (scope: supports ['country'], dataset has ['org'])* | — | — | — | — | — | — | — | — | — | — | — |
| pycountry | *skipped (scope: supports ['country'], dataset has ['org'])* | — | — | — | — | — | — | — | — | — | — | — |
| rapidfuzz_dict | *skipped (scope: supports ['country'], dataset has ['org'])* | — | — | — | — | — | — | — | — | — | — | — |

#### recall metrics

| tool | abst R | amb recall |
|---|---|---|
| resolvekit | 1.000 | 1.000 |
| resolvekit_typed | 1.000 | 1.000 |

#### per-capability accuracy

| tool | informal_alias | iso_code |
|---|---|---|
| resolvekit | 0.714 | 0.556 |
| resolvekit_typed | 0.714 | 0.556 |

#### per-entity-type accuracy

| tool | org |
|---|---|
| resolvekit | 0.750 (n=20) |
| resolvekit_typed | 0.750 (n=20) |

### geo_admin

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| data_commons_resolve | 2.1.6 | 0.598 | [0.58, 0.62] | 80.7% | 0.146 | 0.000 | 0.1 | 0.2 | 8970.8 | 125.9 | 0.3 | — |
| resolvekit | 0.1.2 | 0.934 | [0.92, 0.94] | 100.0% | 0.043 | 0.000 | 0.5 | 2.7 | 937.6 | 1139.5 | 9.6 | 807.3 |
| resolvekit_typed | 0.1.2 | 0.977 | [0.97, 0.98] | 100.0% | 0.001 | 0.000 | 0.2 | 1.5 | 2141.5 | 174.0 | 9.6 | 807.3 |
| country_converter | *skipped (scope: supports ['country'], dataset has ['admin1', 'admin2', 'admin3'])* | — | — | — | — | — | — | — | — | — | — | — |
| countryguess | *skipped (scope: supports ['country'], dataset has ['admin1', 'admin2', 'admin3'])* | — | — | — | — | — | — | — | — | — | — | — |
| geonamescache | *skipped (scope: supports ['city', 'country'], dataset has ['admin1', 'admin2', 'admin3'])* | — | — | — | — | — | — | — | — | — | — | — |
| hdx_python_country | *skipped (scope: supports ['country'], dataset has ['admin1', 'admin2', 'admin3'])* | — | — | — | — | — | — | — | — | — | — | — |
| pycountry | *skipped (scope: supports ['country'], dataset has ['admin1', 'admin2', 'admin3'])* | — | — | — | — | — | — | — | — | — | — | — |
| rapidfuzz_dict | *skipped (scope: supports ['country'], dataset has ['admin1', 'admin2', 'admin3'])* | — | — | — | — | — | — | — | — | — | — | — |

#### recall metrics

| tool | abst R | amb recall |
|---|---|---|
| data_commons_resolve | 0.000 | 0.000 |
| resolvekit | 0.000 | 0.000 |
| resolvekit_typed | 0.000 | 0.000 |

#### per-capability accuracy

| tool | alias | typo |
|---|---|---|
| data_commons_resolve | 0.725 | 0.419 |
| resolvekit | 0.934 | 0.926 |
| resolvekit_typed | 0.934 | 0.972 |

#### per-entity-type accuracy

| tool | admin1 | admin2 | admin3 |
|---|---|---|---|
| data_commons_resolve | 0.652 (n=781) | 0.564 (n=1,264) | — |
| resolvekit | 0.957 (n=791) | 0.921 (n=1,278) | 0.930 (n=488) |
| resolvekit_typed | 0.980 (n=791) | 0.973 (n=1,278) | 0.986 (n=488) |

### geo_cities

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| data_commons_resolve | 2.1.6 | 0.502 | [0.48, 0.52] | 100.0% | 0.198 | 0.000 | 0.1 | 0.2 | 9588.7 | 125.9 | 0.3 | — |
| geonamescache | 3.0.1 | 0.000 | [0.00, 0.00] | 100.0% | 0.154 | 0.000 | 68.8 | 73.2 | 14.3 | 190.8 | 164.7 | — |
| resolvekit | 0.1.2 | 0.858 | [0.84, 0.87] | 100.0% | 0.011 | 0.000 | 0.6 | 2.4 | 1129.8 | 1139.5 | 9.6 | 807.3 |
| resolvekit_typed | 0.1.2 | 0.862 | [0.85, 0.88] | 100.0% | 0.005 | 0.000 | 0.5 | 2.6 | 1213.6 | 174.0 | 9.6 | 807.3 |
| country_converter | *skipped (scope: supports ['country'], dataset has ['city'])* | — | — | — | — | — | — | — | — | — | — | — |
| countryguess | *skipped (scope: supports ['country'], dataset has ['city'])* | — | — | — | — | — | — | — | — | — | — | — |
| hdx_python_country | *skipped (scope: supports ['country'], dataset has ['city'])* | — | — | — | — | — | — | — | — | — | — | — |
| pycountry | *skipped (scope: supports ['country'], dataset has ['city'])* | — | — | — | — | — | — | — | — | — | — | — |
| rapidfuzz_dict | *skipped (scope: supports ['country'], dataset has ['city'])* | — | — | — | — | — | — | — | — | — | — | — |

#### recall metrics

| tool | abst R | amb recall |
|---|---|---|
| data_commons_resolve | 0.000 | 0.000 |
| geonamescache | 0.000 | 0.000 |
| resolvekit | 0.000 | 0.000 |
| resolvekit_typed | 0.000 | 0.000 |

#### per-capability accuracy

| tool | alias | typo |
|---|---|---|
| data_commons_resolve | 0.787 | 0.201 |
| geonamescache | 0.000 | 0.000 |
| resolvekit | 0.985 | 0.833 |
| resolvekit_typed | 0.985 | 0.837 |

#### per-entity-type accuracy

| tool | city |
|---|---|
| data_commons_resolve | 0.502 (n=2,048) |
| geonamescache | 0.000 (n=2,048) |
| resolvekit | 0.858 (n=2,048) |
| resolvekit_typed | 0.862 (n=2,048) |

### geo_countries_en

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| country_converter | 1.3.2 | 0.566 | [0.55, 0.58] | 100.0% | 0.025 | 0.000 | 0.1 | 0.2 | 7522.0 | 115.6 | 0.1 | — |
| countryguess | 0.4.9 | 0.675 | [0.66, 0.69] | 100.0% | 0.038 | 0.000 | 0.1 | 0.3 | 9143.1 | 113.3 | 0.3 | — |
| data_commons_resolve | 2.1.6 | 0.625 | [0.61, 0.64] | 100.0% | 0.047 | 0.000 | 0.1 | 0.2 | 8118.0 | 125.9 | 0.3 | — |
| geonamescache | 3.0.1 | 0.057 | [0.05, 0.07] | 100.0% | 0.000 | 0.000 | 0.0 | 0.0 | 1290117.3 | 190.8 | 164.7 | — |
| hdx_python_country | 4.1.1 | 0.642 | [0.63, 0.66] | 100.0% | 0.042 | 0.000 | 0.1 | 5.8 | 493.3 | 177.3 | 0.2 | — |
| pycountry | 26.2.16 | 0.099 | [0.09, 0.11] | 100.0% | 0.001 | 0.000 | 0.0 | 0.0 | 296705.5 | 112.6 | 20.1 | — |
| rapidfuzz_dict | 3.14.5 | 0.469 | [0.45, 0.48] | 100.0% | 0.507 | 0.000 | 0.3 | 0.6 | 2989.6 | 112.9 | 4.1 | — |
| resolvekit | 0.1.2 | 0.803 | [0.79, 0.82] | 100.0% | 0.038 | 0.000 | 0.8 | 2.9 | 942.2 | 1139.5 | 9.6 | 807.3 |
| resolvekit_typed | 0.1.2 | 0.801 | [0.79, 0.81] | 100.0% | 0.012 | 0.000 | 0.4 | 1.4 | 1893.9 | 174.0 | 9.6 | 807.3 |

#### recall metrics

| tool | abst R | amb recall |
|---|---|---|
| country_converter | 0.000 | 0.000 |
| countryguess | 0.000 | 0.000 |
| data_commons_resolve | 0.000 | 0.000 |
| geonamescache | 0.000 | 0.000 |
| hdx_python_country | 0.000 | 0.000 |
| pycountry | 0.000 | 0.000 |
| rapidfuzz_dict | 0.000 | 0.000 |
| resolvekit | 0.000 | 0.000 |
| resolvekit_typed | 0.000 | 0.000 |

#### per-capability accuracy

| tool | alias | case_noise | prefix_truncation | typo | unicode_normalization |
|---|---|---|---|---|---|
| country_converter | 0.605 | 0.541 | 0.204 | 0.498 | 0.786 |
| countryguess | 0.669 | 0.654 | 0.355 | 0.650 | 0.823 |
| data_commons_resolve | 0.689 | 0.575 | 0.182 | 0.588 | 0.754 |
| geonamescache | 0.014 | 0.001 | 0.000 | 0.000 | 0.000 |
| hdx_python_country | 0.644 | 0.665 | 0.389 | 0.599 | 0.791 |
| pycountry | 0.195 | 0.012 | 0.000 | 0.009 | 0.000 |
| rapidfuzz_dict | 0.442 | 0.449 | 0.188 | 0.443 | 0.573 |
| resolvekit | 0.918 | 0.660 | 0.426 | 0.741 | 0.996 |
| resolvekit_typed | 0.901 | 0.671 | 0.466 | 0.746 | 0.985 |

#### per-entity-type accuracy

| tool | country |
|---|---|
| country_converter | 0.566 (n=4,055) |
| countryguess | 0.675 (n=4,055) |
| data_commons_resolve | 0.625 (n=4,055) |
| geonamescache | 0.057 (n=4,055) |
| hdx_python_country | 0.642 (n=4,055) |
| pycountry | 0.099 (n=4,055) |
| rapidfuzz_dict | 0.469 (n=4,055) |
| resolvekit | 0.803 (n=4,055) |
| resolvekit_typed | 0.801 (n=4,055) |

### geo_countries_multilingual

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| country_converter | 1.3.2 | 0.419 | [0.40, 0.44] | 100.0% | 0.025 | 0.000 | 0.1 | 0.2 | 9307.5 | 115.6 | 0.1 | — |
| countryguess | 0.4.9 | 0.512 | [0.49, 0.53] | 100.0% | 0.029 | 0.000 | 0.1 | 0.3 | 6813.4 | 113.3 | 0.3 | — |
| data_commons_resolve | 2.1.6 | 0.827 | [0.81, 0.84] | 100.0% | 0.029 | 0.000 | 0.1 | 0.2 | 8684.1 | 125.9 | 0.3 | — |
| geonamescache | 3.0.1 | 0.148 | [0.13, 0.16] | 100.0% | 0.002 | 0.000 | 0.0 | 0.0 | 1296806.2 | 190.8 | 164.7 | — |
| hdx_python_country | 4.1.1 | 0.565 | [0.54, 0.59] | 100.0% | 0.084 | 0.000 | 0.1 | 5.9 | 404.0 | 177.3 | 0.2 | — |
| pycountry | 26.2.16 | 0.143 | [0.13, 0.16] | 100.0% | 0.002 | 0.000 | 0.0 | 0.0 | 353970.1 | 112.6 | 20.1 | — |
| rapidfuzz_dict | 3.14.5 | 0.370 | [0.35, 0.39] | 100.0% | 0.495 | 0.000 | 0.3 | 0.7 | 2786.3 | 112.9 | 4.1 | — |
| resolvekit | 0.1.2 | 0.635 | [0.61, 0.65] | 100.0% | 0.025 | 0.000 | 0.5 | 2.2 | 1337.4 | 1139.5 | 9.6 | 807.3 |
| resolvekit_typed | 0.1.2 | 0.614 | [0.59, 0.63] | 100.0% | 0.007 | 0.000 | 0.3 | 1.3 | 2079.3 | 174.0 | 9.6 | 807.3 |

#### recall metrics

| tool | abst R | amb recall |
|---|---|---|
| country_converter | 0.000 | 0.000 |
| countryguess | 0.000 | 0.000 |
| data_commons_resolve | 0.000 | 0.000 |
| geonamescache | 0.000 | 0.000 |
| hdx_python_country | 0.000 | 0.000 |
| pycountry | 0.000 | 0.000 |
| rapidfuzz_dict | 0.000 | 0.000 |
| resolvekit | 0.000 | 0.000 |
| resolvekit_typed | 0.000 | 0.000 |

#### per-capability accuracy

| tool | alias | case_noise | multilingual |
|---|---|---|---|
| country_converter | 0.372 | 0.600 | 0.419 |
| countryguess | 0.425 | 0.800 | 0.511 |
| data_commons_resolve | 0.768 | 0.600 | 0.828 |
| geonamescache | 0.035 | 0.000 | 0.148 |
| hdx_python_country | 0.451 | 0.800 | 0.565 |
| pycountry | 0.036 | 0.400 | 0.142 |
| rapidfuzz_dict | 0.311 | 0.600 | 0.370 |
| resolvekit | 0.454 | 0.800 | 0.634 |
| resolvekit_typed | 0.446 | 0.800 | 0.613 |

#### per-entity-type accuracy

| tool | country |
|---|---|
| country_converter | 0.419 (n=2,140) |
| countryguess | 0.512 (n=2,140) |
| data_commons_resolve | 0.827 (n=2,140) |
| geonamescache | 0.148 (n=2,140) |
| hdx_python_country | 0.565 (n=2,140) |
| pycountry | 0.143 (n=2,140) |
| rapidfuzz_dict | 0.370 (n=2,140) |
| resolvekit | 0.635 (n=2,140) |
| resolvekit_typed | 0.614 (n=2,140) |

### no_match

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| country_converter | 1.3.2 | 1.000 | [0.90, 1.00] | 100.0% | 0.000 | 1.000 | 0.1 | 0.3 | 9410.0 | 115.6 | 0.1 | — |
| countryguess | 0.4.9 | 0.943 | [0.81, 0.98] | 100.0% | 0.057 | 1.000 | 0.2 | 0.2 | 6178.1 | 113.3 | 0.3 | — |
| data_commons_resolve | 2.1.6 | 0.971 | [0.85, 0.99] | 100.0% | 0.029 | 1.000 | 0.2 | 0.3 | 4424.4 | 125.9 | 0.3 | — |
| geonamescache | 3.0.1 | 1.000 | [0.90, 1.00] | 100.0% | 0.000 | 1.000 | 0.0 | 0.0 | 1383891.7 | 190.8 | 164.7 | — |
| hdx_python_country | 4.1.1 | 1.000 | [0.90, 1.00] | 100.0% | 0.000 | 1.000 | 5.2 | 5.4 | 273.6 | 177.3 | 0.2 | — |
| pycountry | 26.2.16 | 1.000 | [0.90, 1.00] | 100.0% | 0.000 | 1.000 | 0.0 | 0.0 | 381820.9 | 112.6 | 20.1 | — |
| rapidfuzz_dict | 3.14.5 | 0.200 | [0.10, 0.36] | 100.0% | 0.800 | 1.000 | 0.3 | 0.6 | 2574.4 | 112.9 | 4.1 | — |
| resolvekit | 0.1.2 | 0.771 | [0.61, 0.88] | 100.0% | 0.086 | 1.000 | 0.0 | 2.4 | 1910.6 | 1139.5 | 9.6 | 807.3 |
| resolvekit_typed | 0.1.2 | 0.914 | [0.78, 0.97] | 100.0% | 0.086 | 1.000 | 0.0 | 1.8 | 3084.4 | 174.0 | 9.6 | 807.3 |

#### recall metrics

| tool | abst R | amb recall |
|---|---|---|
| country_converter | 1.000 | 0.000 |
| countryguess | 0.943 | 0.000 |
| data_commons_resolve | 0.971 | 0.000 |
| geonamescache | 1.000 | 0.000 |
| hdx_python_country | 1.000 | 0.000 |
| pycountry | 1.000 | 0.000 |
| rapidfuzz_dict | 0.200 | 0.000 |
| resolvekit | 0.771 | 0.000 |
| resolvekit_typed | 0.914 | 0.000 |

#### per-capability accuracy

| tool | abstention |
|---|---|
| country_converter | 1.000 |
| countryguess | 0.943 |
| data_commons_resolve | 0.971 |
| geonamescache | 1.000 |
| hdx_python_country | 1.000 |
| pycountry | 1.000 |
| rapidfuzz_dict | 0.200 |
| resolvekit | 0.771 |
| resolvekit_typed | 0.914 |

#### per-entity-type accuracy

| tool | country |
|---|---|
| country_converter | 1.000 (n=35) |
| countryguess | 0.943 (n=35) |
| data_commons_resolve | 0.971 (n=35) |
| geonamescache | 1.000 (n=35) |
| hdx_python_country | 1.000 (n=35) |
| pycountry | 1.000 (n=35) |
| rapidfuzz_dict | 0.200 (n=35) |
| resolvekit | 0.771 (n=35) |
| resolvekit_typed | 0.914 (n=35) |

## Comparison by entity type

Each sub-table is scoped to a single dataset so comparisons are like-for-like. Cross-dataset roll-ups are omitted — datasets differ in difficulty.

### admin1

**ambiguous**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| data_commons_resolve | 0.833 | 6 | 0.000 |
| resolvekit | 0.667 | 6 | 0.000 |
| resolvekit_typed | 1.000 | 6 | 0.000 |

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| data_commons_resolve | 0.700 | 40 | 0.100 |
| resolvekit | 0.782 | 55 | 0.018 |
| resolvekit_typed | 0.818 | 55 | 0.018 |

**geo_admin**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| data_commons_resolve | 0.652 | 781 | 0.119 |
| resolvekit | 0.957 | 791 | 0.030 |
| resolvekit_typed | 0.980 | 791 | 0.000 |

### admin2

**ambiguous**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| data_commons_resolve | 0.900 | 10 | 0.000 |
| resolvekit | 0.700 | 10 | 0.000 |
| resolvekit_typed | 0.700 | 10 | 0.000 |

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| data_commons_resolve | 0.615 | 26 | 0.231 |
| resolvekit | 0.969 | 32 | 0.000 |
| resolvekit_typed | 0.938 | 32 | 0.000 |

**geo_admin**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| data_commons_resolve | 0.564 | 1,264 | 0.163 |
| resolvekit | 0.921 | 1,278 | 0.049 |
| resolvekit_typed | 0.973 | 1,278 | 0.002 |

### admin3

**ambiguous**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 1.000 | 2 | 0.000 |
| resolvekit_typed | 1.000 | 2 | 0.000 |

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.818 | 33 | 0.091 |
| resolvekit_typed | 0.848 | 33 | 0.000 |

**geo_admin**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.930 | 488 | 0.047 |
| resolvekit_typed | 0.986 | 488 | 0.002 |

### admin4

**ambiguous**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 1.000 | 1 | 0.000 |
| resolvekit_typed | 1.000 | 1 | 0.000 |

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.875 | 32 | 0.062 |
| resolvekit_typed | 0.938 | 32 | 0.000 |

### admin5

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.886 | 35 | 0.086 |
| resolvekit_typed | 0.971 | 35 | 0.000 |

### city

**ambiguous**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| data_commons_resolve | 1.000 | 6 | 0.000 |
| geonamescache | 0.000 | 6 | 1.000 |
| resolvekit | 0.833 | 6 | 0.000 |
| resolvekit_typed | 0.833 | 6 | 0.000 |

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| data_commons_resolve | 0.794 | 68 | 0.059 |
| geonamescache | 0.000 | 44 | 0.727 |
| resolvekit | 0.889 | 72 | 0.083 |
| resolvekit_typed | 0.889 | 72 | 0.069 |

**geo_cities**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| data_commons_resolve | 0.502 | 2,048 | 0.198 |
| geonamescache | 0.000 | 2,048 | 0.154 |
| resolvekit | 0.858 | 2,048 | 0.011 |
| resolvekit_typed | 0.862 | 2,048 | 0.005 |

### continent

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 1.000 | 7 | 0.000 |
| resolvekit_typed | 1.000 | 7 | 0.000 |

### continental_union

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 1.000 | 9 | 0.000 |
| resolvekit_typed | 1.000 | 9 | 0.000 |

### country

**ambiguous**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| country_converter | 0.913 | 23 | 0.000 |
| countryguess | 0.957 | 23 | 0.000 |
| data_commons_resolve | 0.909 | 22 | 0.045 |
| geonamescache | 0.682 | 22 | 0.000 |
| hdx_python_country | 1.000 | 23 | 0.000 |
| pycountry | 0.652 | 23 | 0.000 |
| rapidfuzz_dict | 0.783 | 23 | 0.217 |
| resolvekit | 1.000 | 22 | 0.000 |
| resolvekit_typed | 1.000 | 22 | 0.000 |

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| country_converter | 0.700 | 10 | 0.000 |
| countryguess | 0.800 | 10 | 0.100 |
| data_commons_resolve | 0.822 | 73 | 0.068 |
| geonamescache | 0.500 | 56 | 0.018 |
| hdx_python_country | 0.800 | 10 | 0.000 |
| pycountry | 0.500 | 10 | 0.000 |
| rapidfuzz_dict | 0.600 | 10 | 0.400 |
| resolvekit | 0.964 | 83 | 0.000 |
| resolvekit_typed | 0.952 | 83 | 0.036 |

**geo_countries_en**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| country_converter | 0.566 | 4,055 | 0.025 |
| countryguess | 0.675 | 4,055 | 0.038 |
| data_commons_resolve | 0.625 | 4,055 | 0.047 |
| geonamescache | 0.057 | 4,055 | 0.000 |
| hdx_python_country | 0.642 | 4,055 | 0.042 |
| pycountry | 0.099 | 4,055 | 0.001 |
| rapidfuzz_dict | 0.469 | 4,055 | 0.507 |
| resolvekit | 0.803 | 4,055 | 0.038 |
| resolvekit_typed | 0.801 | 4,055 | 0.012 |

**geo_countries_multilingual**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| country_converter | 0.419 | 2,140 | 0.025 |
| countryguess | 0.512 | 2,140 | 0.029 |
| data_commons_resolve | 0.827 | 2,140 | 0.029 |
| geonamescache | 0.148 | 2,140 | 0.002 |
| hdx_python_country | 0.565 | 2,140 | 0.084 |
| pycountry | 0.143 | 2,140 | 0.002 |
| rapidfuzz_dict | 0.370 | 2,140 | 0.495 |
| resolvekit | 0.635 | 2,140 | 0.025 |
| resolvekit_typed | 0.614 | 2,140 | 0.007 |

**no_match**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| country_converter | 1.000 | 35 | 0.000 |
| countryguess | 0.943 | 35 | 0.057 |
| data_commons_resolve | 0.971 | 35 | 0.029 |
| geonamescache | 1.000 | 35 | 0.000 |
| hdx_python_country | 1.000 | 35 | 0.000 |
| pycountry | 1.000 | 35 | 0.000 |
| rapidfuzz_dict | 0.200 | 35 | 0.800 |
| resolvekit | 0.771 | 35 | 0.086 |
| resolvekit_typed | 0.914 | 35 | 0.086 |

### org

**eval_org**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.750 | 20 | 0.100 |
| resolvekit_typed | 0.750 | 20 | 0.100 |

### world_region

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.556 | 9 | 0.444 |
| resolvekit_typed | 1.000 | 9 | 0.000 |

## Calibration

### resolvekit on eval_geo

ECE: 0.030. Brier: 0.071. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 3 | 0.780 | 0.667 |
| [0.8, 0.9) | 118 | 0.873 | 0.915 |
| [0.9, 1.0) | 126 | 0.920 | 0.937 |

### resolvekit on geo_admin

ECE: 0.098. Brier: 0.056. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 0 | 0.000 | 0.000 |
| [0.8, 0.9) | 1,981 | 0.877 | 0.964 |
| [0.9, 1.0) | 95 | 0.914 | 0.600 |

### resolvekit on geo_cities

ECE: 0.100. Brier: 0.031. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 1 | 0.700 | 0.000 |
| [0.8, 0.9) | 944 | 0.877 | 0.987 |
| [0.9, 1.0) | 98 | 0.906 | 0.908 |

### resolvekit on geo_countries_en

ECE: 0.063. Brier: 0.047. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 245 | 0.762 | 0.935 |
| [0.8, 0.9) | 803 | 0.863 | 0.857 |
| [0.9, 1.0) | 2,235 | 0.919 | 0.990 |

### resolvekit on geo_countries_multilingual

ECE: 0.072. Brier: 0.036. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 32 | 0.752 | 0.719 |
| [0.8, 0.9) | 168 | 0.877 | 0.798 |
| [0.9, 1.0) | 1,182 | 0.920 | 0.992 |

### resolvekit_typed on ambiguous

ECE: 0.088. Brier: 0.008. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 0 | 0.000 | 0.000 |
| [0.8, 0.9) | 8 | 0.883 | 1.000 |
| [0.9, 1.0) | 23 | 0.922 | 1.000 |

### resolvekit_typed on eval_geo

ECE: 0.070. Brier: 0.038. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 5 | 0.781 | 0.800 |
| [0.8, 0.9) | 125 | 0.874 | 0.976 |
| [0.9, 1.0) | 147 | 0.921 | 0.966 |

### resolvekit_typed on geo_admin

ECE: 0.121. Brier: 0.016. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 0 | 0.000 | 0.000 |
| [0.8, 0.9) | 2,086 | 0.877 | 0.999 |
| [0.9, 1.0) | 82 | 0.912 | 1.000 |

### resolvekit_typed on geo_cities

ECE: 0.110. Brier: 0.023. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 0 | 0.000 | 0.000 |
| [0.8, 0.9) | 944 | 0.877 | 0.988 |
| [0.9, 1.0) | 89 | 0.906 | 1.000 |

### resolvekit_typed on geo_countries_en

ECE: 0.092. Brier: 0.025. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 276 | 0.759 | 0.953 |
| [0.8, 0.9) | 722 | 0.862 | 0.985 |
| [0.9, 1.0) | 2,245 | 0.920 | 0.989 |

### resolvekit_typed on geo_countries_multilingual

ECE: 0.077. Brier: 0.016. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 26 | 0.752 | 0.885 |
| [0.8, 0.9) | 136 | 0.881 | 0.949 |
| [0.9, 1.0) | 1,151 | 0.920 | 0.997 |

## Caveats

- country_converter on eval_org: scope: supports ['country'], dataset has ['org']
- countryguess on eval_org: scope: supports ['country'], dataset has ['org']
- geonamescache on eval_org: scope: supports ['city', 'country'], dataset has ['org']
- hdx_python_country on eval_org: scope: supports ['country'], dataset has ['org']
- pycountry on eval_org: scope: supports ['country'], dataset has ['org']
- rapidfuzz_dict on eval_org: scope: supports ['country'], dataset has ['org']
- country_converter on geo_admin: scope: supports ['country'], dataset has ['admin1', 'admin2', 'admin3']
- countryguess on geo_admin: scope: supports ['country'], dataset has ['admin1', 'admin2', 'admin3']
- geonamescache on geo_admin: scope: supports ['city', 'country'], dataset has ['admin1', 'admin2', 'admin3']
- hdx_python_country on geo_admin: scope: supports ['country'], dataset has ['admin1', 'admin2', 'admin3']
- pycountry on geo_admin: scope: supports ['country'], dataset has ['admin1', 'admin2', 'admin3']
- rapidfuzz_dict on geo_admin: scope: supports ['country'], dataset has ['admin1', 'admin2', 'admin3']
- country_converter on geo_cities: scope: supports ['country'], dataset has ['city']
- countryguess on geo_cities: scope: supports ['country'], dataset has ['city']
- hdx_python_country on geo_cities: scope: supports ['country'], dataset has ['city']
- pycountry on geo_cities: scope: supports ['country'], dataset has ['city']
- rapidfuzz_dict on geo_cities: scope: supports ['country'], dataset has ['city']
