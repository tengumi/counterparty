# Live WEB-08 browser QA

Node **24.19.0**, installed Chrome **150.0.7871.115**, Playwright Core **1.63.0**.
`qa/web08.ts` uses standard `qa/browser.ts`: Chrome/CDP with its own disposable
profile. No request interception, production fixture switch or manual CDP protocol.

```sh
npm ci
npm run lint
npm run typecheck
npm test
npm run build
npm run qa:check
npm run qa:web08                       # matrix only; no browser
npm run dev -- --port 5173             # separate terminal
npm run qa:web08 -- --capture          # final integrated source only
```

Start UI API on 8000 with the imported disposable demo database and migrations as
in the root README. Vite proxies same-origin REST/cookies; the runner signs in as
`demo-analyst`. No secrets are embedded in the browser. It creates two clearly
named `WEB-08 desktop/mobile ...` projects and leaves them for review.

Flow: create project → add INNs 1684017097/7449088645 → pinned financial report →
exact evidence ref/period → back/discuss/draft → server comparison with explicit
year → comparison source/back → reload preserving draft/context/selection.
The runner checks desktop 1440×900 and mobile 390×844; tablet 1024×768 checks panel
bounds. Mobile Enter inserts a newline. Server amounts, report IDs, refs and
periods are compared with rendered values, not fixture constants.

`--url=http://127.0.0.1:5173`, `--output=../../artifacts/qa/WEB-08` and installed
macOS Chrome are defaults. Override Chrome via `WEB08_CHROME` or `--chrome=...`.
Capture requires clean reviewed source and records exact HEAD in `manifest.json`.
Failures preserve their original manifest and PNGs. Targeted follow-ups use
separate files; never relabel old evidence with a newer SHA.

Results: [WEB-08 evidence](../../../artifacts/qa/WEB-08/README.md). Scope is live
REST over provided mock snapshots; chat/agent, documents, user decisions and
native mobile keyboard remain outside this run. Comparison selection is browser
state, not a saved comparison artifact.

## Historical WEB-07 harness

`qa/run.ts` / `npm run qa:browser` belong to the earlier runtime-fixture baseline;
do not use their fixture capture as current production acceptance. Historical
full capture source was **b13cc17**; reviewed tablet/mobile follow-ups used
**6942d5a**. Those PNGs and their hashes remain unchanged in
[WEB-07](../../../artifacts/qa/WEB-07/README.md).

To reproduce old visual fixtures, use that historical source and its runbook.
Current `fixtureMode` is an explicit component-test option and is not exposed by
the production entrypoint. Current end-to-end evidence comes from `qa:web08`.

Targeted follow-up for the preserved WEB-08 project, without repeating project
creation or the full screenshot suite:

```sh
node qa/web08-followup.ts
```

This checks only new draft-chip touch targets, composer/viewport bounds and the
favicon resource. It writes one mobile PNG and a separate follow-up manifest.
