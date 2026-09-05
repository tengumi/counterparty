# WEB-07 browser QA

Standard Playwright drives an installed Chrome through CDP. Each invocation creates and removes its own temporary Chrome profile; existing browser tabs and user profiles are untouched.

```sh
npm ci
npm run qa:check
npm run qa:browser                 # prints the matrix; does not start Chrome
npm run dev -- --port 5173         # separate terminal, reviewed source commit
npm run qa:browser -- --capture --mode=fixtures
```

Run capture only after the integrated H1 changes are approved for final browser QA. The runner requires clean reviewed source files (generated WEB-07 artifacts are excluded) and records its HEAD in the manifest. Chrome defaults to the macOS application path; set `WEB07_CHROME` or pass `--chrome=/path/to/chrome`. `--url=http://127.0.0.1:5173` and `--output=../../artifacts/qa/WEB-07` are defaults.

The fixture mode intercepts REST in the browser using the shared synthetic `src/test/apiProjects.ts` fixture. The unchanged app reads existing typed conversation, material, report and evidence fixtures. Interception is scoped to the test browser; there is no production fallback, fabricated database ID or custom browser protocol.

For the separate live CRUD run, start UI API on port 8000 against a disposable imported demo database, as documented in the root README/G6 checkpoint. The Vite proxy supplies same-origin REST and cookies:

```sh
npm run qa:browser -- --capture --mode=live
# Or one final invocation for both:
npm run qa:browser -- --capture --mode=all
```

Live mode signs in as `demo-analyst`, creates one server-owned project, renames it, adds two local companies and one missing INN, reloads, removes one company and reloads again. It leaves the clearly named `WEB-07 browser CRUD ...` project for review; this is a disposable demo database operation. It performs no fixture interception.

Outputs: viewport PNGs plus `manifest-{mode}.json` with source SHA, Chrome version, dataset scope, assertions and limitations. Mock screenshots never certify live report/agent wiring (WEB-08/09). Failures make the process exit nonzero while preserving a reviewable manifest. Screenshots use viewport bounds, not tall stitched pages.

The same fixture sweep also opens the unchanged accepted designer HTML as a separate file URL, using its own support.js and the exact CDN dependency versions it declares. Reference captures include S1/S2 at all three widths and materials at desktop/mobile. The HTML and support.js hashes are recorded. Reference narrow-width shell behavior is compared against Specs 07; the harness does not alter its HTML to manufacture pixel equality.
