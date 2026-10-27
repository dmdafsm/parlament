# ADR 0003: server-rendered web with FastAPI, HTMX and Beer CSS

Status: accepted. Date: 2026-10-27. Related tasks: P1–P5.

## Context

The site must be fast on phones, indexable by search engines, accessible, and simple for one maintainer. The brief asks for Material Design.

## Decision

- FastAPI serves Jinja2 templates; HTMX swaps result tables for filters, sorting and search without a JavaScript build. The same app serves the JSON API (`/api/v1`, OpenAPI at `/api/docs`) and RSS.
- Material Design 3 through **Beer CSS 5** (MIT, CSS-only, ~90 KB) with Material Symbols; charts are plain HTML/CSS bars (no chart library).
- Frontend assets are vendored into `src/parlament/web/static/vendor/` by `scripts/vendor_assets.py` with pinned versions and SHA-256 hashes; the page makes no third-party requests except official MP photos when not cached locally. A strict Content-Security-Policy allows only `'self'` scripts.

## Alternatives and consequences

A SPA (SvelteKit/React + Material Web) would add a second toolchain and client-side rendering for mostly static content; Material Web components are in maintenance mode. Upgrading Beer CSS means re-running the vendoring script and checking the pages.

## Verification

Page tests through the FastAPI test client; browser checks at desktop and phone width.
