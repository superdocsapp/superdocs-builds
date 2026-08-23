# Meridian Health Sciences Building — Whole Building Energy Simulation

**Prepared by:** Calloway Energy Analytics
**Modeler:** R. Vasquez, PE, BEMP
**Software:** EnergyPlus 23.2 via OpenStudio
**Protocol:** ASHRAE 90.1 Appendix G performance rating method
**Model run date:** 14 March 2026

## Annual energy cost summary

| Case                  | Annual energy cost |
|-----------------------|--------------------|
| Baseline building     | $1,284,600         |
| Proposed building     | $ 894,800          |

## Model input summary

| Parameter                     | Baseline      | Proposed      |
|-------------------------------|---------------|---------------|
| Wall assembly U-value         | 0.084         | 0.051         |
| Roof assembly U-value         | 0.048         | 0.027         |
| Window U-value                | 0.42          | 0.28          |
| Window SHGC                   | 0.40          | 0.23          |
| Lighting power density (W/sf) | 0.90          | 0.54          |
| Chiller efficiency (kW/ton)   | 0.62          | 0.48          |
| Heat recovery effectiveness   | none          | 0.72          |

## Notes

Laboratory exhaust rates were modeled identically in baseline and proposed
cases per the process load provisions. The proposed case includes a run-around
heat recovery loop serving the vivarium air handling units.
