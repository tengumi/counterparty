# WEB-08 — live REST browser verification

**Pass with limitations.** One full live flow passed **53/53 checks**, with 13
viewport PNGs on source `2dce684`. The independent review found small mobile
chip targets; the final targeted proof on `0c20738` confirms all three buttons
are at least 44×44, no document overflow, and a visible composer.

- [Original manifest](manifest.json): project creation, two imported companies,
  pinned reports/financial facts/evidence, server comparison, back/focus and
  persisted draft/context/selection. All 24 API responses succeeded.
- [404 diagnosis](console-diagnosis.json): the original process exited 1 only
  because `/favicon.ico` was absent. Its original console entry is preserved.
- [Final targeted manifest](follow-up/manifest.json): `/favicon.svg` 200,
  consoleErrors/pageErrors empty; mobile targets and bounds pass. Intermediate
  [failed proof](follow-up/failed-1389cec.json) and [CSS diagnosis](follow-up/diagnostic-7d3c67b.json)
  retain their own source SHAs.

| Viewport | Materials | Report / evidence | Comparison / draft |
|---|---|---|---|
|1440×900|[Materials](desktop/materials.png)|[Report](desktop/report.png) · [Evidence](desktop/evidence.png)|[Comparison](desktop/comparison.png) · [Draft](desktop/draft-reloaded.png)|
|390×844|[Materials](mobile/materials.png)|[Report](mobile/report.png) · [Evidence](mobile/evidence.png)|[Comparison](mobile/comparison.png) · [Final draft](follow-up/mobile-draft.png)|
|1024×768|[Overlay panel](tablet/materials.png)|Prior WEB-07 responsive baseline|—|

All 14 PNGs were visually reviewed. The comparison table scrolls inside its
container; source dates/periods, zero and missing are distinct. Older PNGs are
not relabelled with the final fix SHA. [Runbook](../../../apps/web/qa/README.md).

Limits: provided mock snapshots, not current registry data; two-company browser
flow, not 20-company acceptance; unavailable agent/documents/user decisions;
local comparison selection, not a saved artifact. Native OS keyboard and zoom
were not tested. Production build retains its bundle-size warning.
