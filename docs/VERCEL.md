# Deploy Maxi's website to Vercel

The landing page and documentation are plain HTML, CSS, and JavaScript in
`website/`. The repository-root `vercel.json` configures static hosting.

Import `krishnakanthpathi/maxi` into Vercel and use these settings:

| Setting | Value |
| --- | --- |
| Root Directory | `./` (the repository root) |
| Framework Preset | Other |
| Output Directory | `website` (configured in `vercel.json`) |
| Build Command | Empty (configured in `vercel.json`) |
| Install Command | Empty (configured in `vercel.json`) |
| Environment Variables | None required |

Keep the Root Directory at the repository root so Vercel reads `vercel.json`.
If an existing Vercel project was detected as a Python framework, change its
Framework Preset to **Other**, remove any dashboard build/install overrides,
and redeploy the latest commit.

The homepage is `/`; the docs page is `/docs`. `cleanUrls` serves `docs.html`
at `/docs`. Downloads link to the published GitHub release assets.

To preview locally:

```bash
python3 -m http.server 4849 --directory website
```

Open `http://localhost:4849` and `http://localhost:4849/docs.html`. Python's
simple server does not apply Vercel's extensionless routing.

For CLI deployment, run `vercel` from the repository root for a preview,
then `vercel --prod` when ready. `.vercelignore` limits CLI uploads to public
website files. Never place provider keys or runtime configuration in `website/`.

Vercel serves the public website. The Maxi daemon and native HUD run on the
user's computer. No provider keys or backend deployment are needed for this site.
Once a production domain is selected, add its canonical URL and `og:url` metadata
to both HTML pages.

Configuration reference: [Vercel's vercel.json documentation](https://vercel.com/docs/project-configuration/vercel-json).
