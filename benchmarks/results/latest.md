# resolvekit benchmark — 2026-06-12

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
| country_converter | 1.3.2 | 0.913 | [0.73, 0.98] | 48.3% | 0.000 | 0.000 | 0.1 | 0.1 | 8776.8 | 117.7 | 0.1 | — |
| countryguess | 0.4.9 | 0.957 | [0.79, 0.99] | 48.3% | 0.000 | 0.000 | 0.0 | 0.1 | 31285.5 | 113.8 | 0.3 | — |
| data_commons_resolve | 2.1.6 | 0.909 | [0.79, 0.96] | 93.1% | 0.023 | 0.000 | 0.1 | 0.3 | 6844.3 | 126.2 | 0.3 | — |
| geonamescache | 3.0.1 | 0.536 | [0.36, 0.70] | 60.3% | 0.214 | 0.000 | 0.0 | 73.8 | 63.8 | 191.2 | 164.7 | — |
| hdx_python_country | 4.1.1 | 1.000 | [0.86, 1.00] | 48.3% | 0.000 | 0.000 | 0.0 | 5.1 | 1970.4 | 177.8 | 0.2 | — |
| pycountry | 26.2.16 | 0.652 | [0.45, 0.81] | 48.3% | 0.000 | 0.000 | 0.0 | 0.0 | 406784.5 | 112.9 | 20.1 | — |
| rapidfuzz_dict | 3.14.5 | 0.783 | [0.58, 0.90] | 48.3% | 0.217 | 0.000 | 0.2 | 0.4 | 4723.0 | 113.3 | 4.1 | — |
| resolvekit | 0.1.3 | 0.851 | [0.72, 0.93] | 100.0% | 0.021 | 0.000 | 2.9 | 5.0 | 348.4 | 1633.5 | 9.5 | 806.6 |
| resolvekit_typed | 0.1.3 | 0.915 | [0.80, 0.97] | 100.0% | 0.000 | 0.000 | 2.1 | 4.1 | 127.9 | 239.7 | 9.5 | 806.6 |

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
| resolvekit | 0.000 | 0.851 |
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
| resolvekit | 0.786 | 0.851 |
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
| resolvekit | 0.667 (n=6) | 0.700 (n=10) | 0.500 (n=2) | 1.000 (n=1) | 0.833 (n=6) | 1.000 (n=22) |
| resolvekit_typed | 1.000 (n=6) | 0.700 (n=10) | 1.000 (n=2) | 1.000 (n=1) | 0.833 (n=6) | 1.000 (n=22) |

### eval_geo

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| country_converter | 1.3.2 | 0.700 | [0.40, 0.89] | 23.6% | 0.000 | 0.250 | 0.1 | n/a | 9989.2 | 117.7 | 0.1 | — |
| countryguess | 0.4.9 | 0.800 | [0.49, 0.94] | 23.6% | 0.100 | 0.500 | 0.0 | n/a | 10736.8 | 113.8 | 0.3 | — |
| data_commons_resolve | 2.1.6 | 0.763 | [0.70, 0.82] | 65.7% | 0.092 | 0.281 | 0.1 | 0.2 | 8804.7 | 126.2 | 0.3 | — |
| geonamescache | 3.0.1 | 0.280 | [0.20, 0.37] | 42.8% | 0.330 | 0.188 | 0.0 | 77.9 | 31.0 | 191.2 | 164.7 | — |
| hdx_python_country | 4.1.1 | 0.800 | [0.49, 0.94] | 23.6% | 0.000 | 0.333 | 0.1 | n/a | 438.6 | 177.8 | 0.2 | — |
| pycountry | 26.2.16 | 0.500 | [0.24, 0.76] | 23.6% | 0.000 | 0.167 | 0.0 | n/a | 427040.2 | 112.9 | 20.1 | — |
| rapidfuzz_dict | 3.14.5 | 0.600 | [0.31, 0.83] | 23.6% | 0.400 | 0.000 | 0.2 | n/a | 4301.7 | 113.3 | 4.1 | — |
| resolvekit | 0.1.3 | 0.861 | [0.82, 0.89] | 100.0% | 0.060 | 0.424 | 1.3 | 10.0 | 351.5 | 1633.5 | 9.5 | 806.6 |
| resolvekit_typed | 0.1.3 | 0.888 | [0.85, 0.92] | 100.0% | 0.035 | 0.355 | 0.4 | 2.7 | 1234.5 | 239.7 | 9.5 | 806.6 |

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
| resolvekit | 0.824 | 0.882 |
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
| resolvekit | 0.906 | 0.941 | 0.875 | 0.833 |
| resolvekit_typed | 0.938 | 0.941 | 0.875 | 0.833 |

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
| resolvekit | 0.709 (n=55) | 0.938 (n=32) | 0.909 (n=33) | 0.844 (n=32) | 0.743 (n=35) | 0.875 (n=72) | 1.000 (n=7) | 1.000 (n=9) | 0.964 (n=83) | 0.556 (n=9) |
| resolvekit_typed | 0.818 (n=55) | 0.938 (n=32) | 0.848 (n=33) | 0.875 (n=32) | 0.800 (n=35) | 0.875 (n=72) | 1.000 (n=7) | 1.000 (n=9) | 0.952 (n=83) | 1.000 (n=9) |

