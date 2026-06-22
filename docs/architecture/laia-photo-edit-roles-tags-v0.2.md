# LAIA Photo Edit Roles + Tags v0.2

Each project photo has one canonical `role` and zero or more non-exclusive `tags`.

- Roles identify a listing or publication slot and remain uniqueness-checked during verification.
- Tags describe visible facets and may appear on any number of images.
- Tags are normalized to lowercase hyphenated values and stored alphabetically.

For example:

```text
role: ports
tags: left-side, ports, rear-panel

role: detail
tags: ports, rear-panel, right-side
```

The canonical `ports` role remains unique, while both images retain searchable port coverage.

## Record-sale examples

Useful record roles include `cover_front`, `cover_back`, `vinyl_a`, `vinyl_b`, `label_a`, `label_b`, `spine`, `inner_sleeve`, `matrix`, `defect`, and `detail`.

Useful tags include `ring-wear`, `corner-wear`, `seam-split`, `spine-wear`, `hype-sticker`, `promo`, `mono`, `stereo`, `first-press`, `matrix-visible`, `side-a`, `side-b`, `scratches`, `scuffs`, `warping`, `insert`, `poster`, `booklet`, and `shrink-wrap`.

Example:

```text
role: cover_front
tags: corner-wear, hype-sticker, ring-wear
```

The optional `config/photo_roles.json` and `config/photo_tags.json` files provide starter vocabularies. Unknown tags warn but remain allowed.
