# /hire-me page snippet for bak-dev.com

A drop-in Next.js App Router page component implementing the spec in
`presence/hire-me-page.md`.

## Install

Assuming bak-dev.com is Next.js 14+ with the App Router and Tailwind:

```bash
mkdir -p app/hire-me
cp /path/to/page.tsx app/hire-me/page.tsx
```

Then:

1. Replace `CALENDLY_URL` at the top of the file with your real Calendly link.
2. (Optional) Swap the inline Tailwind classes for whatever your existing button / card components are.
3. Add a header nav entry pointing to `/hire-me` — the page is useless if nobody can find it.
4. Add 301 redirects from `/freelance` and `/work-with-me` to `/hire-me` (in `next.config.js` or middleware).

## Customization checkpoints

- **Proof strip:** add a section between "What I take on" and "What I won't take on" with logos / client metrics once you have them.
- **Career-OS dynamic card:** swap the existing cards for a server-component that fetches `github.com/akrambak/career-os` star count + last commit and renders it as live proof. (`fetch("https://api.github.com/repos/akrambak/career-os", { next: { revalidate: 3600 } })`)
- **Form vs Calendly:** if you prefer a contact form, drop in a server-action form before the closing CTA and keep Calendly as the secondary path.

## Why no framework components

This file uses plain Tailwind so it works regardless of whether bak-dev.com is
using shadcn/ui, daisyUI, MUI, or none of the above. Replace with your own
components if you have a design system in place; the structure is what matters.