### eval_org

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| resolvekit | 0.1.3 | 0.750 | [0.53, 0.89] | 100.0% | 0.150 | 1.000 | 1.7 | 10.8 | 282.4 | 1633.5 | 9.5 | 806.6 |
| resolvekit_typed | 0.1.3 | 0.750 | [0.53, 0.89] | 100.0% | 0.150 | 1.000 | 0.9 | 3.5 | 723.1 | 239.7 | 9.5 | 806.6 |
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
| data_commons_resolve | 2.1.6 | 0.598 | [0.58, 0.62] | 80.7% | 0.146 | 0.000 | 0.1 | 0.3 | 6296.0 | 126.2 | 0.3 | — |
| resolvekit | 0.1.3 | 0.863 | [0.85, 0.88] | 100.0% | 0.078 | 0.000 | 0.7 | 4.3 | 685.8 | 1633.5 | 9.5 | 806.6 |
| resolvekit_typed | 0.1.3 | 0.930 | [0.92, 0.94] | 100.0% | 0.017 | 0.000 | 0.4 | 2.7 | 1248.7 | 239.7 | 9.5 | 806.6 |
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
| resolvekit | 0.492 | 0.863 |
| resolvekit_typed | 0.516 | 0.940 |

#### per-entity-type accuracy

| tool | admin1 | admin2 | admin3 |
|---|---|---|---|
| data_commons_resolve | 0.652 (n=781) | 0.564 (n=1,264) | — |
| resolvekit | 0.886 (n=791) | 0.835 (n=1,278) | 0.900 (n=488) |
| resolvekit_typed | 0.943 (n=791) | 0.923 (n=1,278) | 0.924 (n=488) |

### geo_cities

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| data_commons_resolve | 2.1.6 | 0.502 | [0.48, 0.52] | 100.0% | 0.198 | 0.000 | 0.1 | 0.3 | 6246.7 | 126.2 | 0.3 | — |
| geonamescache | 3.0.1 | 0.000 | [0.00, 0.00] | 100.0% | 0.154 | 0.000 | 72.7 | 86.2 | 13.4 | 191.2 | 164.7 | — |
| resolvekit | 0.1.3 | 0.740 | [0.72, 0.76] | 100.0% | 0.118 | 0.000 | 0.9 | 3.9 | 758.5 | 1633.5 | 9.5 | 806.6 |
| resolvekit_typed | 0.1.3 | 0.739 | [0.72, 0.76] | 100.0% | 0.116 | 0.000 | 0.7 | 3.7 | 902.3 | 239.7 | 9.5 | 806.6 |
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
| resolvekit | 0.618 | 0.726 |
| resolvekit_typed | 0.618 | 0.720 |

#### per-entity-type accuracy

| tool | city |
|---|---|
| data_commons_resolve | 0.502 (n=2,048) |
| geonamescache | 0.000 (n=2,048) |
| resolvekit | 0.740 (n=2,048) |
| resolvekit_typed | 0.739 (n=2,048) |

