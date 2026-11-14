"""Cited reference values that bound the BASS-II microgravity result.

Every number here is quoted from a source; nothing is estimated. Use `REFERENCES` for
citations on the dashboard/project page.

No partial-gravity (Moon 0.16 g, Mars 0.38 g) combustion data exists in PSI yet
(future: LUCI, FM2). The challenge suggests microgravity and 1 g results can bound
intermediate gravity; we report both ends but do NOT claim the Moon value lies
between them (published partial-g work suggests flammability can peak between 0 g and
1 g, so treat any Moon number as unverified).
"""

MARCUM_2016 = (
    "Marcum J.W., Olson S.L., Ferkul P.V. (2016). Correlation of normal gravity mixed "
    "convection blowoff limits with microgravity forced flow blowoff limits. 2016 Spring "
    "Technical Meeting, Central States Section of the Combustion Institute, Knoxville TN. "
    "NASA NTRS 20160012691. https://ntrs.nasa.gov/citations/20160012691"
)
OLSON_FERKUL_2015 = (
    "Olson S.L., Ferkul P.V. (2015). 9th U.S. National Combustion Meeting, The Combustion "
    "Institute, Cincinnati OH (cited as ref. [12] in Marcum et al. 2016)."
)
PSI_BASS2 = "NASA PSI, Burning and Suppression of Solids - II (BASS-II), PSI-25. DOI 10.60555/4qc4-de67"

# PMMA (cast) rods, O2 % by volume.
PMMA_ROD = {
    "microgravity_min_o2": {
        "value": 13.6,
        "quote": "the observed 13.6% O2 minimum concentration needed to get stable "
                 "flames in BASS-II",
        "source": MARCUM_2016 + " p.8, citing " + OLSON_FERKUL_2015,
    },
    "microgravity_zero_stretch_estimate": {
        "value": 13.4,
        "quote": "extrapolating the linear blowoff boundary to zero stretch, which "
                 "estimates that 13.4% O2 is the limiting oxygen concentration below which "
                 "the fuel cannot burn at any stretch rate",
        "source": MARCUM_2016 + " p.8",
    },
    "normal_gravity_bracket": {
        "low": 14.0,   # blew off
        "high": 15.0,  # did not blow off
        "quote": "the rod blew off in repeated tests at 14% oxygen in the larger wind "
                 "tunnel ... A test was then repeated at 15% O2 ... this flame did not "
                 "blow off.",
        "conditions": "1 g, upward axial stagnation flow, ZGRF wind tunnel, 2 cm/s at 14%",
        "source": MARCUM_2016 + " p.3",
    },
}

# Habitat targets from the challenge statement (not a flammability measurement).
HABITAT = {
    "earth_air_o2": 20.9,
    "moon_base_o2_min": 30.0,          # ">= 30 % O2 at <= 10.2 psi" (challenge page)
    "moon_base_pressure_psi_max": 10.2,
    "source": "NASA Space Apps 2026 challenge 'Flame in Freefall' problem statement",
}

REFERENCES = [PSI_BASS2, MARCUM_2016, OLSON_FERKUL_2015, HABITAT["source"]]


def gravity_bounds(material: str = "pmma_rod") -> dict:
    """Limiting-O2 values at the two gravity levels we have data for (O2 % by volume)."""
    if "rod" not in str(material).lower():
        return {"status": "no cited bounds for this material"}
    r = PMMA_ROD
    return {
        "status": "ok",
        "microgravity": r["microgravity_min_o2"]["value"],
        "normal_gravity_low": r["normal_gravity_bracket"]["low"],
        "normal_gravity_high": r["normal_gravity_bracket"]["high"],
        "partial_gravity": None,  # no data in PSI; do not interpolate
        "note": "Moon/Mars (partial g) not measured; not assumed to lie between the bounds.",
    }
