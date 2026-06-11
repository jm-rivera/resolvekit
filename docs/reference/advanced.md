# Advanced

These modules are for building and calibrating your own data packs and evaluating accuracy. Most users never import them. They require the `[data]` and `[calibration]` extras.

!!! info "Why"
    The core Resolver loads pre-built, bundled data. The builder and calibration modules are for data engineers who want to generate custom entity packs, train calibrators on labeled examples, or run reproducible accuracy benchmarks.

## Data builder

::: resolvekit.builder

## Calibration

::: resolvekit.calibration

---

## Next

[Module-level API](api.md) — The convenience functions (`rk.resolve`, `rk.bulk`, `rk.entity`, etc.) for day-to-day resolution without touching builder or calibration.

[Confidence and calibration](../explanation/confidence.md) — How scores are produced, what the calibrator parameters mean, and why confidence is pack-specific.