### geo_countries_en

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| country_converter | 1.3.2 | 0.566 | [0.55, 0.58] | 100.0% | 0.025 | 0.000 | 0.1 | 0.3 | 7095.9 | 117.7 | 0.1 | — |
| countryguess | 0.4.9 | 0.675 | [0.66, 0.69] | 100.0% | 0.038 | 0.000 | 0.1 | 0.3 | 8820.4 | 113.8 | 0.3 | — |
| data_commons_resolve | 2.1.6 | 0.625 | [0.61, 0.64] | 100.0% | 0.047 | 0.000 | 0.1 | 0.2 | 8275.1 | 126.2 | 0.3 | — |
| geonamescache | 3.0.1 | 0.057 | [0.05, 0.07] | 100.0% | 0.000 | 0.000 | 0.0 | 0.0 | 1202847.6 | 191.2 | 164.7 | — |
| hdx_python_country | 4.1.1 | 0.642 | [0.63, 0.66] | 100.0% | 0.042 | 0.000 | 0.1 | 6.1 | 470.2 | 177.8 | 0.2 | — |
| pycountry | 26.2.16 | 0.099 | [0.09, 0.11] | 100.0% | 0.001 | 0.000 | 0.0 | 0.0 | 362236.9 | 112.9 | 20.1 | — |
| rapidfuzz_dict | 3.14.5 | 0.469 | [0.45, 0.48] | 100.0% | 0.507 | 0.000 | 0.3 | 0.6 | 2804.7 | 113.3 | 4.1 | — |
| resolvekit | 0.1.3 | 0.831 | [0.82, 0.84] | 100.0% | 0.038 | 0.000 | 1.0 | 5.8 | 585.8 | 1633.5 | 9.5 | 806.6 |
| resolvekit_typed | 0.1.3 | 0.825 | [0.81, 0.84] | 100.0% | 0.013 | 0.000 | 0.4 | 2.2 | 1349.6 | 239.7 | 9.5 | 806.6 |

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
| resolvekit | 0.966 | 0.692 | 0.491 | 0.765 | 0.991 |
| resolvekit_typed | 0.909 | 0.705 | 0.574 | 0.772 | 0.985 |

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
| resolvekit | 0.831 (n=4,055) |
| resolvekit_typed | 0.825 (n=4,055) |

### geo_countries_multilingual

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| country_converter | 1.3.2 | 0.419 | [0.40, 0.44] | 100.0% | 0.025 | 0.000 | 0.1 | 0.2 | 8962.1 | 117.7 | 0.1 | — |
| countryguess | 0.4.9 | 0.512 | [0.49, 0.53] | 100.0% | 0.029 | 0.000 | 0.1 | 0.4 | 6439.7 | 113.8 | 0.3 | — |
| data_commons_resolve | 2.1.6 | 0.827 | [0.81, 0.84] | 100.0% | 0.029 | 0.000 | 0.1 | 0.2 | 8135.4 | 126.2 | 0.3 | — |
| geonamescache | 3.0.1 | 0.148 | [0.13, 0.16] | 100.0% | 0.002 | 0.000 | 0.0 | 0.0 | 1179768.0 | 191.2 | 164.7 | — |
| hdx_python_country | 4.1.1 | 0.565 | [0.54, 0.59] | 100.0% | 0.084 | 0.000 | 0.1 | 6.0 | 399.3 | 177.8 | 0.2 | — |
| pycountry | 26.2.16 | 0.143 | [0.13, 0.16] | 100.0% | 0.002 | 0.000 | 0.0 | 0.0 | 382567.0 | 112.9 | 20.1 | — |
| rapidfuzz_dict | 3.14.5 | 0.370 | [0.35, 0.39] | 100.0% | 0.495 | 0.000 | 0.4 | 0.7 | 2639.2 | 113.3 | 4.1 | — |
| resolvekit | 0.1.3 | 0.648 | [0.63, 0.67] | 100.0% | 0.028 | 0.000 | 0.6 | 2.6 | 1065.5 | 1633.5 | 9.5 | 806.6 |
| resolvekit_typed | 0.1.3 | 0.627 | [0.61, 0.65] | 100.0% | 0.009 | 0.000 | 0.4 | 1.7 | 1648.3 | 239.7 | 9.5 | 806.6 |

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
| resolvekit | 0.476 | 0.800 | 0.648 |
| resolvekit_typed | 0.466 | 0.800 | 0.627 |

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
| resolvekit | 0.648 (n=2,140) |
| resolvekit_typed | 0.627 (n=2,140) |

### no_match

_resolvekit_typed passes entity_type + language hints from the dataset; scores reflect a caller with structured input available._

