"""Wikidata source — direct SPARQL fetchers used by the builder pipeline.

Distinct from :mod:`resolvekit.calibration.adapters.wikidata`, which uses
Wikidata for *calibration labels*. The builder package uses Wikidata as a
*signal source* for entity attrs (sitelink counts → prominence, etc.).
Both share the SPARQL HTTP primitive in
``resolvekit.calibration.adapters._wikidata_client``.
"""