| tool | version | accuracy | acc CI | coverage | wrong-match | abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| country_converter | 1.3.2 | 1.000 | [0.90, 1.00] | 100.0% | 0.000 | 1.000 | 0.1 | 0.4 | 7606.6 | 117.7 | 0.1 | — |
| countryguess | 0.4.9 | 0.943 | [0.81, 0.98] | 100.0% | 0.057 | 1.000 | 0.2 | 0.3 | 5954.1 | 113.8 | 0.3 | — |
| data_commons_resolve | 2.1.6 | 0.971 | [0.85, 0.99] | 100.0% | 0.029 | 1.000 | 0.2 | 0.4 | 4303.7 | 126.2 | 0.3 | — |
| geonamescache | 3.0.1 | 1.000 | [0.90, 1.00] | 100.0% | 0.000 | 1.000 | 0.0 | 0.0 | 1310468.6 | 191.2 | 164.7 | — |
| hdx_python_country | 4.1.1 | 1.000 | [0.90, 1.00] | 100.0% | 0.000 | 1.000 | 5.4 | 5.8 | 261.0 | 177.8 | 0.2 | — |
| pycountry | 26.2.16 | 1.000 | [0.90, 1.00] | 100.0% | 0.000 | 1.000 | 0.0 | 0.0 | 412575.3 | 112.9 | 20.1 | — |
| rapidfuzz_dict | 3.14.5 | 0.200 | [0.10, 0.36] | 100.0% | 0.800 | 1.000 | 0.4 | 0.7 | 2439.3 | 113.3 | 4.1 | — |
| resolvekit | 0.1.3 | 0.771 | [0.61, 0.88] | 100.0% | 0.114 | 1.000 | 0.0 | 12.3 | 420.6 | 1633.5 | 9.5 | 806.6 |
| resolvekit_typed | 0.1.3 | 0.886 | [0.74, 0.95] | 100.0% | 0.114 | 1.000 | 0.0 | 2.1 | 33.9 | 239.7 | 9.5 | 806.6 |

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
| resolvekit_typed | 0.886 | 0.000 |

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
| resolvekit_typed | 0.886 |

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
| resolvekit_typed | 0.886 (n=35) |

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
| resolvekit | 0.709 | 55 | 0.091 |
| resolvekit_typed | 0.818 | 55 | 0.036 |

**geo_admin**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| data_commons_resolve | 0.652 | 781 | 0.119 |
| resolvekit | 0.886 | 791 | 0.068 |
| resolvekit_typed | 0.943 | 791 | 0.004 |

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
| resolvekit | 0.938 | 32 | 0.031 |
| resolvekit_typed | 0.938 | 32 | 0.000 |

**geo_admin**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| data_commons_resolve | 0.564 | 1,264 | 0.163 |
| resolvekit | 0.835 | 1,278 | 0.092 |
| resolvekit_typed | 0.923 | 1,278 | 0.016 |

### admin3

**ambiguous**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.500 | 2 | 0.500 |
| resolvekit_typed | 1.000 | 2 | 0.000 |

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.909 | 33 | 0.000 |
| resolvekit_typed | 0.848 | 33 | 0.000 |

**geo_admin**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.900 | 488 | 0.057 |
| resolvekit_typed | 0.924 | 488 | 0.039 |

### admin4

**ambiguous**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 1.000 | 1 | 0.000 |
| resolvekit_typed | 1.000 | 1 | 0.000 |

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.844 | 32 | 0.094 |
| resolvekit_typed | 0.875 | 32 | 0.031 |

### admin5

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.743 | 35 | 0.057 |
| resolvekit_typed | 0.800 | 35 | 0.000 |

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
| resolvekit | 0.875 | 72 | 0.097 |
| resolvekit_typed | 0.875 | 72 | 0.097 |

**geo_cities**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| data_commons_resolve | 0.502 | 2,048 | 0.198 |
| geonamescache | 0.000 | 2,048 | 0.154 |
| resolvekit | 0.740 | 2,048 | 0.118 |
| resolvekit_typed | 0.739 | 2,048 | 0.116 |

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
| resolvekit | 0.831 | 4,055 | 0.038 |
| resolvekit_typed | 0.825 | 4,055 | 0.013 |

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
| resolvekit | 0.648 | 2,140 | 0.028 |
| resolvekit_typed | 0.627 | 2,140 | 0.009 |

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
| resolvekit | 0.771 | 35 | 0.114 |
| resolvekit_typed | 0.886 | 35 | 0.114 |

### org

**eval_org**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.750 | 20 | 0.150 |
| resolvekit_typed | 0.750 | 20 | 0.150 |

### world_region

**eval_geo**

| tool | accuracy | n | wrong-match |
|---|---|---|---|
| resolvekit | 0.556 | 9 | 0.444 |
| resolvekit_typed | 1.000 | 9 | 0.000 |

## Calibration

### resolvekit on ambiguous

ECE: 0.031. Brier: 0.048. Reliability diagram data:

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
| [0.8, 0.9) | 0 | 0.000 | 0.000 |
| [0.9, 1.0) | 21 | 0.922 | 0.952 |

### resolvekit on eval_geo

ECE: 0.037. Brier: 0.075. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 1 | 0.791 | 0.000 |
| [0.8, 0.9) | 148 | 0.862 | 0.926 |
| [0.9, 1.0) | 126 | 0.921 | 0.921 |

### resolvekit on geo_admin

ECE: 0.092. Brier: 0.097. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 7 | 0.755 | 0.857 |
| [0.8, 0.9) | 1,912 | 0.854 | 0.927 |
| [0.9, 1.0) | 116 | 0.914 | 0.500 |

### resolvekit on geo_cities

ECE: 0.055. Brier: 0.170. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 5 | 0.748 | 0.000 |
| [0.8, 0.9) | 1,158 | 0.856 | 0.858 |
| [0.9, 1.0) | 93 | 0.908 | 0.226 |

### resolvekit on geo_countries_en

ECE: 0.059. Brier: 0.045. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 110 | 0.771 | 0.836 |
| [0.8, 0.9) | 1,157 | 0.866 | 0.899 |
| [0.9, 1.0) | 2,116 | 0.917 | 0.991 |

### resolvekit on geo_countries_multilingual

ECE: 0.067. Brier: 0.040. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 19 | 0.764 | 0.474 |
| [0.8, 0.9) | 301 | 0.876 | 0.857 |
| [0.9, 1.0) | 1,089 | 0.918 | 0.994 |

### resolvekit_typed on ambiguous

ECE: 0.092. Brier: 0.009. Reliability diagram data:

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
| [0.8, 0.9) | 5 | 0.855 | 1.000 |
| [0.9, 1.0) | 24 | 0.919 | 1.000 |

### resolvekit_typed on eval_geo

ECE: 0.069. Brier: 0.049. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 4 | 0.763 | 1.000 |
| [0.8, 0.9) | 156 | 0.860 | 0.968 |
| [0.9, 1.0) | 135 | 0.922 | 0.941 |

### resolvekit_typed on geo_admin

ECE: 0.133. Brier: 0.037. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 7 | 0.760 | 0.857 |
| [0.8, 0.9) | 2,022 | 0.852 | 0.987 |
| [0.9, 1.0) | 83 | 0.912 | 0.807 |

### resolvekit_typed on geo_cities

ECE: 0.050. Brier: 0.167. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 4 | 0.760 | 0.000 |
| [0.8, 0.9) | 1,169 | 0.857 | 0.857 |
| [0.9, 1.0) | 88 | 0.908 | 0.239 |

### resolvekit_typed on geo_countries_en

ECE: 0.089. Brier: 0.024. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 129 | 0.769 | 0.938 |
| [0.8, 0.9) | 1,079 | 0.865 | 0.980 |
| [0.9, 1.0) | 2,109 | 0.918 | 0.989 |

### resolvekit_typed on geo_countries_multilingual

ECE: 0.079. Brier: 0.019. Reliability diagram data:

| bin | count | mean conf | observed acc |
|---|---|---|---|
| [0.0, 0.1) | 0 | 0.000 | 0.000 |
| [0.1, 0.2) | 0 | 0.000 | 0.000 |
| [0.2, 0.3) | 0 | 0.000 | 0.000 |
| [0.3, 0.4) | 0 | 0.000 | 0.000 |
| [0.4, 0.5) | 0 | 0.000 | 0.000 |
| [0.5, 0.6) | 0 | 0.000 | 0.000 |
| [0.6, 0.7) | 0 | 0.000 | 0.000 |
| [0.7, 0.8) | 25 | 0.755 | 0.760 |
| [0.8, 0.9) | 252 | 0.875 | 0.964 |
| [0.9, 1.0) | 1,063 | 0.918 | 0.996 |

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
